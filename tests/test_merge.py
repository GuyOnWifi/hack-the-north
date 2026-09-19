"""Multi-photo inventory merge. No network, no photos needed.

The one failure this file exists to prevent: silently doubling somebody's brick count because two
photos of the SAME handful were added together. Every test here is either that failure or the
evidence/consistency guarantees that make the merged inventory usable downstream.
"""

import copy
import itertools
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from vision.merge import (
    SAME_PILE_AT,
    box_overlap,
    cosine,
    detect_duplicates,
    histogram_similarity,
    main,
    merge_inventories,
    part_histogram,
)
from vision.pipeline import to_inventory

ROOT = pathlib.Path(__file__).resolve().parents[1]
# The 9-photo merge is being produced while this was written; fall back to the single-photo run,
# then to the committed fixture. A test that needs a file that may not exist is a flaky test.
REAL_CANDIDATES = [ROOT / "data" / "real" / "inventory_all.json",
                   ROOT / "data" / "real" / "inventory.json",
                   ROOT / "fixtures" / "inventory.json"]


def _real() -> dict:
    for p in REAL_CANDIDATES:
        if p.exists():
            return json.loads(p.read_text())
    pytest.skip("no inventory json available")


_BOX = itertools.count()


def _row(part, color, score, status="confirmed", photo="p.jpg", bbox=None):
    # Distinct boxes by default: two different detections never share pixel coordinates, and the
    # duplicate detector reads exactly that. A shared default would fake a same-photo match.
    if bbox is None:
        bbox = (next(_BOX) * 7, 0, 10, 10)
    return {"photo": photo, "piece": 0, "bbox": list(bbox), "part": part, "raw_part": part,
            "resolved_by": "exact", "name": part, "color": color, "color_name": "Red",
            "confidence": {"part": score, "color": 0.9}, "status": status, "alternatives": []}


def _inv(rows, session="ses_a"):
    return to_inventory(rows, session)


def _consistent(inv):
    """Contract 1's arithmetic: every piece is either a counted element or an unknown."""
    t = inv["totals"]
    assert t["pieces"] == sum(i["qty"] for i in inv["items"]) + t["unknown"]
    assert t["distinct"] == len(inv["items"])


# ---------------------------------------------------------------- histogram helper


def test_cosine_is_one_for_identical_mixes_and_zero_for_disjoint_ones():
    assert cosine({"3001": 3, "3003": 1}, {"3001": 3, "3003": 1}) == pytest.approx(1.0)
    assert cosine({"3001": 3}, {"3003": 3}) == pytest.approx(0.0)
    assert cosine({}, {"3001": 1}) == 0.0


def test_cosine_ignores_scale_so_half_a_pile_matches_the_whole():
    """Half the bricks photographed is the same MIX, which is what the detector is asking about."""
    assert cosine({"3001": 6, "3003": 2}, {"3001": 3, "3003": 1}) == pytest.approx(1.0)


def test_histogram_pools_colour_out_by_default():
    inv = _inv([_row("3001", 4, 0.9), _row("3001", 15, 0.9)])
    assert part_histogram(inv) == {"3001": 2}
    assert part_histogram(inv, by_colour=True) == {("3001", 4): 1, ("3001", 15): 1}


def test_a_colour_misread_still_looks_like_the_same_pile():
    """Colour is our weakest stage, so the detector must not be fooled by red-vs-dark-red."""
    a = _inv([_row("3001", 4, 0.9), _row("3001", 4, 0.9), _row("3010", 1, 0.9)])
    b = _inv([_row("3001", 320, 0.9), _row("3001", 4, 0.9), _row("3010", 1, 0.9)])
    assert histogram_similarity(a, b) == pytest.approx(1.0)
    assert histogram_similarity(a, b, by_colour=True) < 0.9


# ---------------------------------------------------------------- the core distinction


def test_same_pile_does_not_double_a_self_merge():
    inv = _real()
    merged = merge_inventories([copy.deepcopy(inv), copy.deepcopy(inv)], "same_pile",
                               labels=["shot1", "shot2"])
    before = {(i["part"], i["color"]): i["qty"] for i in inv["items"]}
    after = {(i["part"], i["color"]): i["qty"] for i in merged["items"]}
    assert after == before, "re-shooting the same bricks must not create bricks"
    assert merged["totals"]["pieces"] == inv["totals"]["pieces"]


def test_distinct_piles_does_double_a_self_merge():
    inv = _real()
    merged = merge_inventories([copy.deepcopy(inv), copy.deepcopy(inv)], "distinct_piles",
                               labels=["handful1", "handful2"])
    for item in merged["items"]:
        original = next(i for i in inv["items"]
                        if i["part"] == item["part"] and i["color"] == item["color"])
        assert item["qty"] == original["qty"] * 2
    assert merged["totals"]["pieces"] == inv["totals"]["pieces"] * 2


