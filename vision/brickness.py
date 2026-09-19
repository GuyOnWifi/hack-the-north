"""Is this crop a brick, or is it the table?

WHY THIS EXISTS. Measured on the user's own 9 phone photos: SAM 2 returned 1,296 crops and 562
of them (43%) are not LEGO at all. They are the surface the bricks were photographed on -- the
woven pattern of a blanket in most photos, the oval slots of a white pegboard in lego3/lego7.
Both are distinct blobs on a light ground with high solidity, so segmentation keeps them, the
existing geometric gate passes them, and Brickognize -- which never returns nothing and never
scores below 0.50 -- gamely calls them "4342 Bread/Baguette" or "3704 Technic Axle 2L". Every one
of those is a phantom brick in the user's inventory and a wasted classifier call.

WHAT THE LABELS ARE. 1,296 crops were labelled BY EYE (data/real/crop_labels.json): 730 brick,
562 not_brick, 4 unsure. Nothing here was labelled from a predicted part id, and no crop was
labelled from a feature this module filters on -- that circularity is exactly how you manufacture
a number that means nothing. The 4 unsure crops are excluded from fitting and from scoring.

THE FEATURES. All cheap, all explicable at a judging table, ~1 ms per crop:

    sat_p90          bricks are moulded plastic in saturated colours; fabric and pegboard are not.
                     P90 not mean, so a mostly-dark brick with one coloured face still counts.
    lap_var          variance of Laplacian -- sharpness. Bricks have in-focus moulded detail;
                     the background artefacts are out of the focal plane and blurred.
    edge_density     Canny pixels per unit area inside the mask. Same idea, different failure mode.
    straight_frac    fraction of the silhouette made of long straight runs. The single most
                     LEGO-specific thing about a brick, and the thing the blanket blobs and
                     pegboard slots most conspicuously lack: they are rounded capsules.
    lines            total length of long straight edges INSIDE the piece, over sqrt(area). A
                     brick is facets: stud rims, panel lines, the step down to a slope. This is
                     the one feature that separates bricks from all three artefact families by
                     the same margin (brick 0.076 vs fabric 0.006 / pegboard 0.039 / blanket
                     0.041), which is why it is the part of this model most likely to survive a
                     surface we have never seen.
    specular         bright low-saturation pixels: the gloss highlight of plastic.
    sat_std, val_std within-piece variation. Moulded parts have studs, tubes and facets; a woven
                     blob is one flat colour.
    circles          HoughCircles hits, normalised -- studs seen from above.
    aspect/fill/solidity  geometry, kept because it is free and it is what the existing
                     VISION_SHAPE_FILTER already uses.

COLOUR IS DELIBERATELY NOT DECISIVE. The labellers flagged tan, dark grey, black and brown bricks
that any saturation threshold on its own would delete, and lego6_126 -- a genuine reddish-brown
Technic axle that looks exactly like a blanket blob. Saturation earns a weight here; it is never
allowed to be the whole decision. See WEIGHTS and the honest failure list at the bottom.
"""

from __future__ import annotations

import math
import os

import cv2
import numpy as np

ENABLED = os.environ.get("VISION_BRICKNESS", "0") == "1"

# Order matters: WEIGHTS lines up with this.
FEATURES = (
    "sat_p90",
    "sat_std",
    "val_std",
    "lap_var",
    "edge_density",
    "straight_frac",
    "lines",
    "specular",
    "circles",
    "aspect",
    "fill",
    "solidity",
)

_BG = 250          # crop_on_white paints the background pure white; >=250 on all three is background
_NORM_EDGE = 96    # features are computed at this scale so a 4000px photo and a 1600px one agree


def _mask_of(crop: np.ndarray) -> np.ndarray:
    """The piece, as knocked out by Piece.crop_on_white (background is pure white)."""
    bg = (crop[:, :, 0] >= _BG) & (crop[:, :, 1] >= _BG) & (crop[:, :, 2] >= _BG)
    m = (~bg).astype(np.uint8)
    if m.sum() < 16:                      # a genuinely white/overexposed piece: use the whole crop
        m = np.ones(crop.shape[:2], np.uint8)
    return m


def _straight_frac(mask: np.ndarray) -> float:
    """Fraction of the silhouette's perimeter that lies on long straight runs.

    A 2x4 brick is four long straight runs. A blanket blob is a capsule: approxPolyDP spends its
    vertices on the curve and no single run is long.
    """
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return 0.0
    c = max(cnts, key=cv2.contourArea)
    peri = cv2.arcLength(c, True)
    if peri <= 0:
        return 0.0
    approx = cv2.approxPolyDP(c, 0.012 * peri, True).reshape(-1, 2).astype(np.float64)
    if len(approx) < 2:
        return 0.0
    seg = np.linalg.norm(np.roll(approx, -1, axis=0) - approx, axis=1)
    return float(seg[seg >= 0.12 * peri].sum() / peri)


