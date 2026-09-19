"""Tests for the `sculpt` backend: parse hard, tile honestly, repeat exactly."""

import json
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest

from core import meta
from core.model import Inventory
from core.sculpt import LayerMap, SculptError, parse, sculpt, tile
from core.sculpt.parse import EMPTY

PLATES = ["3460", "3666", "3710", "3623", "3023b", "3024",
          "3832", "3034", "3795", "3020", "3021", "3022"]
BRICKS = ["3008", "3009", "3010", "3622", "3004", "3005",
          "3006", "3007", "2456", "3001", "3002", "3003"]


def rich_inventory(n=40, colors=(4, 0, 15)):
    return Inventory.from_pairs([(p, c, n) for p in PLATES + BRICKS for c in colors])


def solid(w=6, d=6, h=3, ch="R", color=4):
    return {"grid": {"w": w, "d": d}, "palette": {ch: color},
            "layers": ["\n".join([ch * w] * d)] * h}


# ---------------------------------------------------------------- 1. parse: the happy path

def test_parses_a_layer_map():
    lm = parse(solid(4, 3, 2))
    assert (lm.w, lm.d, lm.height) == (4, 3, 2)
    assert lm.filled == 4 * 3 * 2
    assert lm.colors == (4,)
    assert lm.layers[0][0] == (4, 4, 4, 4)


def test_parses_json_text_and_multiple_colours():
    spec = {"grid": {"w": 3, "d": 2}, "palette": {"R": 4, "K": 0},
            "layers": ["RRK\nKKR"]}
    lm = parse(json.dumps(spec))
    assert lm.colors == (0, 4)
    assert lm.layers[0] == ((4, 4, 0), (0, 0, 4))


def test_narrow_and_shallow_layers_are_padded_not_rejected():
    """A layer smaller than the grid is a legal drawing; only overflow is an error."""
    lm = parse({"grid": {"w": 5, "d": 4}, "palette": {"R": 4}, "layers": ["RR\nRR"]})
    assert len(lm.layers[0]) == 4 and len(lm.layers[0][0]) == 5
    assert lm.layers[0][0] == (4, 4, EMPTY, EMPTY, EMPTY)
    assert lm.layers[0][3] == (EMPTY,) * 5


def test_render_round_trips_the_text():
    lm = parse({"grid": {"w": 3, "d": 2}, "palette": {"R": 4, "K": 0}, "layers": ["R.K\nKRR"]})
    assert lm.render() == "R.K\nKRR"


# ---------------------------------------------------------------- 2. parse: precise refusals

@pytest.mark.parametrize("code,spec", [
    ("RAGGED_LAYER",   {"grid": {"w": 4, "d": 2}, "palette": {"R": 4}, "layers": ["RRRR\nRR"]}),
    ("UNKNOWN_CHAR",   {"grid": {"w": 3, "d": 1}, "palette": {"R": 4}, "layers": ["RQR"]}),
    ("LAYER_TOO_WIDE", {"grid": {"w": 2, "d": 2}, "palette": {"R": 4}, "layers": ["RRRR\nRRRR"]}),
    ("LAYER_TOO_DEEP", {"grid": {"w": 2, "d": 1}, "palette": {"R": 4}, "layers": ["RR\nRR"]}),
    ("EMPTY_LAYER",    {"grid": {"w": 2, "d": 1}, "palette": {"R": 4}, "layers": ["RR", ".."]}),
    ("EMPTY_LAYER",    {"grid": {"w": 2, "d": 1}, "palette": {"R": 4}, "layers": ["RR", "  \n "]}),
    ("NO_LAYERS",      {"grid": {"w": 2, "d": 1}, "palette": {"R": 4}, "layers": []}),
    ("BAD_LAYER",      {"grid": {"w": 2, "d": 1}, "palette": {"R": 4}, "layers": [42]}),
    ("BAD_PALETTE",    {"grid": {"w": 2, "d": 1}, "palette": {"RR": 4}, "layers": ["RR"]}),
    ("BAD_PALETTE",    {"grid": {"w": 2, "d": 1}, "palette": {".": 4}, "layers": ["RR"]}),
    ("BAD_PALETTE",    {"grid": {"w": 2, "d": 1}, "palette": {"R": "red"}, "layers": ["RR"]}),
    ("BAD_PALETTE",    {"grid": {"w": 2, "d": 1}, "palette": {}, "layers": ["RR"]}),
    ("BAD_GRID",       {"grid": {"w": 0, "d": 1}, "palette": {"R": 4}, "layers": ["RR"]}),
    ("BAD_GRID",       {"grid": {"w": 2.5, "d": 1}, "palette": {"R": 4}, "layers": ["RR"]}),
    ("BAD_GRID",       {"palette": {"R": 4}, "layers": ["RR"]}),
    ("TOO_TALL",       {"grid": {"w": 1, "d": 1}, "palette": {"R": 4}, "layers": ["R"] * 200}),
])
def test_malformed_shapes_are_refused_with_a_precise_code(code, spec):
    with pytest.raises(SculptError) as exc:
        parse(spec)
    assert exc.value.code == code
    assert exc.value.human and exc.value.human[-1] in ".)"


