"""The allocator on a LONG-TAIL bin.

The bin these tests care about is `data/real/inventory.json` -- the user's own photographed
bricks: 57 identified pieces across 49 part+colour combinations, almost all quantity one. Every
claim about colour pooling and substitution is measured against that file rather than against a
hand-written tub of identical bricks, because a tub is exactly the case our generators already
handled and the bin is the case they collapsed on.

The load-bearing assertion in here is `test_never_exceeds_the_inventory_*`: no optimisation in
this module may hand out a brick the user does not own. That is the premise of the project.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from core import meta
from core.alloc import (
    BRICK_ROW,
    BRICK_WIDE,
    PLATE_ROW,
    Allocator,
    allocator_from_rows,
    inventory_from_rows,
)
from core.model import Inventory
from core.substitute import RULES, apply_rule, catalog_text, get_rule, rules_for

REAL = pathlib.Path(__file__).resolve().parents[1] / "data" / "real" / "inventory.json"


def real_rows() -> list[dict]:
    if not REAL.exists():                      # the photos are the user's; CI may not have them
        pytest.skip("data/real/inventory.json not present")
    return json.loads(REAL.read_text())["items"]


def consumed(alloc: Allocator, start: Inventory) -> dict[tuple[str, int], int]:
    """What actually left the bin, derived from `remaining` rather than from `used`."""
    keys = set(start.items) | set(alloc.remaining)
    return {k: start.qty(*k) - alloc.remaining.get(k, 0)
            for k in keys if start.qty(*k) - alloc.remaining.get(k, 0)}


# ------------------------------------------------------------------ 1. the rule table


def test_every_rule_tiles_its_parent_exactly():
    """Children must fill the parent's occupancy box with no gap and no overlap.

    This is what makes a 57-row generated table trustworthy: nobody checked it by hand, and
    nobody has to.
    """
    for rule in RULES.values():
        pm = meta.get(rule.part)
        want = {(x, y, z) for x in range(pm.w) for y in range(pm.h) for z in range(pm.d)}
        got: set[tuple[int, int, int]] = set()
        for part, dx, dy, dz in apply_rule(rule.part, rule):
            cm = meta.get(part)
            for x in range(cm.w):
                for y in range(cm.h):
                    for z in range(cm.d):
                        cell = (dx + x, dy + y, dz + z)
                        assert cell not in got, f"{rule.id}: children overlap at {cell}"
                        got.add(cell)
        assert got == want, f"{rule.id} does not tile {rule.part}"


def test_rule_offsets_are_integers_on_the_stud_grid():
    for rule in RULES.values():
        for part, dx, dy, dz in apply_rule(rule.part, rule):
            assert all(isinstance(v, int) for v in (dx, dy, dz)), "no floats in the build model"
            assert dz in (0, 1) and dy in (0, 1, 2) and dx >= 0


def test_the_rules_the_brief_names_all_exist():
    assert get_rule("3010_as_3004_3004").kind == "length"      # one 1x4 -> two 1x2
    assert get_rule("3004_as_3005_3005").kind == "length"      # one 1x2 -> two 1x1
    assert get_rule("3001_as_3003_3003").kind == "length"      # one 2x4 -> two 2x2
    assert get_rule("3001_as_three_3020").kind == "height"     # one brick -> three plates
    assert len(get_rule("3001_as_three_3020").children) == 3


def test_apply_rule_refuses_a_rule_for_a_different_part():
    with pytest.raises(ValueError):
        apply_rule("3005", get_rule("3010_as_3004_3004"))


def test_the_llm_catalogue_offers_ids_and_never_coordinates():
    """Invariant 4: the model picks a rule id; our code produces the numbers."""
    text = catalog_text()
    assert "3010_as_3004_3004" in text
    for line in text.splitlines():
        assert "dx" not in line and "(0, 0, 0)" not in line


def test_rules_for_can_exclude_what_a_caller_cannot_place():
    flat = rules_for("3001", flat_only=True)
    assert flat and all(r.flat for r in flat)
    narrow = rules_for("3001", flat_only=True, max_width=1)
    assert all(r.width == 1 for r in narrow)
    assert [r.penalty for r in flat] == sorted(r.penalty for r in flat), "cheapest first"


# ------------------------------------------------------------------ 2. colour pooling


def test_a_ten_long_row_fails_on_exact_and_succeeds_on_similar():
    """THE headline of this round, on the user's real bricks.

    The bin holds ten studs' worth of 1-wide bricks, just never ten in one colour. Insisting on
    colour is what turned "build me a rover" into a three-part build.
    """
    rows = real_rows()
    strict = allocator_from_rows(rows, color_policy="exact")
    assert strict.fill_row(10, 4, BRICK_ROW) is None

    pooled = allocator_from_rows(rows, color_policy="similar")
    row = pooled.fill_row(10, 4, BRICK_ROW)
    assert row is not None
    assert sum(t.length for t in row) == 10
    assert len({t.color for t in row}) > 1, "the point is that it crossed colours"


def test_a_substitution_is_recorded_in_words_the_ui_can_show():
    pooled = allocator_from_rows(real_rows(), color_policy="similar")
    assert pooled.fill_row(10, 4, BRICK_ROW) is not None
    subs = [s for s in pooled.substitutions if s.kind == "color"]
    assert subs, "a cross-colour fill that reports nothing is a silent lie to the user"
    s = subs[0]
    assert s.wanted_color == 4 and s.used_color != 4
    assert "instead of" in s.human


def test_best_colors_prefers_exact_then_the_deepest_stack():
    inv = Inventory.from_pairs([("3001", 4, 1), ("3001", 1, 5), ("3001", 2, 3)])
    a = Allocator(inv)
    assert a.best_colors("3001", 4) == [4, 1, 2]
    assert a.best_colors("3001", 15) == [1, 2, 4], "no exact match: deepest stack leads"


def test_exact_policy_never_pools_and_ignore_always_does():
    inv = Inventory.from_pairs([("3001", 1, 4)])
    assert Allocator(inv, color_policy="exact").best_colors("3001", 4) == []
    assert Allocator(inv, color_policy="ignore").best_colors("3001", 4) == [1]


def test_a_row_cv_was_confident_about_is_not_pooled_away():
    """Contract 1: `color_mode: "exact"` means trust that colour, so those bricks are only
    handed out for a request in that same colour."""
    inv = Inventory.from_pairs([("3001", 1, 4)])
    modes = {("3001", 1): "exact"}
    a = Allocator(inv, color_policy="similar", color_modes=modes)
    assert a.best_colors("3001", 4) == [], "an exact row was pooled into a red request"
    assert a.best_colors("3001", 1) == [1], "and is still available in its own colour"
    # "ignore" is the user overruling CV entirely, so it wins over the per-row hint.
    assert Allocator(inv, color_policy="ignore", color_modes=modes).best_colors("3001", 4) == [1]


def test_inventory_from_rows_honours_contract_one():
    rows = [
        {"part": "3001", "color": 4, "qty": 2, "status": "confirmed", "color_mode": "exact"},
        {"part": "3001", "color": 1, "qty": 1, "status": "needs_review", "color_mode": "similar"},
        {"part": "9999", "color": 0, "qty": 9, "status": "unknown"},
        {"part": "3003", "color": 0, "qty": 5, "status": "confirmed", "placeable": False},
    ]
    inv, modes = inventory_from_rows(rows)
    assert inv.total == 3, "unknown and unplaceable rows are excluded from the solver"
    assert modes[("3001", 4)] == "exact" and modes[("3001", 1)] == "similar"


# ------------------------------------------------------------------ 3. take / give_back


def test_take_is_exact_and_take_color_pools():
    inv = Inventory.from_pairs([("3001", 1, 1)])
    a = Allocator(inv, color_policy="similar")
    assert a.take("3001", 4) is False, "take() must not silently change colour under a caller"
    assert a.take_color("3001", 4) == 1
    assert a.have("3001", 1) == 0


def test_give_back_returns_the_colour_that_actually_left_the_bin():
    """A caller that only saw `take_color`'s bool still hands back the colour it ASKED for."""
    inv = Inventory.from_pairs([("3001", 1, 1)])
    a = Allocator(inv, color_policy="similar")
    assert a.take_color("3001", 4) == 1
    a.give_back("3001", 4)                       # asked red, was given blue, returns "red"
    assert a.remaining == {("3001", 1): 1}, "a rollback invented a red brick"
    assert a.total_used == 0
    assert not a.substitutions, "a rolled-back substitution must not stay on the record"


