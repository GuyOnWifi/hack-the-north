"""Tests for eval/real_report.py.

Nothing here reads a photo, touches the network or loads SAM 2 -- the report's analysis and
rendering are pure functions over an inventory dict and a cache dict, and this file pins them
against hand-written fixtures whose right answers are obvious by inspection.

The one test that matters most is `test_shape_filter_matches_the_shipped_pipeline`: the report
scores `VISION_SHAPE_FILTER=1` from cached geometry instead of segmenting a second time, and that
shortcut is only honest while it agrees with `vision.segment.suppress_parts`.
"""

import json
import pathlib
import sys

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from eval import real_report as rr
from vision import segment as seg_mod


def _item(part, color, qty, *, pscore=0.7, cscore=0.3, name=None):
    return {
        "id": f"inv_{part}_{color}", "part": part, "name": name or f"part {part}",
        "color": color, "color_name": str(color), "qty": qty, "source": "photo",
        "confidence": {"part": pscore, "color": cscore},
        "status": "needs_review", "placeable": True,
        "color_mode": "exact" if cscore >= 0.60 else "similar",
        "evidence": {"photo": "lego.jpg", "bbox": [0, 0, 4, 4], "bboxes": [[0, 0, 4, 4]],
                     "alternatives": []},
    }


# A bin with the exact asymmetry the report exists to show: six rows, but only three parts once
# colour is ignored, and the 2x4s only reach a group of four when pooled.
LONGTAIL = {
    "session_id": "ses_test",
    "items": [
        _item("3001", 4, 2, pscore=0.9, cscore=0.8),
        _item("3001", 1, 1),
        _item("3001", 15, 2),
        _item("3003", 4, 1),
        _item("3003", 0, 1),
        _item("3004", 2, 1, pscore=0.4),
    ],
    "totals": {"pieces": 12, "distinct": 6, "unknown": 4, "unplaceable": 0},
}


# ---------------------------------------------------------------- bin shape

def test_bin_shape_separates_colour_from_part():
    s = rr.bin_shape(LONGTAIL)
    assert s["combos"] == 6                    # part+colour rows
    assert s["parts"] == 3                     # 3001, 3003, 3004
    assert s["combos_qty2"] == 2               # the two qty-2 rows of 3001
    assert s["parts_qty2"] == 2                # 3001 (5) and 3003 (2)
    assert s["largest_combo"] == 2
    assert s["largest_part"] == 5


def test_bin_shape_counts_pieces_usable_in_groups_of_four():
    """The headline metric: no row reaches four, but one PART does once colour is pooled."""
    s = rr.bin_shape(LONGTAIL)
    assert s["pieces_in_combo4"] == 0
    assert s["pieces_in_part4"] == 5           # the five 2x4s across three colours


def test_bin_shape_counts_unknowns_in_detections_but_not_in_rows():
    s = rr.bin_shape(LONGTAIL)
    assert s["identified"] == 8
    assert s["unknown"] == 4
    assert s["detections"] == 12
    assert s["unknown_rate"] == pytest.approx(4 / 12)


def test_bin_shape_top_is_pooled_and_ordered():
    top = rr.bin_shape(LONGTAIL)["top"]
    assert [p for p, _n, _nm in top] == ["3001", "3003", "3004"]
    assert top[0][1] == 5


def test_bin_shape_survives_an_empty_inventory():
    """An empty bin must render a report, not raise -- the pipeline can legitimately find nothing."""
    s = rr.bin_shape({"items": [], "totals": {"pieces": 0, "unknown": 0}})
    assert s["combos"] == 0 and s["parts"] == 0 and s["unknown_rate"] == 0.0


def test_bin_shape_matches_the_real_inventory_if_it_is_present():
    """Guards the number the write-up leads with against a silent pipeline change."""
    p = pathlib.Path(rr.ROOT) / "data" / "real" / "inventory.json"
    if not p.exists():
        pytest.skip("data/real/inventory.json is not present (photos are gitignored)")
    s = rr.bin_shape(json.loads(p.read_text()))
    assert s["combos"] > s["parts"], "colour pooling must reduce the number of distinct entries"
    assert s["pieces_in_part4"] >= s["pieces_in_combo4"]


# ---------------------------------------------------------------- confidence

def test_confidence_buckets_are_piece_weighted():
    d = rr.confidence_distribution(LONGTAIL)
    assert d["identified"] == 8
    assert d["part"]["confirmed"] == 2          # one row, qty 2, score 0.90
    assert d["part"]["needs_review"] == 5       # 1 + 2 + 1 + 1
    assert d["part"]["unknown"] == 1            # the 0.40 row


