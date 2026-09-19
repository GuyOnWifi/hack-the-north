"""Tests for the brick/not-brick discriminator.

The honest test in here is `test_holds_up_on_a_photo_it_never_saw`: it refits the model with one
whole photo held out and scores that photo. Everything else is a guard against the module quietly
breaking -- shape of the features, behaviour on degenerate input, and the flag defaulting OFF.

Splitting by crop instead of by photo would make every number in this file meaningless: hundreds
of the labelled background crops are near-duplicates of each other WITHIN a photo, so a random
split puts copies of the same blob on both sides.
"""

import importlib.util
import json
import pathlib
import sys

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from vision import brickness as B
from vision import pipeline as pipeline_mod

ROOT = pathlib.Path(__file__).resolve().parents[1]
LABELS = ROOT / "data/real/crop_labels.json"
INDEX = ROOT / "data/real/crops_index.json"
CROPS = ROOT / "data/real/crops"
PILE = ROOT / "data/test/pile01.png"
HAVE_REAL = LABELS.exists() and INDEX.exists() and CROPS.is_dir()


# ---------------------------------------------------------------- synthetic sanity

def _fake_brick(size=140, colour=(40, 40, 200)) -> np.ndarray:
    """A saturated rectangle with studs and facet lines, on the white knockout background."""
    img = np.full((size, size, 3), 255, np.uint8)
    cv2.rectangle(img, (18, 40), (size - 18, size - 40), colour, -1)
    top = tuple(min(255, c + 45) for c in colour)
    cv2.rectangle(img, (18, 40), (size - 18, 62), top, -1)       # a lit top face -> facet line
    for cx in range(34, size - 25, 26):
        cv2.circle(img, (cx, 52), 9, top, -1)
        cv2.circle(img, (cx, 52), 9, colour, 2)                  # stud rims
    return img