def test_accounting_never_drifts_between_used_and_remaining():
    inv = Inventory.from_pairs([("3001", 1, 2), ("3001", 4, 1)])
    a = Allocator(inv, color_policy="similar")
    a.take_color("3001", 4)          # exact
    a.take_color("3001", 4)          # pooled -> blue
    a.give_back("3001", 4)
    a.give_back("3001", 4)
    assert a.total_used == 0
    assert sum(a.remaining.values()) == inv.total


# ------------------------------------------------------------------ 4. part substitution


def test_a_row_completes_with_substitutes_when_the_exact_part_has_run_out():
    """Palette holds only the 1x4; the bin holds only 1x2s. The rule table bridges them."""
    inv = Inventory.from_pairs([("3004", 4, 2)])
    a = Allocator(inv)
    row = a.fill_row(4, 4, ["3010"])
    assert row is not None
    assert [t.part for t in row] == ["3004", "3004"]
    assert [t.dx for t in row] == [0, 2]
    assert any(s.kind == "part" and s.rule == "3010_as_3004_3004" for s in a.substitutions)


def test_substitution_recurses_within_its_budget():
    inv = Inventory.from_pairs([("3005", 4, 4)])
    a = Allocator(inv)
    row = a.fill_row(4, 4, ["3010"])             # 1x4 -> two 1x2 -> four 1x1
    assert row is not None
    assert [t.part for t in row] == ["3005"] * 4
    assert [t.dx for t in row] == [0, 1, 2, 3]


