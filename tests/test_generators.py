"""Tests for the silhouette generators in core/generators/extra.py.

Three things are worth testing about a generator and nothing else really is:

  * with bricks to spare it produces something the validator accepts,
  * with an empty bin it says no instead of producing a model that cannot exist,
  * it never spends a brick the user does not own.

Everything below is one of those three, plus a regression for each bug found writing them.
Each of those regressions is a shape that LOOKED right and was not: legs whose ties overlapped,
a wing whose two layers had the same seams, a roof that called a 2x1 slope two studs long.
"""

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest

from core import meta
from core.alloc import Allocator
from core.compose import Composition, compose
from core.generators import GENERATORS, generate
from core.generators.registry import catalog_text
from core.model import Build, Inventory, Placed
from core.validate import validate

NEW = ["wing", "roof_gable", "arch", "turret", "cockpit", "legs", "neck", "fence"]

RICH = ["3008", "3009", "3010", "3622", "3004", "3005", "3460", "3666", "3710", "3623",
        "3023b", "3024", "3069b", "3070b", "2431", "3006", "3007", "2456", "3001", "3002",
        "3003", "3832", "3034", "3795", "3020", "3021", "3022", "3038", "3039", "3040b"]
SMALL = ["3005", "3004", "3024", "3023b"]           # 1x1 and 1x2 bricks and plates only
NO_SLOPES = [p for p in RICH if p not in ("3038", "3039", "3040b")]

# A spread per generator: the default, something small, something big, and the awkward shapes
# (odd widths, one leg, no lean) that are where off-by-one geometry actually breaks.
CASES = [
    ("wing", {}), ("wing", {"span": 4, "depth": 1}), ("wing", {"span": 13, "depth": 5}),
    ("roof_gable", {}), ("roof_gable", {"length": 4, "width": 4}),
    ("roof_gable", {"length": 9, "width": 7}), ("roof_gable", {"length": 5, "width": 2}),
    ("arch", {}), ("arch", {"width": 1, "height": 3}), ("arch", {"width": 4, "height": 12}),
    ("turret", {}), ("turret", {"radius": 1, "height": 3}),
    ("turret", {"radius": 3, "height": 12}), ("turret", {"radius": 5, "height": 6}),
    ("cockpit", {}), ("cockpit", {"length": 2, "width": 1}),
    ("cockpit", {"length": 9, "width": 5}),
    ("legs", {}), ("legs", {"count": 1, "height": 3}), ("legs", {"count": 7, "height": 12}),
    ("neck", {}), ("neck", {"height": 3, "lean": 0}), ("neck", {"height": 15, "lean": -1}),
    ("fence", {}), ("fence", {"length": 1, "height": 3}), ("fence", {"length": 11, "height": 9}),
]
IDS = [f"{n}{sorted(kw.items())}" for n, kw in CASES]


def bin_of(parts: list[str], qty: int = 200, colors=(4, 15, 0)) -> Inventory:
    return Inventory.from_pairs([(p, c, qty) for p in parts for c in colors])


def as_build(res) -> Build:
    return Build("gen", "gen").add(*res.parts)


# ---------------------------------------------------------------- 1. it is wired up


def test_every_new_generator_is_registered_and_described():
    catalog = catalog_text()
    for name in NEW:
        assert name in GENERATORS, f"{name} never reached the registry"
        spec = GENERATORS[name]
        assert spec.tags, f"{name} has no tags, so the LLM cannot find it by theme"
        assert spec.doc, f"{name} has no docstring, and the docstring IS the prompt"
        assert f"- {name}(" in catalog


# ---------------------------------------------------------------- 2. it builds


@pytest.mark.parametrize("name,args", CASES, ids=IDS)
def test_generator_produces_a_build_the_validator_accepts(name, args):
    inv = bin_of(RICH)
    res = generate(name, Allocator(inv), 4, sub=name, **args)
    assert res is not None, f"{name}{args} gave up with a full bin"
    assert res.parts, f"{name}{args} returned an empty subassembly"
    report = validate(as_build(res), inv)
    assert report.ok, [e.human for e in report.errors]


@pytest.mark.parametrize("name,args", CASES, ids=IDS)
def test_generator_never_spends_a_brick_you_do_not_own(name, args):
    inv = bin_of(RICH, qty=3)           # deliberately tight: 3 of each part per colour
    alloc = Allocator(inv)
    res = generate(name, alloc, 4, sub=name, **args)
    if res is None:
        return
    for (part, color), used in as_build(res).counts.items():
        assert used <= inv.qty(part, color), f"{name} placed {used}x {part} in colour {color}"
        assert alloc.used.get((part, color), 0) == used, \
            f"{name} placed {part} without taking it from the allocator"