def test_confidence_scores_colour_on_the_colour_threshold_not_the_part_bands():
    """Colour has one threshold (0.60), not three bands. Reporting it otherwise invents a band."""
    d = rr.confidence_distribution(LONGTAIL)
    assert d["colour_exact"] == 2
    assert d["colour_similar"] == 6
    assert d["colour_exact_rate"] == pytest.approx(2 / 8)


def test_confidence_bucket_edges_match_the_pipeline_policy():
    """If the pipeline moves a threshold, this report must not keep quoting the old one."""
    from vision import pipeline as pipe
    edges = {lo for lo, _hi, _n, _lbl in rr.BUCKETS}
    assert pipe.CONFIRM_AT in edges and pipe.REVIEW_AT in edges


def test_confidence_of_an_empty_inventory_does_not_divide_by_zero():
    d = rr.confidence_distribution({"items": [], "totals": {}})
    assert d["colour_exact_rate"] == 0.0


# ---------------------------------------------------------------- the shape filter

def _piece(area, w, h, solidity):
    """A Piece with a mask whose area is `area`, so suppress_parts and our shim agree."""
    mask = np.zeros((h + 2, w + 2), np.uint8)
    return seg_mod.Piece(0, (1, 1, w, h), mask, area, solidity)


def test_shape_filter_matches_the_shipped_pipeline(monkeypatch):
    """Scoring the filter from the cache must equal running the pipeline with it turned on.

    This is the assumption the report's `+filter` column rests on: `suppress_parts` applies
    `plausible_brick` strictly AFTER containment suppression, so the survivors are all the filter
    ever sees. If someone moves the filter earlier, this test fails and the report's claim stops
    being true -- which is exactly when we want to hear about it.
    """
    # Boxes far apart, so containment suppression keeps every one of them and the only thing
    # separating the two paths is the filter itself.
    raw = [_piece(3000, 70, 60, 0.90),                  # plausible brick
           _piece(2800, 65, 60, 0.90),                  # plausible brick
           _piece(30, 8, 6, 0.90),                      # far too small -> a stud, not a brick
           _piece(3200, 300, 20, 0.90),                 # aspect 15:1 -> a shadow streak
           _piece(2900, 68, 60, 0.35)]                  # ragged -> not a brick
    for i, p in enumerate(raw):
        p.bbox = (i * 500, 0, p.bbox[2], p.bbox[3])

    monkeypatch.setattr(seg_mod, "SHAPE_FILTER", True)
    kept_by_pipeline = seg_mod.suppress_parts(list(raw))

    monkeypatch.setattr(seg_mod, "SHAPE_FILTER", False)
    unfiltered = seg_mod.suppress_parts(list(raw))
    cached = [{"bbox": list(p.bbox), "area": p.area, "solidity": p.solidity} for p in unfiltered]
    kept_by_report = rr.shape_filter_survivors(cached)

    assert len(kept_by_report) == len(kept_by_pipeline)
    assert ([tuple(p["bbox"]) for p in kept_by_report]
            == [p.bbox for p in kept_by_pipeline])
    assert 0 < len(kept_by_report) < len(cached), "the fixture must exercise both outcomes"


def test_shape_filter_on_an_empty_list():
    assert rr.shape_filter_survivors([]) == []


# ---------------------------------------------------------------- cache

CACHE = {
    "version": rr.CACHE_VERSION,
    "photos": {
        "a.jpg": {
            "sam2": {"photo": "a.jpg", "backend": "sam2", "pixels": [4000, 3000],
                     "working": [1600, 1200], "classify_hits": 3, "classify_online": False,
                     "pieces": [{"bbox": [0, 0, 60, 40], "area": 2000, "solidity": 0.9},
                                {"bbox": [200, 0, 60, 40], "area": 2000, "solidity": 0.9},
                                {"bbox": [400, 0, 4, 4], "area": 8, "solidity": 0.9}],
                     "seconds": {"read": 0.1, "segment": 6.0, "crop": 0.2,
                                 "colour": 0.5, "classify": 0.01}},
            "opencv": {"photo": "a.jpg", "backend": "opencv", "pixels": [4000, 3000],
                       "working": [1600, 1200], "classify_hits": 1, "classify_online": False,
                       "pieces": [{"bbox": [0, 0, 60, 40], "area": 2000, "solidity": 0.9}],
                       "seconds": {"read": 0.1, "segment": 0.2, "crop": 0.05,
                                   "colour": 0.1, "classify": 0.0}},
        }
    },
}


def test_cache_round_trips(tmp_path):
    p = tmp_path / "cache.json"
    p.write_text(json.dumps(CACHE))
    assert rr.load_cache(p) == CACHE