def test_substitution_can_be_switched_off():
    inv = Inventory.from_pairs([("3004", 4, 2)])
    assert Allocator(inv, substitute=False).fill_row(4, 4, ["3010"]) is None


def test_a_failed_substitution_costs_nothing():
    inv = Inventory.from_pairs([("3004", 4, 1)])
    a = Allocator(inv)
    assert a.fill_row(4, 4, ["3010"]) is None, "one 1x2 cannot cover four studs"
    assert a.remaining == dict(inv.items)
    assert a.total_used == 0
    assert not a.substitutions


def test_a_band_may_split_across_its_width_and_the_rect_keeps_the_offset():
    """The 2-wide part is what joins two rows, so splitting it is the most expensive rule --
    but two 1x2s beat no build at all. `fill_rect` must add its row offset, not overwrite it."""
    inv = Inventory.from_pairs([("3004", 4, 2)])
    a = Allocator(inv)
    band = a.fill_band(2, 4, BRICK_WIDE)
    assert band is not None
    assert sorted(t.dz for t in band) == [0, 1]

    a2 = Allocator(Inventory.from_pairs([("3004", 4, 4)]))
    rect = a2.fill_rect(2, 2, 4, BRICK_ROW)
    assert rect is not None
    cells = {(t.dx + dx, t.dz) for t in rect for dx in range(t.length)}
    assert len(cells) == 4, "two parts landed in the same cell"


# ------------------------------------------------------------------ 5. use what you have


def test_best_fill_returns_the_best_row_it_can_build_instead_of_none():
    inv = Inventory.from_pairs([("3004", 4, 2)])
    a = Allocator(inv, substitute=False)
    assert a.fill_row(10, 4, BRICK_ROW) is None
    got = a.best_fill(10, 4, BRICK_ROW, substitute=False)
    assert got is not None
    assert got.covered == 4 and got.shortfall == 6 and not got.complete
    assert "4" in got.human and "short" in got.human
    assert sum(t.length for t in got.taken) == got.covered