def features(crop_bgr: np.ndarray, *, solidity: float | None = None) -> dict[str, float]:
    """Cheap, explicable descriptors of one crop. `solidity` comes free from segmentation."""
    if crop_bgr is None or crop_bgr.size == 0:
        return {k: 0.0 for k in FEATURES}

    h0, w0 = crop_bgr.shape[:2]
    s = _NORM_EDGE / max(h0, w0, 1)
    if s < 1:
        crop = cv2.resize(crop_bgr, (max(1, int(w0 * s)), max(1, int(h0 * s))),
                          interpolation=cv2.INTER_AREA)
    else:
        crop = crop_bgr
    mask = _mask_of(crop)
    n = int(mask.sum())
    if n < 16:
        return {k: 0.0 for k in FEATURES}

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1][mask > 0].astype(np.float32) / 255.0
    val = hsv[:, :, 2][mask > 0].astype(np.float32) / 255.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

    # Erode before any gradient measure: the knockout boundary is a synthetic step edge and would
    # otherwise dominate both lap_var and edge_density with a number about the mask, not the piece.
    k = np.ones((3, 3), np.uint8)
    inner = cv2.erode(mask, k, iterations=2)
    if inner.sum() < 16:
        inner = mask
    ii = inner > 0

    lap = cv2.Laplacian(cv2.GaussianBlur(gray, (3, 3), 0), cv2.CV_32F)
    lap_var = float(lap[ii].var())
    edges = cv2.Canny(gray, 60, 160)
    edge_density = float((edges[ii] > 0).mean())

    # Straight edges INSIDE the piece. Canny runs on the untouched grey -- blanking the outside
    # first would paint a synthetic step along the mask edge, and HoughLinesP would dutifully
    # report the silhouette as internal structure. Measured: a flat grey rectangle on white
    # scored lines=0.09 that way, all of it the boundary. Masking the EDGE IMAGE with a mask
    # eroded well clear of the boundary (4px at the 96px working scale) takes it to 0.00.
    deep = cv2.erode(mask, k, iterations=4)
    if deep.sum() < 16:
        deep = inner
    inner_edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 60, 160)
    inner_edges[deep == 0] = 0
    minlen = max(6, int(0.25 * math.sqrt(n)))
    segs = cv2.HoughLinesP(inner_edges, 1, np.pi / 180, threshold=max(12, minlen),
                           minLineLength=minlen, maxLineGap=3)
    total_len = 0.0
    if segs is not None:
        for x1, y1, x2, y2 in segs.reshape(-1, 4):
            total_len += math.hypot(float(x2 - x1), float(y2 - y1))
    lines = min(total_len / max(math.sqrt(n), 1.0), 20.0) / 20.0

    circles = cv2.HoughCircles(cv2.medianBlur(gray, 3), cv2.HOUGH_GRADIENT, dp=1.5,
                               minDist=max(4, _NORM_EDGE // 12), param1=120, param2=26,
                               minRadius=3, maxRadius=max(4, _NORM_EDGE // 5))
    n_circ = 0
    if circles is not None:
        for cx, cy, _r in np.round(circles[0]).astype(int):
            if 0 <= cy < mask.shape[0] and 0 <= cx < mask.shape[1] and mask[cy, cx]:
                n_circ += 1

    ys, xs = np.nonzero(mask)
    bw = xs.max() - xs.min() + 1
    bh = ys.max() - ys.min() + 1
    if solidity is None:
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if cnts:
            c = max(cnts, key=cv2.contourArea)
            hull = cv2.contourArea(cv2.convexHull(c)) or 1.0
            solidity = float(cv2.contourArea(c) / hull)
        else:
            solidity = 1.0

    return {
        "sat_p90": float(np.percentile(sat, 90)),
        "sat_std": float(sat.std()),
        "val_std": float(val.std()),
        "lap_var": float(math.log1p(lap_var)),
        "edge_density": edge_density,
        "straight_frac": _straight_frac(mask),
        "lines": lines,
        "specular": float(((val > 0.94) & (sat < 0.20)).mean()),
        "circles": min(n_circ, 8) / 8.0,
        "aspect": min(max(bw, bh) / max(1, min(bw, bh)), 8.0) / 8.0,
        "fill": n / float(bw * bh),
        "solidity": float(solidity),
    }


def vector(crop_bgr: np.ndarray, *, solidity: float | None = None) -> np.ndarray:
    f = features(crop_bgr, solidity=solidity)
    return np.array([f[k] for k in FEATURES], dtype=np.float64)


# ---------------------------------------------------------------------------------------------
# Logistic regression on the 12 standardised features above, fitted on all 1,292 usable labelled
# crops by scripts/fit_brickness.py. Regenerate with `python scripts/fit_brickness.py --emit`.
#
# MEASURED, HELD OUT BY PHOTO (9 folds; each crop scored by a model that never saw one crop from
# its photo -- a random crop split would be meaningless here, because hundreds of the artefacts
# are near-duplicates of each other within a photo):
#
#     threshold   real bricks lost    phantoms kept    brick P / R     not_brick P / R
#     do nothing      0 / 730            562 / 562         -                 -
#     0.10            4 (0.5%)            50 (8.9%)     0.936 / 0.995     0.992 / 0.911
#     0.20  <-        9 (1.2%)            31 (5.5%)     0.959 / 0.988     0.983 / 0.945
#     0.50           21 (2.9%)            24 (4.3%)     0.967 / 0.971     0.962 / 0.957
#     0.80           45 (6.2%)            16 (2.8%)     0.977 / 0.938     0.924 / 0.972
#
# WHY 0.20 AND NOT THE BALANCED POINT. The two errors are not symmetric. A discarded brick is a
# piece the user physically owns, gone from the inventory with no way to notice; a kept phantom is
# one wasted API call and one wrong row that the user can see and the reviewer can delete. So we
# sit on the brick-preserving side: 0.20 keeps 98.8% of real bricks while removing 94.5% of the
# background. Walking up to 0.50 buys 7 fewer phantoms and costs 12 more bricks, which is the
# wrong direction on that trade; walking down to 0.10 saves 5 bricks but lets 19 more phantoms
# through, and each of those is an API call plus a wrong inventory row. 0.20 is where the
# exchange rate turns over.
#
# WHICH BRICKS IT LOSES, which matters more than how many. All 9 are light grey, white or black:
# lego3_057 "light grey slope, crisp straight edges", lego7_000 "light grey Technic brick",
# lego8_002 "white studded plate", lego6_005 "black vehicle base". The residual damage is
# concentrated exactly where the labellers warned it would be -- desaturated elements -- so a
# scan of a mostly-grey Technic set is the case to re-measure before turning this on.
#
# WHAT THIS DOES NOT DO -- read before trusting it on a new table. Held out by ARTEFACT FAMILY
# instead of by photo (train on two surfaces, test on a third it has never seen):
#
#     unseen pegboard   85/90  removed (0.94)      bricks kept 108/110
#     unseen blanket   407/449 removed (0.91)      bricks kept 396/403
#     unseen fabric      1/23  removed (0.04)      bricks kept 214/217
#
# Pegboard and blanket transfer. Pale towel/terry fabric does NOT: the model keeps 22 of 23 of
# them. Those scraps are pale, ragged and high-edge-density, so the geometry terms vote "brick"
# loudly enough to overrule the low saturation. This filter has learned the two artefacts it saw
# a lot of, and it will not survive an arbitrary new surface -- which is exactly why it ships
# behind VISION_BRICKNESS=1 and defaults OFF.
MEAN = np.array([0.534403, 0.150765, 0.178405, 4.8066, 0.108607, 0.507784, 0.06017,
                 0.016066, 0.283959, 0.210329, 0.71839, 0.943415])
SCALE = np.array([0.325852, 0.077638, 0.043339, 0.600035, 0.069719, 0.140058, 0.068683,
                  0.016773, 0.263051, 0.067206, 0.132468, 0.03869])
# sat_std +3.01, val_std -2.32, lap_var +1.78, aspect -1.63, lines +1.41, fill -1.22,
# edge_density -0.89, sat_p90 +0.85, circles +0.51, straight_frac +0.23, solidity +0.22,
# specular -0.10. Positive = votes "brick".
#
# Read that list before trusting the model. The strongest single term is sat_std -- how much the
# saturation VARIES across the piece, not how saturated it is -- and sat_p90 is only eighth. That
# is a better story than a colour threshold (a moulded part has a lit face, a shaded face and a
# stud ring; a woven blob is one flat colour) but it is still substantially a colour argument,
# and the error breakdown above shows where that bites: every brick it loses is a grey one.
WEIGHTS = np.array([0.85127, 3.007049, -2.320868, 1.783078, -0.887145, 0.231795, 1.409456,
                    -0.103578, 0.508501, -1.625942, -1.224057, 0.218062])
BIAS = 2.727591
THRESHOLD = 0.20


def score(crop_bgr: np.ndarray, *, solidity: float | None = None) -> float:
    """P(this crop is a real LEGO element), 0..1."""
    z = (vector(crop_bgr, solidity=solidity) - MEAN) / SCALE
    return float(1.0 / (1.0 + math.exp(-(float(z @ WEIGHTS) + BIAS))))


def is_brick(crop_bgr: np.ndarray, *, solidity: float | None = None) -> bool:
    return score(crop_bgr, solidity=solidity) >= THRESHOLD
