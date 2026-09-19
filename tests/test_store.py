"""The brick collection tracker. These guard the promises that matter to a user."""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from vision.store import BrickStore, _key

REAL = pathlib.Path(__file__).resolve().parents[1] / "data" / "real" / "inventory.json"


def _scan(items, sid="s1"):
    return {"session_id": sid, "items": items,
            "totals": {"pieces": sum(i["qty"] for i in items), "distinct": len(items),
                       "unknown": 0}}


def _item(i, part, color, qty=1, status="confirmed", score=0.9):
    return {"id": f"inv_{i:03d}", "part": part, "name": part, "color": color, "qty": qty,
            "source": "photo", "confidence": {"part": score, "color": 0.9},
            "status": status, "color_mode": "similar",
            "evidence": {"photo": "p.jpg", "bbox": [0, 0, 10, 10], "bboxes": [[0, 0, 10, 10]],
                         "alternatives": []}}


def test_a_new_store_is_empty(tmp_path):
    s = BrickStore(tmp_path / "c.json")
    assert s.owned().total == 0 and s.summary()["scans"] == 0


def test_the_collection_survives_a_restart(tmp_path):
    p = tmp_path / "c.json"
    s = BrickStore(p)
    s.add_scan(_scan([_item(1, "3001", 4, 3)]))
    s.save()
    assert BrickStore(p).owned().total == 3


def test_rescanning_the_same_pile_does_not_double_your_bricks(tmp_path):
    """The failure that matters most: an overcount produces instructions for bricks you don't own."""
    s = BrickStore(tmp_path / "c.json")
    scan = _scan([_item(1, "3001", 4, 5), _item(2, "3003", 15, 4)])
    s.add_scan(scan, label="first")
    s.add_scan(json.loads(json.dumps(scan)), label="same-pile-again")
    assert s.owned().total == 9, "re-shooting the same bricks must not add them twice"


def test_scanning_a_different_handful_does_add(tmp_path):
    s = BrickStore(tmp_path / "c.json")
    s.add_scan(_scan([_item(1, "3001", 4, 5)]), label="a", mode="distinct_piles")
    s.add_scan(_scan([_item(1, "3020", 2, 6)]), label="b", mode="distinct_piles")
    assert s.owned().total == 11


def test_a_correction_sticks_and_applies_to_future_scans(tmp_path):
    """Correct a brick once; it stays corrected in every photo you ever take of it."""
    s = BrickStore(tmp_path / "c.json")
    s.add_scan(_scan([_item(1, "3001", 4, 2)]), label="a")
    s.correct("3001", 4, "3003", 4, note="it's a 2x2, not a 2x4")
    assert ("3003", 4) in s.owned().items

    s.add_scan(_scan([_item(1, "3001", 4, 1)]), label="b", mode="distinct_piles")
    assert ("3001", 4) not in s.owned().items, "the correction must apply to the NEW scan too"


def test_reserving_a_build_removes_bricks_from_available_but_not_from_owned(tmp_path):
    s = BrickStore(tmp_path / "c.json")
    s.add_scan(_scan([_item(1, "3001", 4, 10)]))
    s.reserve("bld_1", {("3001", 4): 4}, name="Rover")
    assert s.owned().total == 10, "the bricks are still yours, they are just in a model"
    assert s.available().total == 6
    assert s.summary()["reserved_pieces"] == 4


def test_taking_a_build_apart_returns_its_bricks(tmp_path):
    s = BrickStore(tmp_path / "c.json")
    s.add_scan(_scan([_item(1, "3001", 4, 10)]))
    s.reserve("bld_1", {("3001", 4): 4})
    assert s.release("bld_1") is True
    assert s.available().total == 10
    assert s.release("bld_1") is False, "releasing twice must not resurrect bricks"


def test_availability_never_goes_negative(tmp_path):
    s = BrickStore(tmp_path / "c.json")
    s.add_scan(_scan([_item(1, "3001", 4, 2)]))
    s.reserve("greedy", {("3001", 4): 99})
    assert s.available().total == 0


def test_unknown_rows_are_owned_but_not_offered_to_the_solver(tmp_path):
    s = BrickStore(tmp_path / "c.json")
    s.add_scan(_scan([_item(1, "3001", 4, 3), _item(2, "9999", 4, 5, status="unknown")]))
    assert s.owned().total == 3
    assert s.owned(include_unknown=True).total == 8


def test_every_change_is_recorded(tmp_path):
    """A tracker that quietly revises how many bricks you own is worse than no tracker."""
    s = BrickStore(tmp_path / "c.json")
    s.add_scan(_scan([_item(1, "3001", 4, 2)]))
    s.correct("3001", 4, "3003", 4)
    s.reserve("b1", {("3003", 4): 1})
    s.release("b1")
    kinds = [h["kind"] for h in s.history]
    assert kinds == ["scan", "correction", "reserve", "release"]


def test_schema_mismatch_refuses_rather_than_guessing(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"schema": 999, "inventory": {}}))
    with pytest.raises(ValueError, match="schema"):
        BrickStore(p)


@pytest.mark.skipif(not REAL.exists(), reason="needs the real scan")
def test_the_real_scan_loads_and_reconciles(tmp_path):
    s = BrickStore(tmp_path / "c.json")
    s.add_scan(json.loads(REAL.read_text()), label="lego.jpg")
    summ = s.summary()
    assert summ["owned_pieces"] > 40
    assert summ["distinct_parts"] < summ["distinct_elements"], (
        "a real bin is long-tail: fewer distinct PARTS than part+colour combinations")
