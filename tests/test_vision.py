"""CV lane tests. Nothing here needs the network except the tests marked `network`."""

import pathlib
import sys

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from vision import color as color_mod
from vision.pipeline import to_inventory
from vision.resolve import resolve

ROOT = pathlib.Path(__file__).resolve().parents[1]
PILE = ROOT / "data" / "test" / "pile01.png"


# ---------------------------------------------------------------- colour

def test_palette_is_restricted_to_colours_people_own():
    common, full = color_mod.palette(), color_mod.palette(False)
    assert 30 < len(common) < 60, "the common palette should be ~40 colours"
    assert len(full) > 250, "the full LDraw palette should be the whole LDConfig"


@pytest.mark.parametrize("rgb,expect", [
    ((200, 20, 20), 4),      # red
    ((245, 245, 240), 15),   # white
    ((28, 33, 40), 0),       # black
    ((0, 133, 43), 2),      # green -- LDraw #00852B, read as HEX not decimal
])
def test_obvious_colours_resolve_correctly(rgb, expect):
    code, _name, _conf = color_mod.nearest(rgb)
    assert code == expect


def test_ambiguous_colour_reports_low_confidence():
    """Two palette entries equally close must surface as low confidence, not a confident guess."""
    _c1, _n1, clear = color_mod.nearest((200, 20, 20))
    _c2, _n2, murky = color_mod.nearest((220, 180, 60))   # sits between Yellow and Light Yellow
    assert clear > murky
    assert murky < 0.35


def test_colour_of_ignores_specular_highlights():
    """A red brick with a blown-out white highlight is still red."""
    img = np.zeros((40, 40, 3), np.uint8)
    img[:, :] = (20, 20, 200)              # BGR red
    img[4:10, 4:10] = (255, 255, 255)      # highlight
    mask = np.full((40, 40), 255, np.uint8)
    code, _name, _conf = color_mod.colour_of(img, mask)
    assert code == 4


# ---------------------------------------------------------------- id resolution

@pytest.mark.parametrize("brickognize_id,ldraw_id", [
    ("3001", "3001"),      # already an LDraw id
    ("3023", "3023b"),     # THE trap: BrickLink drops the variant suffix
    ("3040", "3040b"),
    ("3068", "3068b"),
    ("3070", "3070b"),
    ("3004", "3004"),
])
def test_bricklink_ids_resolve_to_ldraw_ids(brickognize_id, ldraw_id):
    part, _how = resolve(brickognize_id)
    assert part == ldraw_id


def test_resolver_prefers_the_plain_mould_over_a_special_variant():
    """3023a is 'plate 1x2 with flat pin'; 3023b is the plain plate everybody owns."""
    from core import meta
    part, _ = resolve("3023")
    assert "with" not in meta.get(part).name


def test_unknown_part_resolves_to_none_rather_than_guessing():
    part, how = resolve("99999")
    assert part is None and how == "no-ldraw-equivalent"


# ---------------------------------------------------------------- aggregation

def _row(part, color, score, status="confirmed"):
    return {"photo": "p.jpg", "piece": 0, "bbox": [0, 0, 10, 10], "part": part,
            "raw_part": part, "resolved_by": "exact", "name": part, "color": color,
            "color_name": "Red", "confidence": {"part": score, "color": 0.9},
            "status": status, "alternatives": []}


def test_identical_detections_merge_into_a_quantity():
    inv = to_inventory([_row("3001", 4, 0.9), _row("3001", 4, 0.9), _row("3001", 15, 0.9)])
    by = {(i["part"], i["color"]): i["qty"] for i in inv["items"]}
    assert by[("3001", 4)] == 2 and by[("3001", 15)] == 1


def test_unknown_rows_are_counted_but_not_placeable():
    inv = to_inventory([_row("3001", 4, 0.9), _row(None, 4, 0.2, "unknown")])
    assert inv["totals"]["unknown"] == 1
    assert inv["totals"]["pieces"] == 2, "an unidentified brick is still a brick you own"
    assert len(inv["items"]) == 1


def test_a_low_confidence_row_is_flagged_for_review():
    inv = to_inventory([_row("3001", 4, 0.61, "needs_review")])
    assert inv["items"][0]["status"] == "needs_review"


def test_inventory_matches_contract_1():
    inv = to_inventory([_row("3001", 4, 0.9)])
    assert set(inv) == {"session_id", "items", "totals", "sufficient", "guidance"}
    item = inv["items"][0]
    for field in ("id", "part", "color", "qty", "source", "confidence", "status", "color_mode"):
        assert field in item, f"Contract 1 requires {field}"


def test_every_instance_location_is_kept():
    """qty 3 must carry 3 locations -- "show me where my red 2x4s are" depends on it."""
    inv = to_inventory([_row("3001", 4, 0.9), _row("3001", 4, 0.9), _row("3001", 4, 0.9)])
    assert len(inv["items"][0]["evidence"]["bboxes"]) == 3


def test_a_thin_scan_refuses_instead_of_building_something_embarrassing():
    inv = to_inventory([_row("3001", 4, 0.9)])
    assert inv["sufficient"] is False and "single layer" in inv["guidance"]


# ---------------------------------------------------------------- segmentation

