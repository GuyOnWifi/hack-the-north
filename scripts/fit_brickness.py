"""Fit and HONESTLY evaluate the brick/not-brick discriminator in vision/brickness.py.

    .venv/bin/python scripts/fit_brickness.py            # report only
    .venv/bin/python scripts/fit_brickness.py --emit     # also print the constants to paste back

Two rules this script exists to enforce:

SPLIT BY PHOTO, NEVER BY CROP. The background artefact repeats within a photo -- hundreds of
near-identical blanket blobs. A random crop split would put near-duplicates on both sides and
score ~0.99 while generalising to nothing. Every number below comes from a model that never saw
a single crop from the photo it is scoring.

AND THEN DO NOT BELIEVE THAT NUMBER EITHER. Photo holdout still leaves the SAME blanket in the
training fold, because it appears in 5 of the 9 photos. So we also hold out a whole artefact
FAMILY (the labellers' own description of what the crops are: fabric / pegboard / blanket) and
report that too. It is much worse, and it is the number that predicts a new user's table.

Labels come from data/real/crop_labels.json -- 1,296 crops labelled by eye. No crop was ever
labelled from its predicted part id, and no crop was labelled from a feature this model uses.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from vision.brickness import FEATURES, features  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
LABELS = ROOT / "data/real/crop_labels.json"
INDEX = ROOT / "data/real/crops_index.json"
CROPS = ROOT / "data/real/crops"

# What the not_brick crops in each photo actually ARE, transcribed from the labellers' notes.
# Used only to define the harsh holdout -- never as an input to the model.
FAMILY = {
    "lego.jpg": "fabric", "lego1.jpg": "fabric", "lego2.jpg": "fabric",
    "lego3.jpg": "pegboard",
    "lego4.jpg": "blanket", "lego5.jpg": "blanket", "lego6.jpg": "blanket",
    "lego7.jpg": "blanket", "lego8.jpg": "blanket",
}

L2 = 1.0
ITERS = 6000
LR = 0.5
THRESHOLD = 0.20      # see choose_operating_point() and the table this script prints


def load() -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str], int]:
    meta = {r["id"]: r for r in json.loads(INDEX.read_text())}
    labelled = json.loads(LABELS.read_text())["labels"]
    n_unsure = sum(1 for r in labelled if r["label"] == "unsure")

    X, y, photo, ids = [], [], [], []
    t0 = time.perf_counter()
    for rec in labelled:
        if rec["label"] == "unsure":          # dropped from fitting AND from scoring, by design
            continue
        cid = rec["crop_id"]
        img = cv2.imread(str(CROPS / f"{cid}.png"))
        f = features(img, solidity=meta[cid]["solidity"])
        X.append([f[k] for k in FEATURES])
        y.append(1.0 if rec["label"] == "brick" else 0.0)
        photo.append(meta[cid]["photo"])
        ids.append(cid)
    dt = (time.perf_counter() - t0) / max(len(X), 1) * 1000
    print(f"{len(X)} labelled crops ({int(sum(y))} brick / {int(len(y) - sum(y))} not_brick), "
          f"{n_unsure} unsure dropped.  features: {dt:.2f} ms/crop")
    return np.array(X), np.array(y), np.array(photo), ids, n_unsure


def fit(X: np.ndarray, y: np.ndarray):
    """Logistic regression by plain gradient descent -- 12 weights, no sklearn dependency."""
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = (X - mu) / sd
    w = np.zeros(X.shape[1])
    b = 0.0
    for _ in range(ITERS):
        p = 1 / (1 + np.exp(-(Z @ w + b)))
        w -= LR * (Z.T @ (p - y) / len(y) + L2 * w / len(y))
        b -= LR * (p - y).mean()
    return mu, sd, w, b


def apply(X, model):
    mu, sd, w, b = model
    return 1 / (1 + np.exp(-(((X - mu) / sd) @ w + b)))


def heldout(X, y, groups) -> np.ndarray:
    """Score every crop with a model that never saw its group."""
    s = np.zeros(len(y))
    for g in sorted(set(groups)):
        te = groups == g
        s[te] = apply(X[te], fit(X[~te], y[~te]))
    return s


def counts(s, y, thr):
    p = s >= thr
    return (int(((p == 1) & (y == 1)).sum()), int(((p == 1) & (y == 0)).sum()),
            int(((p == 0) & (y == 1)).sum()), int(((p == 0) & (y == 0)).sum()))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit", action="store_true", help="print the constants for brickness.py")
    args = ap.parse_args()

    X, y, photo, ids, n_unsure = load()
    fam = np.array([FAMILY[p] for p in photo])

    s_photo = heldout(X, y, photo)
    s_fam = heldout(X, y, fam)

    print("\n=== HELD OUT BY PHOTO (9 folds). Doing nothing = 0 bricks lost, 562 phantoms kept.")
    print(f"{'thr':>5} {'bricks lost':>12} {'phantoms kept':>14} {'brick P':>8} {'brick R':>8} "
          f"{'not_brick P':>12} {'not_brick R':>12}")
    for thr in (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.65, 0.80):
        tp, fp, fn, tn = counts(s_photo, y, thr)
        mark = "  <- shipped" if abs(thr - THRESHOLD) < 1e-9 else ""
        print(f"{thr:5.2f} {fn:12d} {fp:14d} {tp/max(tp+fp,1):8.3f} {tp/(tp+fn):8.3f} "
              f"{tn/max(tn+fn,1):12.3f} {tn/(tn+fp):12.3f}{mark}")

    print(f"\n=== PER PHOTO at thr={THRESHOLD}")
    for p in sorted(set(photo)):
        m = photo == p
        tp, fp, fn, tn = counts(s_photo[m], y[m], THRESHOLD)
        print(f"  {p:11s} bricks kept {tp:3d}/{tp+fn:3d}   background removed {tn:3d}/{tn+fp:3d}")

    print("\n=== HELD OUT BY ARTEFACT FAMILY (the harsh test: a surface never seen in training)")
    for f in ("fabric", "pegboard", "blanket"):
        m = fam == f
        tp, fp, fn, tn = counts(s_fam[m], y[m], THRESHOLD)
        print(f"  unseen {f:9s} bricks kept {tp:3d}/{tp+fn:3d}   "
              f"background removed {tn:3d}/{tn+fp:3d} ({tn/max(tn+fp,1):.2f})")

    model = fit(X, y)                      # shipped weights: fitted on everything
    mu, sd, w, b = model
    print("\n=== SHIPPED MODEL (fitted on all 1,292 labelled crops; the numbers above are "
          "from models that never saw the fold they scored)")
    print("  weight on the standardised feature -- sign says which way it votes for 'brick'")
    for k, wi in sorted(zip(FEATURES, w), key=lambda t: -abs(t[1])):
        print(f"    {k:15s} {wi:+.3f}")
    print(f"    {'(bias)':15s} {b:+.3f}")

    if args.emit:
        np.set_printoptions(precision=6, suppress=True, linewidth=100)
        print("\n# paste into vision/brickness.py")
        print(f"MEAN = np.array({np.round(mu, 6).tolist()})")
        print(f"SCALE = np.array({np.round(sd, 6).tolist()})")
        print(f"WEIGHTS = np.array({np.round(w, 6).tolist()})")
        print(f"BIAS = {round(float(b), 6)}")
        print(f"THRESHOLD = {THRESHOLD}")


if __name__ == "__main__":
    main()