def test_the_error_names_the_layer_row_and_column():
    with pytest.raises(SculptError) as exc:
        parse({"grid": {"w": 3, "d": 2}, "palette": {"R": 4}, "layers": ["RRR\nRRR", "RRR\nRQR"]})
    h = exc.value.human
    assert "Layer 1" in h and "row 1" in h and "column 1" in h and "'Q'" in h


def test_bad_json_is_refused_rather_than_half_parsed():
    with pytest.raises(SculptError) as exc:
        parse("{not json")
    assert exc.value.code == "BAD_JSON"


# ---------------------------------------------------------------- 3. tile: the happy path

def test_solid_block_tiles_and_validates():
    r = sculpt(solid(6, 6, 3), rich_inventory(), seed=11)
    assert r.report.ok, r.notes
    assert r.uncovered == 0
    covered = sum(meta.get(p.part).footprint(p.rot)[0] * meta.get(p.part).footprint(p.rot)[1]
                  * meta.get(p.part).h for p in r.build.parts)
    assert covered == 6 * 6 * 3          # every voxel filled exactly once, no part invented
    assert len(r.build.parts) < 6 * 6 * 3  # and it actually used big pieces
    assert r.build.provenance["backend"] == "sculpt"


def test_layers_cross_so_the_stack_is_one_object():
    """A tall block must come out as a single connected component, not a pile of planks."""
    r = sculpt(solid(8, 8, 4), rich_inventory(), seed=3)
    assert r.report.ok, r.notes
    assert not any(w.code == "WEAK_BOND" for w in r.report.warnings), r.report.warnings


def test_each_part_keeps_the_colour_of_the_cells_it_covers():
    spec = {"grid": {"w": 6, "d": 2}, "palette": {"R": 4, "K": 0},
            "layers": ["RRRKKK\nRRRKKK"] * 3}
    r = sculpt(spec, rich_inventory(), seed=5)
    lm = parse(spec)
    want = {(x, y, z): c for (x, y, z, c) in lm.cells()}
    for p in r.build.parts:
        m = meta.get(p.part)
        for cx, cz in m.cells(p.rot):
            assert want[(p.x + cx, p.y, p.z + cz)] == p.color


def test_brick_unit_puts_one_voxel_layer_every_three_plates():
    r = sculpt(solid(4, 4, 2), rich_inventory(), seed=2, unit="brick")
    assert sorted({p.y for p in r.build.parts}) == [0, 3]
    assert all(meta.get(p.part).h == 3 for p in r.build.parts)


# ---------------------------------------------------------------- 4. tile: the finite bin

def test_degrades_gracefully_instead_of_inventing_parts():
    """Six 1x1 plates cannot make a 4x4x2 block, and we say so rather than conjuring bricks."""
    inv = Inventory.from_pairs([("3024", 4, 6)])
    r = sculpt(solid(4, 4, 2), inv, seed=1)
    used = r.build.counts
    assert used, "should still return the piece of the shape it can afford"
    for (part, color), n in used.items():
        assert n <= inv.qty(part, color), f"invented {part}"
    assert sum(used.values()) <= 6
    assert r.uncovered > 0 and r.notes
    assert all(q >= 0 for q in r.remaining.items.values())


def test_never_exceeds_the_inventory_even_when_it_is_lopsided():
    inv = Inventory.from_pairs([("3024", 4, 3), ("3023b", 4, 4), ("3022", 4, 2)])
    r = sculpt(solid(5, 5, 3), inv, seed=9)
    for (part, color), n in r.build.counts.items():
        assert n <= inv.qty(part, color)
    assert set(r.build.counts) <= set(inv.items)