@pytest.mark.skipif(not PILE.exists(), reason="run scripts/make_test_pile.py first")
def test_segmenter_finds_most_bricks_in_the_synthetic_pile():
    import cv2
    from vision.segment import segment
    img = cv2.imread(str(PILE))
    work, pieces = segment(img)
    assert len(pieces) >= 10, f"only found {len(pieces)} pieces"
    for p in pieces:
        x, y, w, h = p.bbox
        assert w > 0 and h > 0
        assert p.mask.shape[:2] == work.shape[:2]


@pytest.mark.skipif(not PILE.exists(), reason="run scripts/make_test_pile.py first")
def test_crop_on_white_knocks_out_the_background():
    import cv2
    from vision.segment import segment
    img = cv2.imread(str(PILE))
    work, pieces = segment(img)
    crop = pieces[0].crop_on_white(work)
    corners = [crop[0, 0], crop[0, -1], crop[-1, 0], crop[-1, -1]]
    assert all((c == 255).all() for c in corners), "corners should be knocked out to white"


# ---------------------------------------------------------------- COCO import

def test_coco_import_maps_category_names_to_ldraw_ids(tmp_path):
    """CVAT/Roboflow exports name categories freely; we must find the part id inside."""
    import json
    from eval.import_coco import category_to_part

    assert category_to_part("3001 Brick 2 x 4", True)[0] == "3001"
    assert category_to_part("3023 - Plate 1 x 2", True)[0] == "3023b"   # the BrickLink trap again
    assert category_to_part("brick", True)[0] is None                   # generic class
    assert category_to_part("lego", True)[0] is None


def test_class_agnostic_truth_does_not_fake_a_perfect_classification_score():
    """Comparing None to None would report top-1 = 1.00, the most misleading number possible."""
    from eval.pile_eval import score_one
    import json
    import pathlib

    pile = pathlib.Path(__file__).resolve().parents[1] / "data" / "test" / "pile01.png"
    if not pile.exists():
        import pytest as _p
        _p.skip("run scripts/make_test_pile.py first")
    truth = {"image": pile.name, "pieces": [{"part": None, "bbox": [100, 100, 200, 200]}]}
    r = score_one(pile, truth, 1600 / 1400)
    assert r["classifiable"] == 0
    assert r["top1"] != r["top1"], "top-1 must be NaN when nothing is classifiable"


# ---------------------------------------------------------------- confirm loop

def _det(i, part, score, w=80, h=40, alts=()):
    return {"photo": "p.jpg", "piece": i, "bbox": [i * 10, 0, w, h], "part": part,
            "name": part or "?", "color": 4, "color_name": "Red",
            "confidence": {"part": score, "color": 0.9},
            "status": "confirmed" if score >= 0.85 else "needs_review",
            "alternatives": [{"part": p, "name": p, "score": s} for p, s in alts]}


def test_confirming_one_row_propagates_to_similar_rows():
    """The demo moment: confirm one brick, watch several amber rows go green."""
    from vision.confirm import ConfirmState
    rows = [
        _det(0, "3001", 0.55, alts=[("3003", 0.44)]),   # ambiguous, same size as the anchor
        _det(1, "3001", 0.58, alts=[("3003", 0.45)]),   # ambiguous, same size
        _det(2, "3024", 0.92, w=20, h=20),              # unrelated, already confident
    ]
    st = ConfirmState(rows)
    changes = st.confirm(0, part="3003")                # the human says row 0 is really 3003

    assert rows[0]["part"] == "3003" and rows[0]["status"] == "confirmed"
    assert rows[1]["part"] == "3003", "a same-size ambiguous row should follow the correction"
    assert any(c.row_index == 1 for c in changes)
    assert rows[2]["part"] == "3024", "an unrelated confident row must not be touched"


def test_propagation_never_invents_a_part_the_classifier_did_not_propose():
    from vision.confirm import ConfirmState
    rows = [_det(0, "3001", 0.9), _det(1, "3010", 0.55, alts=[("3622", 0.4)])]
    st = ConfirmState(rows)
    st.confirm(0, part="3005")                          # 3005 appears nowhere in row 1
    assert rows[1]["part"] in {"3010", "3622"}


def test_propagation_does_not_overwrite_a_human_confirmation():
    from vision.confirm import ConfirmState
    rows = [_det(0, "3001", 0.55, alts=[("3003", 0.5)]),
            _det(1, "3001", 0.55, alts=[("3003", 0.5)])]
    st = ConfirmState(rows)
    st.confirm(1, part="3001")                          # human pins row 1
    st.confirm(0, part="3003")
    assert rows[1]["part"] == "3001", "a confirmed row is frozen"


def test_every_propagated_change_records_a_reason():
    from vision.confirm import ConfirmState
    rows = [_det(0, "3001", 0.55, alts=[("3003", 0.44)]),
            _det(1, "3001", 0.58, alts=[("3003", 0.45)])]
    st = ConfirmState(rows)
    changes = st.confirm(0, part="3003")
    assert changes and all(c.reason for c in changes)
    assert rows[1].get("propagated"), "the UI must be able to explain the change"


def test_differently_sized_rows_are_not_dragged_along():
    from vision.confirm import ConfirmState
    rows = [_det(0, "3001", 0.55, w=80, h=40, alts=[("3003", 0.44)]),
            _det(1, "3001", 0.55, w=20, h=20, alts=[("3003", 0.44)])]
    st = ConfirmState(rows)
    st.confirm(0, part="3003")
    assert rows[1]["part"] == "3001", "size mismatch means the ownership prior alone is too weak"
