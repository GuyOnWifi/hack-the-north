"""Colour identification -- computed from pixels, never learned, never guessed by an LLM.

Brickognize identifies the MOULD. Colour is a separate, solvable photometric problem, so we do it
ourselves: median LAB over the eroded mask (specular highlights and shadow removed), then nearest
neighbour against the official LDraw palette restricted to colours people actually own.

Restricting the palette is what stops "Dark Azure vs Medium Azure" coin-flips that read as bugs.
"""

from __future__ import annotations

import functools
import pathlib
import re

import numpy as np

LDCONFIG = pathlib.Path(__file__).resolve().parents[1] / "data" / "LDConfig.ldr"
_COLOUR_RE = re.compile(
    r"^0 !COLOUR\s+(\S+)\s+CODE\s+(\d+)\s+VALUE\s+#([0-9A-Fa-f]{6})", re.M)

# The ~40 colours a real home bin actually contains. Everything else in the 322-entry palette is
# a trap: it turns a confident right answer into an unconfident near-miss.
COMMON = {
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 14, 15, 17, 18, 19, 22, 25, 26, 27, 28, 29,
    70, 71, 72, 73, 74, 77, 78, 84, 85, 191, 212, 226, 272, 288, 308, 320, 321, 326, 484,
}


def _srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB (0-255, shape [..., 3]) -> CIE L*a*b* under D65."""
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124564, 0.3575761, 0.1804375],
                  [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]])
    xyz = c @ m.T
    white = np.array([0.95047, 1.00000, 1.08883])
    t = xyz / white
    d = 6 / 29
    f = np.where(t > d ** 3, np.cbrt(t), t / (3 * d ** 2) + 4 / 29)
    fx, fy, fz = f[..., 0], f[..., 1], f[..., 2]
    return np.stack([116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)], axis=-1)


@functools.cache
def palette(common_only: bool = True) -> list[tuple[int, str, tuple[int, int, int], np.ndarray]]:
    """(code, name, rgb, lab) for every LDraw colour."""
    if not LDCONFIG.exists():
        raise FileNotFoundError(
            f"{LDCONFIG} missing. Fetch it with:\n"
            f"  curl -A 'Bricolage/0.1' https://library.ldraw.org/library/official/LDConfig.ldr "
            f"-o {LDCONFIG}")
    out = []
    for name, code, hexv in _COLOUR_RE.findall(LDCONFIG.read_text()):
        code = int(code)
        if common_only and code not in COMMON:
            continue
        rgb = tuple(int(hexv[i:i + 2], 16) for i in (0, 2, 4))
        out.append((code, name.replace("_", " "), rgb, _srgb_to_lab(np.array(rgb))))
    return out


def nearest(rgb, common_only: bool = True) -> tuple[int, str, float]:
    """Nearest LDraw colour to an sRGB triple. Returns (code, name, confidence 0-1).

    Confidence is 1 - d_best/d_second: high when one colour wins clearly, low when two are
    equally close -- which is exactly when the UI should ask the human.
    """
    lab = _srgb_to_lab(np.asarray(rgb, dtype=np.float64))
    pal = palette(common_only)
    dists = sorted((float(np.linalg.norm(lab - p[3])), p[0], p[1]) for p in pal)
    best, second = dists[0], dists[1] if len(dists) > 1 else dists[0]
    conf = 0.0 if second[0] == 0 else max(0.0, min(1.0, 1 - best[0] / second[0]))
    return best[1], best[2], conf


def estimate_illuminant(image_bgr: np.ndarray) -> np.ndarray:
    """Per-channel gains that neutralise the scene's colour cast (grey-world).

    Measured need: on real photos the top colour confusions were all WARM shifts --
    Black -> Dark Brown (132x), Light Bluish Grey -> Medium Nougat (119x), -> Dark Tan (85x),
    -> Dark Orange (70x). Those are not matching errors, they are an uncorrected illuminant:
    LEGO grey under warm indoor light really does have the raw RGB of tan.

    Grey-world assumes the average of a scene is neutral. A pile of mixed bricks on a plain
    surface satisfies that far better than most photographs do.
    """
    px = image_bgr.reshape(-1, 3).astype(np.float64)
    # Ignore blown-out and near-black pixels; both corrupt the estimate.
    lum = px @ np.array([0.114, 0.587, 0.299])
    keep = px[(lum > 15) & (lum < 245)]
    if len(keep) < 32:
        keep = px
    means = keep.mean(axis=0)
    means[means < 1e-6] = 1e-6
    gains = means.mean() / means
    return np.clip(gains, 0.5, 2.0)


def colour_of(image_bgr: np.ndarray, mask: np.ndarray,
              illuminant: np.ndarray | None = None) -> tuple[int, str, float]:
    """Dominant LDraw colour of one masked brick.

    Drops the brightest 15% (specular highlight off glossy ABS reads as white) and the darkest
    10% (self-shadow and the gap between bricks) before taking the median.

    Pass `illuminant` from estimate_illuminant() on the FULL frame -- a single brick crop is far
    too small a sample to estimate a white point from.
    """
    import cv2

    m = cv2.erode(mask.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1)
    px = image_bgr[m > 0]
    if len(px) < 12:
        px = image_bgr[mask > 0]
    if len(px) == 0:
        return 15, "White", 0.0

    lum = px.astype(np.float64) @ np.array([0.114, 0.587, 0.299])   # BGR weights
    lo, hi = np.percentile(lum, 10), np.percentile(lum, 85)
    keep = px[(lum >= lo) & (lum <= hi)]
    if len(keep) < 8:
        keep = px
    bgr = np.median(keep, axis=0)
    if illuminant is not None:
        bgr = np.clip(bgr * illuminant, 0, 255)
    return nearest((bgr[2], bgr[1], bgr[0]))