def test_best_fill_reports_completion_when_the_bin_is_enough():
    a = Allocator(Inventory.from_pairs([("3004", 4, 6)]))
    got = a.best_fill(8, 4, BRICK_ROW)
    assert got is not None and got.complete and got.shortfall == 0


def test_best_fill_is_none_only_when_nothing_at_all_can_be_laid():
    a = Allocator(Inventory.from_pairs([("3068b", 4, 1)]))
    assert a.best_fill(6, 4, BRICK_ROW) is None


def test_best_rect_rescues_the_rover_chassis_from_the_real_bin():
    """The exact failure that collapsed the demo build: a 10x4 plate floor the bin cannot tile.

    The repair ladder shrank 10 -> 8 and still failed. `best_rect` answers with the largest
    rectangle that IS buildable, so the generator can shrink the design instead of vanishing.
    """
    rows = real_rows()
    a = allocator_from_rows(rows, color_policy="similar")
    assert a.fill_rect(10, 4, 4, PLATE_ROW) is None

    b = allocator_from_rows(rows, color_policy="similar")
    got = b.best_rect(10, 4, 4, PLATE_ROW)
    assert got is not None
    assert got.requested == (10, 4) and not got.complete
    cw, cd = got.covered
    assert cw >= 4 and cd == 4, f"expected a usable floor, got {got.covered}"
    assert "10x4" in got.human


def test_best_rect_fills_completely_when_it_can():
    rows = real_rows()
    a = allocator_from_rows(rows, color_policy="similar")
    got = a.best_rect(10, 4, 4, BRICK_ROW)
    assert got is not None and got.complete, "the bin holds twelve 2x4s; a brick deck must fit"


# ------------------------------------------------------------------ 6. the premise


@pytest.mark.parametrize("policy", ["exact", "similar", "ignore"])
def test_never_exceeds_the_inventory_on_the_real_bin(policy):
    """No pooling, substitution or best-fit path may hand out a brick the user does not own."""
    rows = real_rows()
    start, _ = inventory_from_rows(rows)
    a = allocator_from_rows(rows, color_policy=policy)

    for palette in (BRICK_ROW, PLATE_ROW):
        for want in (12, 8, 6, 4, 2):
            a.best_rect(want, 4, 4, palette, min_depth=1)
            a.best_fill(want, 14, palette)

    assert all(n >= 0 for n in a.remaining.values()), "the allocator went into debt"
    spent = consumed(a, start)
    assert all(n <= start.qty(*k) for k, n in spent.items())
    assert sum(spent.values()) == a.total_used, "`used` and `remaining` disagree"
    assert a.total_used <= start.total


def test_never_exceeds_the_inventory_when_substitution_is_starved():
    """Ask for far more than the bin holds, repeatedly. Rollbacks must be exact."""
    inv = Inventory.from_pairs([("3004", 4, 3), ("3005", 1, 2), ("3010", 15, 1)])
    a = Allocator(inv)
    for _ in range(20):
        a.best_rect(9, 3, 4, BRICK_ROW, min_depth=1)
        a.fill_row(9, 2, BRICK_ROW)
    assert all(n >= 0 for n in a.remaining.values())
    assert sum(consumed(a, inv).values()) == a.total_used <= inv.total


# ------------------------------------------------------------------ 7. determinism


def test_same_bin_and_same_request_give_byte_identical_results():
    """Invariant 6. Undo, replay and 'try another' all rest on this."""
    rows = real_rows()

    def run():
        a = allocator_from_rows(rows, color_policy="similar")
        got = a.best_rect(10, 4, 4, BRICK_ROW)
        return ([(t.part, t.rot, t.dx, t.dz, t.color) for t in got.taken], got.covered,
                [s.human for s in a.substitutions])

    assert run() == run()
