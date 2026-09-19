"""The four tests that matter. If these pass, the foundation is trustworthy."""

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest

from core import meta
from core.alloc import Allocator, BRICK_ROW
from core.compose import Composition, compose
from core.ldraw import to_ldraw
from core.model import Build, Inventory, Placed
from core.sequence import order_parts, sequence
from core.validate import connections, validate

PALETTE = ["3008", "3009", "3010", "3622", "3004", "3005", "3460", "3666", "3710",
           "3623", "3023b", "3024", "3069b", "3070b", "2431", "3006", "3007", "2456",
           "3001", "3002", "3003", "3832", "3034", "3795", "3020", "3021", "3022"]


def rich_inventory(n=30):
    return Inventory.from_pairs([(p, c, n) for p in PALETTE for c in (4, 15, 0)])


# ---------------------------------------------------------------- 1. metadata

@pytest.mark.parametrize("part,w,d,h,tile", [
    ("3001", 4, 2, 3, False),   # brick 2x4
    ("3005", 1, 1, 3, False),   # brick 1x1
    ("3024", 1, 1, 1, False),   # plate 1x1
    ("3020", 4, 2, 1, False),   # plate 2x4
    ("3069b", 2, 1, 1, True),   # tile 1x2 -- the corner-feature trap
    ("3070b", 1, 1, 1, True),   # tile 1x1
    ("3023b", 2, 1, 1, False),  # plate 1x2 -- bricknet keys are exact LDraw filenames
])
def test_part_metadata_matches_reality(part, w, d, h, tile):
    m = meta.get(part)
    assert (m.w, m.d, m.h) == (w, d, h)
    assert m.is_tile is tile


def test_rotation_swaps_footprint_and_moves_studs():
    m = meta.get("3001")
    assert m.footprint(0) == (4, 2)
    assert m.footprint(90) == (2, 4)
    assert len(m.stud_cells(0)) == len(m.stud_cells(90)) == 8
    assert min(c[0] for c in m.stud_cells(90)) == 0


# ---------------------------------------------------------------- 2. validator

def test_validator_catches_overlap():
    b = Build("x", "x").add(Placed("a", "3001", 4, (0, 0, 0)),
                            Placed("b", "3001", 4, (0, 0, 0)))
    r = validate(b)
    assert not r.ok and any(e.code == "OVERLAP" for e in r.errors)


def test_validator_catches_floating():
    b = Build("x", "x").add(Placed("a", "3001", 4, (0, 0, 0)),
                            Placed("b", "3001", 4, (0, 9, 0)))
    r = validate(b)
    assert not r.ok and any(e.code == "UNSUPPORTED" for e in r.errors)


def test_validator_catches_disconnected():
    b = Build("x", "x").add(Placed("a", "3001", 4, (0, 0, 0)),
                            Placed("b", "3001", 4, (20, 0, 0)))
    r = validate(b)
    assert not r.ok and any(e.code == "DISCONNECTED" for e in r.errors)


def test_validator_catches_over_budget():
    b = Build("x", "x").add(Placed("a", "3001", 4, (0, 0, 0)),
                            Placed("b", "3001", 4, (0, 3, 0)))
    r = validate(b, Inventory.from_pairs([("3001", 4, 1)]))
    assert not r.ok and any(e.code == "OUT_OF_BUDGET" for e in r.errors)


def test_validator_accepts_a_good_stack():
    b = Build("x", "x").add(Placed("a", "3001", 4, (0, 0, 0)),
                            Placed("b", "3001", 4, (2, 3, 0)))
    r = validate(b, Inventory.from_pairs([("3001", 4, 2)]))
    assert r.ok, [e.human for e in r.errors]


def test_nothing_attaches_on_top_of_a_tile():
    """A tile has no studs. Footprint overlap alone is not a connection."""
    b = Build("x", "x").add(Placed("t", "3068b", 4, (0, 0, 0)),
                            Placed("p", "3022", 4, (0, 1, 0)))
    assert connections(b) == []
    assert not validate(b).ok


# ---------------------------------------------------------------- 3. allocator