def test_an_empty_bin_yields_an_empty_build_not_a_crash():
    r = sculpt(solid(3, 3, 1), Inventory.from_pairs([]), seed=0)
    assert r.build.parts == ()
    assert not r.report.ok and r.report.errors[0].code == "EMPTY"
    assert r.uncovered == 9


# ---------------------------------------------------------------- 5. determinism

def _fingerprint(r):
    return json.dumps([[p.id, p.part, p.color, list(p.pos), p.rot, p.sub] for p in r.build.parts],
                      sort_keys=True)


def test_same_seed_twice_is_byte_identical():
    spec = solid(7, 5, 3)
    inv = rich_inventory()
    a = sculpt(spec, inv, seed=42)
    b = sculpt(spec, inv, seed=42)
    assert _fingerprint(a) == _fingerprint(b)
    assert a.score == b.score and a.uncovered == b.uncovered


def test_a_different_seed_explores_a_different_tiling():
    spec = solid(9, 7, 3)
    inv = rich_inventory()
    seen = {_fingerprint(sculpt(spec, inv, seed=s)) for s in range(6)}
    assert len(seen) > 1, "restarts are not actually randomized"


def test_restart_count_is_the_budget_and_one_restart_still_works():
    r = tile(parse(solid(5, 5, 2)), rich_inventory(), seed=0, restarts=1)
    assert r.report.ok, r.notes
    assert r.build.provenance["restarts"] == 1


def test_the_winner_is_never_a_tiling_that_had_to_be_rescued_by_pruning():
    """Regression: fewer-pieces-wins once picked loose planks and let the prune hide it."""
    for seed in range(6):
        r = sculpt(solid(6, 6, 3), rich_inventory(), seed=seed)
        assert r.report.ok, (seed, r.notes)
        assert not any("Removed" in n for n in r.notes), (seed, r.notes)
        area = sum(meta.get(p.part).footprint(p.rot)[0] * meta.get(p.part).footprint(p.rot)[1]
                   for p in r.build.parts)
        assert area == 6 * 6 * 3


def test_determinism_survives_a_fresh_interpreter():
    """Invariant 6 is about processes, not just calls -- so the seed must not ride on hash()."""
    import subprocess, textwrap
    prog = textwrap.dedent("""
        import json, sys, pathlib
        sys.path.insert(0, %r)
        from core.model import Inventory
        from core.sculpt import sculpt
        parts = %r
        inv = Inventory.from_pairs([(p, c, 40) for p in parts for c in (4, 0, 15)])
        spec = {"grid": {"w": 7, "d": 5}, "palette": {"R": 4},
                "layers": ["\\n".join(["RRRRRRR"] * 5)] * 3}
        r = sculpt(spec, inv, seed=42)
        print(json.dumps([[p.id, p.part, p.color, list(p.pos), p.rot] for p in r.build.parts]))
    """) % (str(pathlib.Path(__file__).resolve().parents[1]), PLATES + BRICKS)
    runs = {subprocess.run([sys.executable, "-c", prog], capture_output=True, text=True,
                           check=True).stdout for _ in range(2)}
    assert len(runs) == 1


# ---------------------------------------------------------------- 6. against the real fixture

def test_tiles_a_shape_from_the_real_fixture_inventory():
    raw = json.loads((pathlib.Path(__file__).resolve().parents[1]
                      / "fixtures" / "inventory.json").read_text())
    inv = Inventory.from_pairs([(i["part"], i["color"], i["qty"]) for i in raw["items"]
                                if i.get("status") != "unknown"])
    plus = "\n".join([".RRR.", "RRRRR", "RRRRR", "RRRRR", ".RRR."])
    r = sculpt({"grid": {"w": 5, "d": 5}, "palette": {"R": 4}, "layers": [plus] * 3},
               inv, seed=17)
    assert r.report.ok, r.notes
    assert r.uncovered == 0
    assert all(n <= inv.qty(*k) for k, n in r.build.counts.items())


def test_a_one_layer_mosaic_is_reported_disconnected_not_pruned_to_a_single_brick():
    """Rows of plates side by side really are loose. Say so; do not delete the model instead."""
    r = sculpt(solid(6, 6, 1), rich_inventory(), seed=1)
    assert len(r.build.parts) >= 3
    assert not r.report.ok
    assert any(e.code == "DISCONNECTED" for e in r.report.errors)
    assert any("does not" in n or "fall off" in n for n in r.notes)