def test_a_stale_cache_schema_is_discarded_not_rendered(tmp_path):
    """Rendering v1 numbers under v2 headings would be a quiet lie. Re-measure instead."""
    p = tmp_path / "cache.json"
    p.write_text(json.dumps({"version": 0, "photos": {"a.jpg": {}}}))
    assert rr.load_cache(p)["photos"] == {}


def test_a_missing_cache_is_an_empty_one(tmp_path):
    assert rr.load_cache(tmp_path / "nope.json")["photos"] == {}


# ---------------------------------------------------------------- rendering

def test_render_states_the_missing_ground_truth_up_front():
    md = rr.render(CACHE, [("inv.json", "test", LONGTAIL)], [])
    head = md.split("## The shape of the bin")[0]
    assert "no ground truth" in head.lower()
    assert "recall" in head.lower() and "precision" in head.lower()


def test_render_never_reports_recall_on_the_unlabelled_photos():
    """The one number this report must not invent."""
    md = rr.render(CACHE, [("inv.json", "test", LONGTAIL)], [])
    before_labelled = md.split("## Separately")[0]
    for line in before_labelled.splitlines():
        low = line.lower()
        if "recall" in low or "precision" in low:
            assert any(mark in low for mark in
                       ("not computable", "no ground truth", "labelled set", "labels",
                        "unmeasured", "different, published dataset")), line


def test_render_has_every_section_the_write_up_promises():
    md = rr.render(CACHE, [("inv.json", "test", LONGTAIL)], [])
    for heading in ("## What works", "## What these numbers are not", "## The shape of the bin",
                    "## Detections per photo", "## Classifier confidence",
                    "## Runtime per stage", "## Separately", "## Limits"):
        assert heading in md, heading


def test_render_flags_counts_that_hit_the_piece_cap():
    capped = json.loads(json.dumps(CACHE))
    one = capped["photos"]["a.jpg"]["sam2"]["pieces"][0]
    one_list = [dict(one, bbox=[i * 100, 0, 60, 40]) for i in range(seg_mod.MAX_PIECES)]
    capped["photos"]["a.jpg"]["sam2"]["pieces"] = one_list
    md = rr.render(capped, [], [])
    assert "capped" in md and str(seg_mod.MAX_PIECES) in md


def test_render_works_with_no_cache_and_no_inventory():
    """Someone will run this before measuring anything. It must produce a file, not a traceback."""
    md = rr.render({"version": rr.CACHE_VERSION, "photos": {}}, [], [])
    assert "--measure" in md and md.startswith("# ")


def test_render_includes_the_labelled_numbers_from_results_tsv():
    labelled = [{"tag": "filter-on", "images": "10", "recall": "0.816", "precision": "0.985"},
                {"tag": "ignored-tag", "images": "1", "recall": "1.0", "precision": "1.0"}]
    md = rr.render(CACHE, [], labelled)
    assert "0.816" in md
    assert "ignored-tag" not in md, "only the runs we stand behind belong in the write-up"


def test_labelled_rows_parses_the_real_tsv():
    rows = rr.labelled_rows(rr.RESULTS_TSV)
    if not rows:
        pytest.skip("eval/results.tsv is empty")
    assert {"tag", "images", "recall", "precision"} <= set(rows[0])


def test_labelled_rows_on_a_missing_file(tmp_path):
    assert rr.labelled_rows(tmp_path / "nope.tsv") == []


# ---------------------------------------------------------------- cli

def test_main_regenerates_from_cache_without_photos_or_network(tmp_path):
    """The whole point of the cache: a report with no camera, no GPU and no wifi."""
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps(CACHE))
    out = tmp_path / "RESULTS.md"
    assert rr.main(["--cache", str(cache), "--out", str(out)]) == 0
    assert out.read_text().startswith("# Bricolage")


def test_the_report_is_deterministic(tmp_path):
    """Same cache + same inventory = byte-identical markdown (invariant 6)."""
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps(CACHE))
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    rr.main(["--cache", str(cache), "--out", str(a)])
    rr.main(["--cache", str(cache), "--out", str(b)])
    assert a.read_bytes() == b.read_bytes()


def test_the_heavy_imports_stay_inside_measure_photo():
    """Importing the report must not cost a torch import -- the CLI renders from cache by default."""
    src = pathlib.Path(rr.__file__).read_text()
    top = src.split("def measure_photo")[0]
    for heavy in ("import cv2", "import torch", "from vision import"):
        assert heavy not in top, f"{heavy} belongs inside measure_photo, not at module scope"
    assert not hasattr(rr, "cv2")