@pytest.mark.parametrize("name,args", CASES, ids=IDS)
def test_generator_only_places_parts_the_grid_knows(name, args):
    """A part with no metadata cannot be placed, rendered or counted. Catch it here, not in the
    validator, where it has already cost a round of the repair loop."""
    res = generate(name, Allocator(bin_of(RICH)), 4, sub=name, **args)
    assert res is not None
    for p in res.parts:
        assert meta.has(p.part), f"{name} placed {p.part}, which is not in the metadata table"
        assert p.rot in (0, 90, 180, 270)
        assert all(isinstance(v, int) for v in p.pos), "no floats in the build model"


@pytest.mark.parametrize("name", NEW)
def test_attachment_points_are_studs_that_really_exist(name):
    """Every attach point must name studs that are genuinely exposed, or children float.

    Tested the only way that means anything: put a 1x1 plate on every stud the generator
    declared and ask the validator whether they are supported.
    """
    res = generate(name, Allocator(bin_of(RICH)), 4, sub=name)
    assert res is not None
    extra = []
    for i, ap in enumerate(res.attach):
        assert ap.face == "top" and ap.studs
        for j, (sx, sz) in enumerate(ap.studs):
            extra.append(Placed(f"probe{i}_{j}", "3024", 4, (sx, ap.at[1], sz), 0, name))
    report = validate(as_build(res).add(*extra))
    assert report.ok, [e.human for e in report.errors][:5]


@pytest.mark.parametrize("name", NEW)
def test_same_bin_same_arguments_same_model(name):
    """Undo, replay and 'try another' all assume this (invariant 9)."""
    def shape():
        res = generate(name, Allocator(bin_of(RICH)), 4, sub=name)
        return [(p.part, p.color, p.pos, p.rot) for p in res.parts]
    assert shape() == shape()


# ---------------------------------------------------------------- 3. it degrades


@pytest.mark.parametrize("name", NEW)
def test_empty_bin_gives_none_not_a_broken_model(name):
    inv = Inventory.from_pairs([])
    assert generate(name, Allocator(inv), 4, sub=name) is None


@pytest.mark.parametrize("name", NEW)
def test_a_generator_that_gives_up_hands_the_bricks_back(name):
    """Three 1x1 bricks cannot become any of these. What matters is that the attempt costs
    nothing: the next generator in the composition must find the bin exactly as it was."""
    inv = Inventory.from_pairs([("3005", 4, 3)])
    alloc = Allocator(inv)
    assert generate(name, alloc, 4, sub=name) is None
    assert alloc.remaining == dict(inv.items), f"{name} kept bricks it did not use"
    assert not any(alloc.used.values())


@pytest.mark.parametrize("name", NEW)
def test_degrades_to_smaller_parts_instead_of_demanding_big_ones(name):
    """A bin of nothing but 1x1s and 1x2s is the realistic worst case for a loose-brick pile."""
    inv = bin_of(SMALL, qty=400)
    res = generate(name, Allocator(inv), 4, sub=name)
    if res is None:
        # Only the arch may legitimately fail here: a doorway needs one part long enough to
        # span the opening, and nothing in this bin spans anything.
        assert name == "arch"
        return
    assert validate(as_build(res), inv).ok
    assert {p.part for p in res.parts} <= set(SMALL)


def test_roof_gable_still_builds_a_roof_with_no_slopes_in_the_bin():
    inv = bin_of(NO_SLOPES)
    res = generate("roof_gable", Allocator(inv), 4, sub="roof", length=8, width=6)
    assert res is not None
    assert validate(as_build(res), inv).ok
    assert not {p.part for p in res.parts} & {"3038", "3039", "3040b"}


def test_cockpit_still_builds_a_nose_with_no_slopes_in_the_bin():
    inv = bin_of(NO_SLOPES)
    res = generate("cockpit", Allocator(inv), 4, sub="nose", length=6, width=4)
    assert res is not None
    assert validate(as_build(res), inv).ok


# ---------------------------------------------------------------- 4. regressions