def test_the_duplicate_detector_flags_a_self_merge():
    inv = _real()
    overlaps = detect_duplicates([copy.deepcopy(inv), copy.deepcopy(inv)], ["shot1", "shot2"])
    assert len(overlaps) == 1
    assert overlaps[0].similarity == pytest.approx(1.0)
    assert "shot1" in overlaps[0].human and "shot2" in overlaps[0].human


def test_identical_boxes_prove_the_same_photograph_rather_than_merely_suspecting_it():
    """Segmentation is deterministic, so pixel-identical boxes are evidence, not inference."""
    inv = _real()
    overlaps = detect_duplicates([copy.deepcopy(inv), copy.deepcopy(inv)], ["a", "b"])
    assert overlaps[0].kind == "same_photo"
    assert overlaps[0].shared_boxes == pytest.approx(1.0)
    assert "share a photograph" in overlaps[0].human


def test_two_photos_of_different_bricks_share_no_boxes():
    a = _inv([_row("3001", 4, 0.9, bbox=(10, 10, 40, 20))])
    b = _inv([_row("3001", 4, 0.9, bbox=(11, 10, 40, 20))])
    assert box_overlap(a, b) == 0.0
    assert detect_duplicates([a, b], ["a", "b"])[0].kind == "same_mix"


def test_a_matching_mix_is_only_ever_a_suspicion():
    """MEASURED on the real bin: two handfuls scooped from ONE bin score 0.90-0.95, and two
    re-shoots of one pile score 0.98+. The clusters nearly touch, so counts alone cannot decide
    it -- the detector must say `same_mix` and let the user answer."""
    dominant = {"3001": 80, "3003": 60, "3004": 54}
    a = _inv([_row(p, 4, 0.9, bbox=(i, 0, 5, 5))
              for i, (p, n) in enumerate(dominant.items()) for _ in range(n // 2)])
    b = _inv([_row(p, 4, 0.9, bbox=(500 + i, 0, 5, 5))
              for i, (p, n) in enumerate(dominant.items()) for _ in range(n - n // 2)])
    overlap = detect_duplicates([a, b], ["scoopA", "scoopB"])[0]
    assert overlap.kind == "same_mix", "no shared boxes, so nothing is proven"
    assert "may be the same bricks" in overlap.human


def test_adding_duplicates_is_loud_about_it():
    """Doubling is allowed when asked for. Doing it SILENTLY is the failure."""
    inv = _real()
    merged = merge_inventories([copy.deepcopy(inv), copy.deepcopy(inv)], "distinct_piles",
                               labels=["a", "b"])
    assert merged["merge"]["likely_same_pile"] is True
    assert merged["merge"]["warning"], "a suspected double-count must be stated in the result"
    assert "same_pile" in merged["merge"]["warning"]


def test_different_handfuls_merge_quietly():
    a = _inv([_row("3001", 4, 0.9), _row("3001", 4, 0.9)])
    b = _inv([_row("3010", 1, 0.9), _row("3005", 14, 0.9)])
    merged = merge_inventories([a, b], "distinct_piles", labels=["a", "b"])
    assert merged["merge"]["likely_same_pile"] is False
    assert merged["merge"]["warning"] is None
    assert merged["totals"]["pieces"] == 4
    _consistent(merged)


def test_auto_mode_picks_the_safe_arithmetic_on_its_own():
    inv = _real()
    same = merge_inventories([copy.deepcopy(inv), copy.deepcopy(inv)], "auto", labels=["a", "b"])
    assert same["merge"]["mode"] == "same_pile"
    assert same["totals"]["pieces"] == inv["totals"]["pieces"]

    a = _inv([_row("3001", 4, 0.9)])
    b = _inv([_row("3010", 1, 0.9)])
    apart = merge_inventories([a, b], "auto", labels=["a", "b"])
    assert apart["merge"]["mode"] == "distinct_piles"
    assert apart["totals"]["pieces"] == 2


def test_explicit_modes_are_obeyed_even_when_the_detector_disagrees():
    """Guessing against an instruction produces bugs nobody can reproduce. Warn, do not override."""
    a = _inv([_row("3001", 4, 0.9), _row("3001", 4, 0.9)])
    b = _inv([_row("3010", 1, 0.9)])
    merged = merge_inventories([a, b], "same_pile", labels=["a", "b"])
    assert merged["merge"]["mode"] == "same_pile"
    assert "distinct_piles" in merged["merge"]["warning"]


def test_same_pile_pools_colour_so_a_misread_hue_cannot_invent_a_brick():
    """One photo reads three 2x4s as red, the re-shoot reads one of them as dark red.

    Max-per-(part, colour) alone would report four 2x4s. Nobody gained a brick between shots.
    """
    a = _inv([_row("3001", 4, 0.9), _row("3001", 4, 0.9), _row("3001", 4, 0.9)])
    b = _inv([_row("3001", 4, 0.9), _row("3001", 4, 0.9), _row("3001", 320, 0.9)])
    merged = merge_inventories([a, b], "same_pile", labels=["a", "b"])
    assert sum(i["qty"] for i in merged["items"]) == 3
    assert "3001" in merged["merge"]["capped"]
    _consistent(merged)


# ---------------------------------------------------------------- confidence and evidence


def test_a_confident_sighting_beats_an_ambiguous_one():
    """Seen clearly once and badly once is a part we know, not a part we are unsure about."""
    murky = _inv([_row("3001", 4, 0.55, "needs_review")])
    clear = _inv([_row("3001", 4, 0.97, "confirmed")])
    merged = merge_inventories([murky, clear], "same_pile", labels=["bad_angle", "good_angle"])
    item = merged["items"][0]
    assert item["confidence"]["part"] == pytest.approx(0.97)
    assert item["status"] == "confirmed"


def test_a_human_confirmation_is_never_demoted():
    typed = _inv([_row("3001", 4, 0.40, "confirmed")])
    typed["items"][0]["status"] = "confirmed"          # the user fixed this row by hand
    guess = _inv([_row("3001", 4, 0.40, "needs_review")])
    merged = merge_inventories([typed, guess], "same_pile", labels=["a", "b"])
    assert merged["items"][0]["status"] == "confirmed"


def test_every_photo_that_saw_a_brick_is_named_in_the_evidence():
    """"Where are my six red 2x4s" has to work across the whole shoot, not one frame."""
    a = _inv([_row("3001", 4, 0.9, photo="lego1.jpg", bbox=(10, 10, 40, 20))])
    b = _inv([_row("3001", 4, 0.9, photo="lego2.jpg", bbox=(90, 30, 40, 20))])
    merged = merge_inventories([a, b], "distinct_piles", labels=["lego1", "lego2"])
    ev = merged["items"][0]["evidence"]
    assert {s["photo"] for s in ev["sightings"]} == {"lego1.jpg", "lego2.jpg"}
    assert ev["photos"] == ["lego1.jpg", "lego2.jpg"]
    assert len(ev["bboxes"]) == 2, "Contract 1's flat bbox list survives the merge"
    assert [s["bbox"] for s in ev["sightings"]] == ev["bboxes"]


def test_a_self_merge_does_not_invent_duplicate_locations():
    """The same box in the same frame is one brick, however many times it is merged."""
    inv = _real()
    merged = merge_inventories([copy.deepcopy(inv), copy.deepcopy(inv)], "same_pile",
                               labels=["a", "b"])
    for item in merged["items"]:
        assert len(item["evidence"]["bboxes"]) == item["qty"]


def test_alternatives_from_several_photos_are_pooled_and_capped():
    a = _inv([_row("3001", 4, 0.6, "needs_review")])
    a["items"][0]["evidence"]["alternatives"] = [{"part": "3003", "score": 0.4}]
    b = _inv([_row("3001", 4, 0.6, "needs_review")])
    b["items"][0]["evidence"]["alternatives"] = [{"part": "3003", "score": 0.5},
                                                 {"part": "3010", "score": 0.3},
                                                 {"part": "3005", "score": 0.2},
                                                 {"part": "3020", "score": 0.1}]
    merged = merge_inventories([a, b], "same_pile", labels=["a", "b"])
    alts = merged["items"][0]["evidence"]["alternatives"]
    assert len(alts) == 3
    assert alts[0] == {"part": "3003", "score": 0.5}, "best score per part wins"


# ---------------------------------------------------------------- totals and shape


@pytest.mark.parametrize("mode", ["distinct_piles", "same_pile", "auto"])
def test_totals_stay_internally_consistent(mode):
    inv = _real()
    merged = merge_inventories([copy.deepcopy(inv), copy.deepcopy(inv)], mode, labels=["a", "b"])
    _consistent(merged)


def test_unknown_pieces_follow_the_same_arithmetic_as_known_ones():
    rows = [_row("3001", 4, 0.9), _row(None, 4, 0.2, "unknown")]
    a, b = _inv(rows), _inv(copy.deepcopy(rows))
    assert merge_inventories([a, b], "distinct_piles")["totals"]["unknown"] == 2
    assert merge_inventories([a, b], "same_pile")["totals"]["unknown"] == 1


def test_merged_inventory_is_still_contract_1():
    merged = merge_inventories([_real(), _real()], "same_pile", labels=["a", "b"])
    assert {"session_id", "items", "totals", "sufficient", "guidance"} <= set(merged)
    item = merged["items"][0]
    for field in ("id", "part", "color", "qty", "source", "confidence", "status", "color_mode"):
        assert field in item, f"Contract 1 requires {field}"
    ids = [i["id"] for i in merged["items"]]
    assert ids == sorted(ids) and len(set(ids)) == len(ids), "ids are renumbered and unique"


def test_a_hand_written_inventory_without_evidence_does_not_crash():
    """fixtures/inventory.json has no bboxes and no `placeable`. Typed inventories have neither."""
    thin = {"session_id": "ses_typed",
            "items": [{"id": "inv_001", "part": "3001", "color": 4, "qty": 8, "source": "typed",
                       "confidence": {"part": 0.94, "color": 0.88}, "status": "confirmed",
                       "evidence": {"crop_url": "x", "alternatives": []}}],
            "totals": {"pieces": 8, "distinct": 1, "unknown": 0}}
    merged = merge_inventories([thin, copy.deepcopy(thin)], "same_pile", labels=["a", "b"])
    assert merged["items"][0]["qty"] == 8
    assert merged["items"][0]["source"] == "typed"
    assert merged["items"][0]["evidence"]["bboxes"] == []
    _consistent(merged)


def test_merging_nothing_is_an_empty_inventory_not_a_crash():
    merged = merge_inventories([], "distinct_piles")
    assert merged["items"] == [] and merged["totals"]["pieces"] == 0
    assert merged["sufficient"] is False and merged["guidance"]


def test_one_inventory_merges_to_itself():
    inv = _real()
    merged = merge_inventories([copy.deepcopy(inv)], "distinct_piles", labels=["only"])
    assert merged["totals"]["pieces"] == inv["totals"]["pieces"]
    assert merged["merge"]["likely_same_pile"] is False
    _consistent(merged)


def test_a_single_inventory_is_not_warned_about_photos_disagreeing():
    """There is no pair to disagree. A warning here would be noise the user learns to ignore."""
    assert merge_inventories([_real()], "same_pile")["merge"]["warning"] is None


def test_merging_does_not_mutate_its_inputs():
    """Everything in this project is value-in, value-out. A merge that edited the photo's own
    inventory would corrupt the version the user is still reviewing in the bin UI."""
    a, b = _real(), _real()
    before = json.dumps([a, b], sort_keys=True)
    merge_inventories([a, b], "same_pile", labels=["a", "b"])
    merge_inventories([a, b], "distinct_piles", labels=["a", "b"])
    assert json.dumps([a, b], sort_keys=True) == before


def test_an_unknown_mode_is_refused_loudly():
    with pytest.raises(ValueError):
        merge_inventories([_real()], "average")


def test_thresholds_are_explicit_and_tunable():
    a = _inv([_row("3001", 4, 0.9), _row("3010", 1, 0.9)])
    b = _inv([_row("3001", 4, 0.9), _row("3005", 14, 0.9)])
    sim = histogram_similarity(a, b)
    assert 0.0 < sim < SAME_PILE_AT
    assert detect_duplicates([a, b], ["a", "b"]) == []
    assert detect_duplicates([a, b], ["a", "b"], threshold=sim - 0.01)


# ---------------------------------------------------------------- CLI


def test_cli_writes_a_merged_file_and_reports_its_mode(tmp_path, capsys):
    inv = _real()
    p1, p2 = tmp_path / "lego1.json", tmp_path / "lego2.json"
    p1.write_text(json.dumps(inv))
    p2.write_text(json.dumps(inv))
    out = tmp_path / "merged.json"

    assert main([str(p1), str(p2), "-o", str(out), "--mode", "same_pile"]) == 0

    merged = json.loads(out.read_text())
    assert merged["totals"]["pieces"] == inv["totals"]["pieces"]
    assert merged["merge"]["sources"] == ["lego1", "lego2"]
    assert "same_pile" in capsys.readouterr().out


def test_cli_skips_a_missing_file_rather_than_dying(tmp_path, capsys):
    p1 = tmp_path / "lego1.json"
    p1.write_text(json.dumps(_real()))
    out = tmp_path / "merged.json"
    assert main([str(p1), str(tmp_path / "nope.json"), "-o", str(out)]) == 0
    assert json.loads(out.read_text())["merge"]["sources"] == ["lego1"]


def test_cli_with_nothing_readable_exits_nonzero(tmp_path):
    assert main([str(tmp_path / "nope.json"), "-o", str(tmp_path / "m.json")]) == 2
