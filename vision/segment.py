"""Finding the individual bricks in a photo of a pile.

Two backends behind one interface, chosen by `choose_backend()`:

    sam 2    Apache-2.0, pretrained, no training. Recall 0.90 / precision 0.82 on real photos,
             ~10 s per image on MPS. The default when a checkpoint is present.
    opencv   Background learned from the frame border, Otsu, morphology, per-component watershed.
             Recall 0.47 / precision 0.46 on the same photos, 0.09 s. No model, no GPU, no
             network -- which is why it stays as the fallback and is never deleted.

Both numbers are measured, not assumed: 20 images of the Brickognize "uncontrolled" split,
2026-09-19. The gap is large enough that SAM 2 leads, but the fallback is what makes this work on
a laptop with a dead network at a judging table.

Capture guidance still buys more accuracy per minute than either backend: plain surface, bricks
spread out, scale card in frame.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import cv2
import numpy as np

MAX_EDGE = 1600
MIN_AREA_FRAC = 0.0001      # a 1x1 plate in a wide shot is genuinely tiny
MAX_AREA_FRAC = 0.25        # bigger than this is the table, not a brick
MAX_PIECES = 200
MIN_SOLIDITY = 0.45         # ragged blobs are shadow or clutter, not bricks
PEAK_FRAC = 0.35            # watershed seed threshold, applied PER COMPONENT (see _peaks)
CONTAINMENT_MAX = 0.80      # a mask this far inside a bigger mask is a stud, not a brick
SHAPE_FILTER = os.environ.get("VISION_SHAPE_FILTER", "0") == "1"
SAM_POINTS_PER_SIDE = os.environ.get("SAM2_POINTS_PER_SIDE", "32")
# Prompt density, and it is scene-dependent in a way no single value fixes. MEASURED:
#
#   points_per_side   heaped pile (~14 big bricks)   scattered (40-70 tiny parts)
#   32 (default)      94 raw -> 34 kept   (bad)      recall 0.88   (good)
#   16                45 raw -> 17 kept   (good)     recall 0.48   (bad)
#
# Dense prompting segments a big brick into its studs; sparse prompting misses small parts.
# We keep 32 because the SUPPORTED case is bricks spread out in a single layer, where it scores
# 0.88. An attempt to derive this per image from foreground-component size FAILED: in a heap the
# foreground merges into one blob bigger than MAX_AREA_FRAC, so the estimator cannot see
# individual bricks -- precisely the case it was meant to fix. Override with SAM2_POINTS_PER_SIDE
# when photographing a genuine heap.


@dataclass
class Piece:
    """One segmented brick."""

    index: int
    bbox: tuple[int, int, int, int]      # x, y, w, h in the working image
    mask: np.ndarray = field(repr=False)
    area: int = 0
    solidity: float = 1.0

    def crop(self, image: np.ndarray, pad: int = 8) -> np.ndarray:
        x, y, w, h = self.bbox
        H, W = image.shape[:2]
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(W, x + w + pad), min(H, y + h + pad)
        return image[y0:y1, x0:x1]

    def crop_on_white(self, image: np.ndarray, pad: int = 8,
                      full_res: np.ndarray | None = None) -> np.ndarray:
        """The crop with the background knocked out -- what the classifier should see.

        Pass `full_res` (the ORIGINAL photo) to cut the crop at full resolution and only use the
        working image for the mask. Measured on a real 4000x3000 phone photo: cropping from the
        1600px working image gives the classifier ~50px crops and 64 of 74 came back "unknown";
        the same bricks at full resolution are ~140px. Segmentation wants a downscale, the
        classifier wants every pixel it can get, and there is no reason to make them share.
        """
        x, y, w, h = self.bbox
        H, W = image.shape[:2]
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(W, x + w + pad), min(H, y + h + pad)

        m = self.mask[y0:y1, x0:x1]
        if full_res is None or full_res.shape[:2] == image.shape[:2]:
            sub = image[y0:y1, x0:x1].copy()
        else:
            fh, fw = full_res.shape[:2]
            sx, sy = fw / W, fh / H
            fx0, fy0 = int(x0 * sx), int(y0 * sy)
            fx1, fy1 = min(fw, int(x1 * sx)), min(fh, int(y1 * sy))
            sub = full_res[fy0:fy1, fx0:fx1].copy()
            if sub.size == 0:
                return image[y0:y1, x0:x1].copy()
            m = cv2.resize(m, (sub.shape[1], sub.shape[0]), interpolation=cv2.INTER_NEAREST)
        sub[m == 0] = (255, 255, 255)
        return sub


def downscale(image: np.ndarray, max_edge: int = MAX_EDGE) -> np.ndarray:
    h, w = image.shape[:2]
    s = max_edge / max(h, w)
    if s >= 1:
        return image
    return cv2.resize(image, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)


def _background_mask(lab: np.ndarray) -> np.ndarray:
    """Foreground = pixels far from the colour of the border ring.

    The border of a well-framed photo is table, so we learn the background instead of assuming
    it is white -- which is what lets this work on wood, carpet or paper.
    """
    h, w = lab.shape[:2]
    band = max(4, min(h, w) // 25)
    ring = np.concatenate([
        lab[:band].reshape(-1, 3), lab[-band:].reshape(-1, 3),
        lab[:, :band].reshape(-1, 3), lab[:, -band:].reshape(-1, 3),
    ])
    bg = np.median(ring, axis=0)
    dist = np.linalg.norm(lab.astype(np.float32) - bg, axis=2)
    # Otsu on the distance image adapts the threshold to the actual contrast of this photo.
    d8 = np.clip(dist / max(dist.max(), 1e-6) * 255, 0, 255).astype(np.uint8)
    _, fg = cv2.threshold(d8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return fg


def choose_backend() -> str:
    """SAM 2 when it is actually available, OpenCV otherwise. `VISION_SEG` overrides.

    MEASURED on 20 real photos (Brickognize "uncontrolled" split, 2026-09-19):

        backend    recall   precision   per image
        opencv      0.47      0.46        0.09 s
        sam 2       0.90      0.82       10.2 s   (hiera_small, MPS)

    Nearly double on both metrics. 10 s for one photo is fine behind a progress bar; 0.47 recall
    is not fine at a judging table. So SAM 2 leads and OpenCV is the fallback -- which is also
    what keeps this working on a laptop with no checkpoint and no network.
    """
    forced = os.environ.get("VISION_SEG")
    if forced:
        return forced
    if not os.environ.get("SAM2_CHECKPOINT"):
        return "opencv"
    try:
        import sam2  # noqa: F401
        return "sam2"
    except ImportError:
        return "opencv"


def segment(image_bgr: np.ndarray, *, backend: str | None = None) -> tuple[np.ndarray, list[Piece]]:
    """Return (working image, pieces). The working image is what all bboxes/masks refer to."""
    backend = backend or choose_backend()
    img = downscale(image_bgr)
    if backend == "sam2":
        try:
            return img, sam2_segment(img)
        except RuntimeError as exc:
            print(f"  ! sam2 unavailable ({exc}); falling back to opencv")
            return img, opencv_segment(img)
    return img, opencv_segment(img)


def _peaks(fg: np.ndarray, dist: np.ndarray) -> np.ndarray:
    """Watershed seeds, thresholded PER CONNECTED COMPONENT.

    A single global `PEAK_FRAC * dist.max()` is scaled by the LARGEST blob in the frame, so one
    big brick (or two bricks merged into one blob) silently raises the bar above every small
    brick's distance peak and they never get a seed at all. Measured on real photos: global
    thresholding scored 0.19 recall where per-component scored 0.41 on the same images.

    Thresholding each component against its own maximum makes the seed test scale-free.
    """
    out = np.zeros(fg.shape, np.uint8)
    n, labels = cv2.connectedComponents((fg > 0).astype(np.uint8))
    for lb in range(1, n):
        comp = labels == lb
        local = dist[comp]
        if local.size == 0:
            continue
        thr = PEAK_FRAC * float(local.max())
        out[comp & (dist > thr)] = 255
    return out


def opencv_segment(img: np.ndarray) -> list[Piece]:
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    fg = _background_mask(lab)

    k = np.ones((5, 5), np.uint8)
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, k, iterations=1)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, k, iterations=2)

    # Watershed splits bricks that touch -- failure mode #1 in a real pile.
    dist = cv2.distanceTransform(fg, cv2.DIST_L2, 5)
    peaks = _peaks(fg, dist)
    n_markers, markers = cv2.connectedComponents(peaks)
    unknown = cv2.subtract(fg, peaks)
    markers = markers + 1
    markers[unknown == 255] = 0
    markers = cv2.watershed(img, markers)

    H, W = img.shape[:2]
    frame = H * W
    pieces: list[Piece] = []
    for label in range(2, n_markers + 2):
        mask = np.uint8(markers == label) * 255
        area = int((mask > 0).sum())
        if not (MIN_AREA_FRAC * frame <= area <= MAX_AREA_FRAC * frame):
            continue
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            continue
        c = max(cnts, key=cv2.contourArea)
        hull_area = cv2.contourArea(cv2.convexHull(c)) or 1.0
        solidity = float(cv2.contourArea(c) / hull_area)
        if solidity < MIN_SOLIDITY:
            continue
        x, y, w, h = cv2.boundingRect(c)
        pieces.append(Piece(len(pieces), (x, y, w, h), mask, area, solidity))

    return suppress_parts(pieces)


def sam2_segment(img: np.ndarray) -> list[Piece]:
    """SAM 2 automatic mask generation (Apache-2.0, pretrained -- no training needed).

        pip install "git+https://github.com/facebookresearch/sam2.git"
        export SAM2_CHECKPOINT=/path/to/sam2.1_hiera_small.pt
        export SAM2_CONFIG=configs/sam2.1/sam2.1_hiera_s.yaml
        VISION_SEG=sam2 python -m vision.pipeline photo.jpg

    Expect OVER-segmentation on glossy plastic -- separate masks for a brick's top face, its
    studs and its shadow. The area/solidity/NMS filtering below is not optional.
    """
    try:
        import torch
        from sam2.build_sam import build_sam2
        from sam2.automatic_mask_generator import SAM2AutomaticMaskGenerator
    except ImportError as exc:
        raise RuntimeError(
            "VISION_SEG=sam2 but sam2 is not installed. Either\n"
            '  pip install "git+https://github.com/facebookresearch/sam2.git"\n'
            "or drop back to the classical path with VISION_SEG=opencv (the default)."
        ) from exc

    ckpt = os.environ.get("SAM2_CHECKPOINT")
    cfg = os.environ.get("SAM2_CONFIG", "configs/sam2.1/sam2.1_hiera_s.yaml")
    if not ckpt:
        raise RuntimeError("set SAM2_CHECKPOINT to a downloaded sam2.1 checkpoint")

    device = "cuda" if torch.cuda.is_available() else (
        "mps" if torch.backends.mps.is_available() else "cpu")
    model = build_sam2(cfg, ckpt, device=device, apply_postprocessing=False)
    gen = SAM2AutomaticMaskGenerator(model, points_per_side=int(SAM_POINTS_PER_SIDE),
                                     pred_iou_thresh=0.8, stability_score_thresh=0.9)
    raw = gen.generate(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    return _filter_masks(raw, img.shape[:2])


def _filter_masks(raw: list[dict], shape: tuple[int, int]) -> list[Piece]:
    H, W = shape
    frame = H * W
    cand: list[Piece] = []
    for m in raw:
        seg = m["segmentation"].astype(np.uint8) * 255
        area = int(m.get("area", (seg > 0).sum()))
        if not (MIN_AREA_FRAC * frame <= area <= MAX_AREA_FRAC * frame):
            continue
        cnts, _ = cv2.findContours(seg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            continue
        c = max(cnts, key=cv2.contourArea)
        hull = cv2.contourArea(cv2.convexHull(c)) or 1.0
        solidity = float(cv2.contourArea(c) / hull)
        if solidity < 0.6:
            continue
        x, y, w, h = cv2.boundingRect(c)
        cand.append(Piece(0, (x, y, w, h), seg, area, solidity))

    return suppress_parts(cand)


# Geometric plausibility bounds for "is this crop a whole brick?", fitted on 8 real photos and
# validated on 10 HELD-OUT ones. Measured trade at several tightnesses:
#
#   tightness   false positives removed   true bricks lost   precision
#   gentle              86%                    5.8%          0.84 -> 0.97
#   medium              87%                   10.3%          0.84 -> 0.97
#   tight               92%                   25.1%          0.84 -> 0.98
#
# We keep the gentle setting and default it OFF: it was fitted on one dataset of small Technic
# parts on white, and trading 6% recall for 13% precision is a product decision that should be
# made against YOUR photos, not against someone else's. Turn it on with VISION_SHAPE_FILTER=1
# and re-measure.
#
# Worth stating plainly: this replaces a trained classifier. Auto-labelling every SAM detection
# against ground truth gave ~5,400 positive and ~700 negative crops -- enough to train a
# brick/not-brick CNN. Four arithmetic comparisons got the same separation with no model to
# train, host, or keep in sync. The cheap thing was tried first and it won.
SHAPE_BOUNDS = {
    "area_ratio": (0.42, 11.1),   # area relative to the median detection in the same photo
    "aspect": (1.0, 5.2),         # long side / short side
    "solidity": (0.63, 0.98),     # contour area / convex hull area
    "fill": (0.17, 0.90),         # mask area / bbox area
}


def plausible_brick(p: "Piece", median_area: float) -> bool:
    """Cheap geometric gate. See SHAPE_BOUNDS for the measured trade-off."""
    x, y, w, h = p.bbox
    lo, hi = SHAPE_BOUNDS["area_ratio"]
    if not lo <= p.area / max(median_area, 1e-6) <= hi:
        return False
    lo, hi = SHAPE_BOUNDS["aspect"]
    if not lo <= max(w, h) / max(1, min(w, h)) <= hi:
        return False
    lo, hi = SHAPE_BOUNDS["solidity"]
    if not lo <= p.solidity <= hi:
        return False
    lo, hi = SHAPE_BOUNDS["fill"]
    return lo <= p.area / max(w * h, 1e-6) <= hi


def suppress_parts(cand: list[Piece]) -> list[Piece]:
    """Drop masks that are PARTS of a brick we already kept -- studs, faces, logos.

    IoU-based NMS alone does not do this, and that is the single biggest failure we measured.
    A stud sitting on a 2x4 brick has IoU ~0.02 with it (tiny box inside a big one), so every
    IoU threshold keeps both. On a real heaped pile SAM 2 returned 82 masks for ~14 bricks:
    it had boxed each individual stud, including the moulded "LEGO" text on top of them.

    Containment is the right test, not overlap: if most of a candidate's area lies inside a
    larger candidate, it is a feature OF that brick rather than a brick.
    """
    cand.sort(key=lambda p: -p.area)
    kept: list[Piece] = []
    for p in cand:
        if any(_iou(p.bbox, q.bbox) >= 0.5 for q in kept):
            continue
        if any(_contained(p.bbox, q.bbox) >= CONTAINMENT_MAX for q in kept):
            continue
        p.index = len(kept)
        kept.append(p)
    if SHAPE_FILTER and kept:
        import statistics
        med = statistics.median(p.area for p in kept)
        kept = [p for p in kept if plausible_brick(p, med)]
        for i, p in enumerate(kept):
            p.index = i
    return kept[:MAX_PIECES]


def _contained(inner, outer) -> float:
    """Fraction of `inner`'s area that lies inside `outer`."""
    ax, ay, aw, ah = inner
    bx, by, bw, bh = outer
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    a_area = aw * ah
    return (ix * iy) / a_area if a_area else 0.0


def _iou(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union else 0.0