def test_a_slope_is_as_long_as_its_long_axis():
    """Regression. A 2x1 slope is ONE stud along the ridge and two across the pitch. Reading
    its length as max(w, d) made the roof skip every other stud and left holes in the pitch."""
    assert (meta.get("3040b").w, meta.get("3040b").d) == (1, 2)
    inv = bin_of([p for p in NO_SLOPES] + ["3040b"])
    res = generate("roof_gable", Allocator(inv), 4, sub="roof", length=3, width=6)
    assert res is not None
    # Width 6 gives two courses, each with a band of slopes down either pitch, and each band
    # is three 1-stud slopes long. Reading the slope as 2 long leaves a stud over at the end of
    # every band, the band falls back to plain bricks, and the count collapses.
    assert sum(1 for p in res.parts if p.part == "3040b") == 2 * 2 * 3
    assert validate(as_build(res), inv).ok


def test_leg_ties_do_not_land_on_top_of_each_other():
    """Regression. A tie reaching from one leg's START to the next leg's END overlapped its
    neighbour by two studs -- two bricks in one place, which is not a model."""
    inv = bin_of(RICH)
    res = generate("legs", Allocator(inv), 4, sub="legs", count=5, height=9)
    assert res is not None
    report = validate(as_build(res), inv)
    assert not [e for e in report.errors if e.code == "OVERLAP"], \
        [e.human for e in report.errors]


def test_a_wing_is_one_object_not_a_stack_of_slats():
    """Regression. Both layers paired their rows the same way, so a 2x10 and a 2x2 that met on
    a clean line stayed two separate pieces. Parts side by side in a layer do not connect."""
    inv = bin_of(RICH)
    for span, depth in ((12, 3), (14, 6), (10, 4), (7, 2)):
        res = generate("wing", Allocator(inv), 4, sub="wing", span=span, depth=depth)
        assert res is not None
        report = validate(as_build(res), inv)
        assert not [e for e in report.errors if e.code == "DISCONNECTED"], \
            f"wing({span},{depth}): " + str([e.human for e in report.errors])


def test_a_one_course_turret_is_still_one_object():
    """Regression. A ring's four walls are tied together by the course above them, so the
    shortest possible turret needs its plate cap or it is four loose walls."""
    inv = bin_of(RICH)
    res = generate("turret", Allocator(inv), 4, sub="t", radius=2, height=3)
    assert res is not None
    assert validate(as_build(res), inv).ok


def test_a_cockpit_course_bridges_the_one_below_it():
    """Regression. Parity was counted per course instead of from the course's own z origin, so
    an inset course landed exactly on the seams below it and the nose split into stripes."""
    inv = bin_of(RICH)
    res = generate("cockpit", Allocator(inv), 4, sub="nose", length=8, width=6)
    assert res is not None
    assert validate(as_build(res), inv).ok


def test_fence_rail_lands_on_pickets_even_when_the_run_is_odd():
    inv = bin_of(RICH)
    for length in (1, 5, 7, 9, 11):
        res = generate("fence", Allocator(inv), 4, sub="f", length=length, height=6)
        assert res is not None, length
        assert validate(as_build(res), inv).ok, length


def test_a_neck_cannot_lean_itself_off_its_own_base():
    """A course stepped two studs sideways shares no studs with the one below it. The lean is
    clamped rather than trusted, because the LLM picks this number."""
    inv = bin_of(RICH)
    for lean in (-5, -1, 0, 1, 5):
        res = generate("neck", Allocator(inv), 4, sub="n", height=12, lean=lean)
        assert res is not None, lean
        assert validate(as_build(res), inv).ok, lean


# ---------------------------------------------------------------- 5. in a whole model


def test_a_cottage_composes_and_validates():
    inv = bin_of(RICH)
    build, report, notes = compose(Composition("slab", [
        {"id": "slab", "gen": "slab", "args": {"length": 8, "width": 6, "height": 1}},
        {"id": "walls", "gen": "cabin", "attach_to": "slab",
         "args": {"length": 8, "width": 6, "height": 6}},
        {"id": "roof", "gen": "roof_gable", "attach_to": "walls",
         "args": {"length": 8, "width": 6}},
    ]), inv, name="Cottage")
    assert report.ok, [e.human for e in report.errors]
    assert {p.sub for p in build.parts} == {"slab", "walls", "roof"}
    assert any(p.part in ("3038", "3039", "3040b") for p in build.parts), \
        "the roof should be pitched, not flat"


def test_a_flyer_composes_and_validates():
    inv = bin_of(RICH)
    build, report, notes = compose(Composition("chassis", [
        {"id": "chassis", "gen": "chassis", "args": {"length": 10, "width": 4}},
        {"id": "nose", "gen": "cockpit", "attach_to": "chassis", "at": "top_front",
         "args": {"length": 4, "width": 4}},
    ]), inv, name="Flyer")
    assert report.ok, [e.human for e in report.errors]
    for (part, color), used in build.counts.items():
        assert used <= inv.qty(part, color)