def _fake_blob(size=140) -> np.ndarray:
    """A soft, desaturated, structureless capsule -- the blanket blob in caricature."""
    img = np.full((size, size, 3), 255, np.uint8)
    cv2.ellipse(img, (size // 2, size // 2), (size // 2 - 12, size // 5), 0, 0, 360, (92, 96, 104), -1)
    img = cv2.GaussianBlur(img, (21, 21), 0)
    return img


def test_features_are_the_declared_ones_and_are_finite():
    f = B.features(_fake_brick())
    assert list(f) == list(B.FEATURES)
    assert all(np.isfinite(v) for v in f.values())


def test_a_drawn_brick_scores_above_a_drawn_blob():
    assert B.score(_fake_brick()) > B.score(_fake_blob())


def test_degenerate_crops_do_not_raise():
    for bad in (np.zeros((0, 0, 3), np.uint8),
                np.full((3, 3, 3), 255, np.uint8),
                np.full((60, 60, 3), 255, np.uint8)):
        s = B.score(bad)
        assert 0.0 <= s <= 1.0


def test_features_are_scale_normalised():
    """The same piece photographed twice as large must not score differently."""
    small = _fake_brick(120)
    big = cv2.resize(small, (360, 360), interpolation=cv2.INTER_CUBIC)
    assert abs(B.score(small) - B.score(big)) < 0.25


def test_the_knockout_boundary_does_not_leak_into_the_texture_features():
    """A flat patch on white must read as flat: gradients are measured inside an eroded mask."""
    flat = np.full((120, 120, 3), 255, np.uint8)
    cv2.rectangle(flat, (20, 20), (100, 100), (120, 120, 120), -1)
    f = B.features(flat)
    assert f["edge_density"] < 0.05
    assert f["lines"] < 0.05


# ---------------------------------------------------------------- the flag

def test_defaults_to_off():
    """One evening of data on one person's blanket does not get to change a default."""
    import os
    assert B.ENABLED == (os.environ.get("VISION_BRICKNESS") == "1")
    if "VISION_BRICKNESS" not in os.environ:
        assert B.ENABLED is False


@pytest.mark.skipif(not PILE.exists(), reason="run scripts/make_test_pile.py first")
def test_pipeline_only_filters_when_the_flag_is_on(monkeypatch):
    monkeypatch.setattr(B, "ENABLED", False)
    before = pipeline_mod.analyse_photo(PILE, classify=False)
    assert before, "the fixture pile should segment into something"

    monkeypatch.setattr(B, "ENABLED", True)
    monkeypatch.setattr(B, "is_brick", lambda *a, **k: False)
    assert pipeline_mod.analyse_photo(PILE, classify=False) == []

    monkeypatch.setattr(B, "is_brick", lambda *a, **k: True)
    assert len(pipeline_mod.analyse_photo(PILE, classify=False)) == len(before)


# ---------------------------------------------------------------- real labelled crops

def _real_rows():
    meta = {r["id"]: r for r in json.loads(INDEX.read_text())}
    out = []
    for rec in json.loads(LABELS.read_text())["labels"]:
        if rec["label"] == "unsure":
            continue
        cid = rec["crop_id"]
        img = cv2.imread(str(CROPS / f"{cid}.png"))
        if img is None:
            continue
        f = B.features(img, solidity=meta[cid]["solidity"])
        out.append(([f[k] for k in B.FEATURES], 1.0 if rec["label"] == "brick" else 0.0,
                    meta[cid]["photo"]))
    return out


@pytest.fixture(scope="module")
def real():
    if not HAVE_REAL:
        pytest.skip("data/real/crop_labels.json not present")
    rows = _real_rows()
    X = np.array([r[0] for r in rows])
    y = np.array([r[1] for r in rows])
    photo = np.array([r[2] for r in rows])
    return X, y, photo


def test_the_labels_on_disk_are_the_ones_that_were_measured():
    if not HAVE_REAL:
        pytest.skip("data/real/crop_labels.json not present")
    doc = json.loads(LABELS.read_text())
    assert doc["counts"] == {"brick": 730, "not_brick": 562, "unsure": 4}
    assert len(doc["labels"]) == 1296
    ids = {r["crop_id"] for r in doc["labels"]}
    assert ids == {r["id"] for r in json.loads(INDEX.read_text())}


def test_shipped_weights_still_separate_the_labelled_crops(real):
    """In-sample floor. NOT a generalisation claim -- it only catches the weights going stale."""
    X, y, _ = real
    s = 1 / (1 + np.exp(-(((X - B.MEAN) / B.SCALE) @ B.WEIGHTS + B.BIAS)))
    kept = s >= B.THRESHOLD
    brick_recall = kept[y == 1].mean()
    background_removed = (~kept[y == 0]).mean()
    assert brick_recall >= 0.98, f"in-sample brick recall regressed to {brick_recall:.3f}"
    assert background_removed >= 0.93, f"in-sample background removal regressed to {background_removed:.3f}"


def test_holds_up_on_a_photo_it_never_saw(real):
    """The only number in this file that is allowed to be quoted: whole photos held out.

    Floors are set below the measured leave-one-photo-out result (0.986 brick recall, 0.943
    background removal over all 9 folds) so that ordinary noise does not fail the suite, but a
    real regression does.
    """
    spec = importlib.util.spec_from_file_location("fit_brickness", ROOT / "scripts/fit_brickness.py")
    fitmod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fitmod)

    X, y, photo = real
    s = np.zeros(len(y))
    for p in sorted(set(photo)):
        te = photo == p
        s[te] = fitmod.apply(X[te], fitmod.fit(X[~te], y[~te]))

    kept = s >= B.THRESHOLD
    brick_recall = kept[y == 1].mean()
    background_removed = (~kept[y == 0]).mean()
    assert brick_recall >= 0.97, f"held-out brick recall {brick_recall:.3f}"
    assert background_removed >= 0.90, f"held-out background removal {background_removed:.3f}"


def test_an_unseen_artefact_family_is_the_known_weak_spot(real):
    """Documents the failure rather than hiding it: pale fabric does NOT transfer.

    If this test ever starts failing because fabric removal went UP, that is good news and the
    claim in vision/brickness.py should be re-measured and rewritten.
    """
    spec = importlib.util.spec_from_file_location("fit_brickness", ROOT / "scripts/fit_brickness.py")
    fitmod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fitmod)

    X, y, photo = real
    fam = np.array([fitmod.FAMILY[p] for p in photo])
    removed = {}
    for f in ("fabric", "pegboard", "blanket"):
        te = fam == f
        s = fitmod.apply(X[te], fitmod.fit(X[~te], y[~te]))
        neg = y[te] == 0
        removed[f] = float((s[neg] < B.THRESHOLD).mean())

    assert removed["pegboard"] >= 0.85, removed
    assert removed["blanket"] >= 0.80, removed
    assert removed["fabric"] < 0.50, (
        f"fabric removal is now {removed['fabric']:.2f}; the documented weak spot has changed "
        "and vision/brickness.py must be re-measured")