def test_allocator_degrades_to_smaller_parts():
    a = Allocator(Inventory.from_pairs([("3004", 4, 6)]))
    row = a.fill_row(8, 4, BRICK_ROW)
    assert row is not None and sum(t.length for t in row) == 8
    assert {t.part for t in row} == {"3004"}


def test_allocator_rolls_back_when_it_cannot_finish():
    inv = Inventory.from_pairs([("3004", 4, 1)])
    a = Allocator(inv)
    assert a.fill_row(8, 4, BRICK_ROW) is None
    assert a.remaining == dict(inv.items), "a failed fill must not consume inventory"


def test_allocator_cannot_exceed_inventory():
    inv = Inventory.from_pairs([("3005", 4, 3)])
    a = Allocator(inv)
    taken = sum(1 for _ in range(10) if a.take("3005", 4))
    assert taken == 3


# ---------------------------------------------------------------- 4. round trip

def test_ldraw_roundtrip_preserves_part_count():
    b = Build("x", "Wall").add(*[Placed(f"p{i}", "3001", 4, (0, 3 * i, 0)) for i in range(3)])
    text = to_ldraw(b, sequence(b))
    refs = [ln for ln in text.splitlines() if ln.startswith("1 ")]
    assert len(refs) == 3
    assert text.count("0 STEP") == len(sequence(b))


def test_geometry_agrees_with_an_independent_implementation():
    """Cross-check our coordinate conversion against bricknet's own LDraw parser."""
    graph = pytest.importorskip("bricknet.graph")
    b = Build("x", "Wall").add(
        *[Placed(f"a{i}", "3001", 4, (i * 4, 0, 0)) for i in range(3)],
        *[Placed(f"b{i}", "3001", 15, (i * 4 + 2, 3, 0)) for i in range(2)])
    ours = {(lo, hi) for lo, hi, _ in connections(b)}
    assert len(ours) == 4
    g = graph.parse_ldr(to_ldraw(b, sequence(b)))
    assert len(g.part_ids) == 5
    pairs = {(int(e["a"]), int(e["b"])) for e in g.edges}
    assert len(pairs) == len(ours), "bricknet must find the same number of joins we do"


# ---------------------------------------------------------------- 5. sequencing

def test_sequencer_never_places_a_part_before_its_support():
    b, rep, _ = compose(Composition("chassis", [
        {"id": "chassis", "gen": "chassis", "args": {"length": 8, "width": 4}},
        {"id": "cabin", "gen": "cabin", "attach_to": "chassis",
         "args": {"length": 4, "width": 4, "height": 6}},
    ]), rich_inventory())
    assert rep.ok, [e.human for e in rep.errors]
    ordered = order_parts(b)
    seen, supports = set(), {p.id: set() for p in b.parts}
    for lo, hi, _ in connections(b):
        supports[hi].add(lo)
    for p in ordered:
        assert supports[p.id] <= seen, f"{p.id} placed before its support"
        seen.add(p.id)


def test_compose_produces_a_valid_build_within_inventory():
    inv = rich_inventory()
    b, rep, _ = compose(Composition("chassis", [
        {"id": "chassis", "gen": "chassis", "args": {"length": 10, "width": 4}, "color": 4},
        {"id": "cabin", "gen": "cabin", "attach_to": "chassis", "at": "top_rear",
         "args": {"length": 4, "width": 4, "height": 6}, "color": 15},
    ]), inv, name="Rover")
    assert rep.ok, [e.human for e in rep.errors]
    for (part, color), n in b.counts.items():
        assert n <= inv.qty(part, color)


def test_compose_degrades_instead_of_cheating_when_short_of_bricks():
    """The inventory is a constraint, not a suggestion. Running out must never invent parts."""
    tiny = Inventory.from_pairs([("3004", 4, 2)])
    b, rep, notes = compose(Composition("slab", [
        {"id": "slab", "gen": "slab", "args": {"length": 10, "width": 4}},
    ]), tiny)
    assert len(b.parts) == 0
    assert any("not enough bricks" in n for n in notes)
