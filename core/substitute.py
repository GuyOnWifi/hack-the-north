"""Part substitution: covering one part you do not own with several you do.

WHY this exists. Measured on the user's real bin: 74 detections -> 57 pieces across 49 distinct
part+colour combinations. Almost everything is quantity ONE. Our generators were written against
a tub of identical bricks, so "build me a rover" collapsed to three parts. Colour pooling
(`core.alloc`) recovers most of it; this module recovers the rest, by letting a design that wants
a brick 1x4 accept two brick 1x2 instead.

The rules are DATA, not code. Three compact tables below expand into `RULES`, and every rule is
checked against `core.meta` by the test suite: the children must tile the parent's occupancy box
exactly -- no gap, no overlap, no change in height. That check is why a rule table can be trusted
even though nobody hand-verified 60 rows of it.

INVARIANT 4 (the LLM never emits a coordinate) is the reason for the shape of the API. Offsets
live in here, keyed by a stable rule id. The model may only ever say `"3010_as_3004_3004"`; the
coordinates come out of `apply_rule`, which is ordinary code.

Offsets are on the INTEGER STUD GRID, not in LDraw units:
  dx  studs along the parent's long axis (the axis the allocator lays parts along)
  dz  studs across it
  dy  PLATES of height (a brick is 3)
and they are expressed in the parent's own rot-0 frame, which for every part in these tables has
its long axis along +X. A caller that rotates the parent rotates the children with it.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------- the tables
#
# Read these as "one of the first, when you have none, may be replaced by the rest".

# Same footprint width, split along the long axis. `(parent, left, right)`.
_LENGTH_SPLITS: tuple[tuple[str, str, str], ...] = (
    # bricks, 1 wide            1x8 1x6 1x4 1x3 1x2 1x1 = 3008 3009 3010 3622 3004 3005
    ("3008", "3010", "3010"),
    ("3008", "3009", "3004"),
    ("3009", "3010", "3004"),
    ("3009", "3622", "3622"),
    ("3010", "3004", "3004"),
    ("3010", "3622", "3005"),
    ("3622", "3004", "3005"),
    ("3004", "3005", "3005"),
    # plates, 1 wide            1x8 1x6 1x4 1x3 1x2 1x1 = 3460 3666 3710 3623 3023b 3024
    ("3460", "3710", "3710"),
    ("3460", "3666", "3023b"),
    ("3666", "3710", "3023b"),
    ("3666", "3623", "3623"),
    ("3710", "3023b", "3023b"),
    ("3710", "3623", "3024"),
    ("3623", "3023b", "3024"),
    ("3023b", "3024", "3024"),
    # tiles, 1 wide             1x4 1x3 1x2 1x1 = 2431 63864 3069b 3070b
    ("2431", "3069b", "3069b"),
    ("2431", "63864", "3070b"),
    ("63864", "3069b", "3070b"),
    ("3069b", "3070b", "3070b"),
    # bricks, 2 wide            2x10 2x8 2x6 2x4 2x3 2x2 = 3006 3007 2456 3001 3002 3003
    ("3006", "3007", "3003"),
    ("3006", "2456", "3001"),
    ("3007", "3001", "3001"),
    ("3007", "2456", "3003"),
    ("2456", "3001", "3003"),
    ("2456", "3002", "3002"),
    ("3001", "3003", "3003"),
    # No 2x3 -> 2x2 + something: the leftover is one stud wide ACROSS the run, and a rule whose
    # child has to be turned a quarter turn is a different (harder) rule than these tables model.
    # plates, 2 wide            2x10 2x8 2x6 2x4 2x3 2x2 = 3832 3034 3795 3020 3021 3022
    ("3832", "3034", "3022"),
    ("3832", "3795", "3020"),
    ("3034", "3020", "3020"),
    ("3034", "3795", "3022"),
    ("3795", "3020", "3022"),
    ("3795", "3021", "3021"),
    ("3020", "3022", "3022"),
)

# A 2-wide part replaced by two 1-wide parts of the same length, laid side by side. This is the
# rule with a real cost: two 1xN parts side by side are NOT joined to each other (the validator
# says so and it is physically true), so the course above has to tie them. Hence the penalty.
_WIDTH_SPLITS: tuple[tuple[str, str], ...] = (
    ("3007", "3008"), ("2456", "3009"), ("3001", "3010"), ("3002", "3622"), ("3003", "3004"),
    ("3034", "3460"), ("3795", "3666"), ("3020", "3710"), ("3021", "3623"), ("3022", "3023b"),
    ("3068b", "3069b"),
)

# One brick replaced by three plates of the same footprint. Same volume, same studs on top,
# two extra seams. `(brick, plate)`.
_BRICK_TO_PLATES: tuple[tuple[str, str], ...] = (
    ("3008", "3460"), ("3009", "3666"), ("3010", "3710"), ("3622", "3623"),
    ("3004", "3023b"), ("3005", "3024"),
    ("3006", "3832"), ("3007", "3034"), ("2456", "3795"),
    ("3001", "3020"), ("3002", "3021"), ("3003", "3022"),
)

# Penalties are ordinal, not physical: they only order the rules. Integers, because nothing in
# this project wants a float it does not need.
PENALTY_LENGTH = 1      # an extra seam along the run; masonry deals with it
PENALTY_PLATES = 2      # two extra seams, and three times the step count
PENALTY_WIDTH = 3       # leaves two pieces that do not touch each other: needs a tying course


@dataclass(frozen=True, slots=True)
class Child:
    """One replacement part and where it sits inside the parent's footprint."""

    part: str
    dx: int = 0
    dy: int = 0
    dz: int = 0


@dataclass(frozen=True, slots=True)
class Rule:
    """One way to replace `part` with `children`. Immutable, and identified by a stable id."""

    id: str
    part: str
    children: tuple[Child, ...]
    penalty: int
    kind: str          # length | width | height
    why: str

    @property
    def flat(self) -> bool:
        """True when no child is raised off the parent's own layer.

        Row filling can only place flat rules: `Taken` carries dx/dz and no dy, so a rule that
        stacks plates has to be applied by a caller that knows about height.
        """
        return all(c.dy == 0 for c in self.children)

    @property
    def width(self) -> int:
        """How many rows deep the replacement reaches (1 or 2)."""
        return max((c.dz for c in self.children), default=0) + 1


def _length(part: str) -> int:
    """Studs along the long axis, from metadata. Rules are only built for parts we know."""
    from . import meta as meta_mod

    m = meta_mod.get(part)
    return max(m.w, m.d)


def _build_rules() -> dict[str, Rule]:
    from . import meta as meta_mod

    out: dict[str, Rule] = {}

    def add(rule: Rule) -> None:
        if rule.id in out:
            raise ValueError(f"duplicate substitution rule id {rule.id!r}")
        out[rule.id] = rule

    for parent, a, b in _LENGTH_SPLITS:
        if not all(meta_mod.has(p) for p in (parent, a, b)):
            continue
        # Children run along the parent's long axis, so `a` starts at 0 and `b` after it.
        add(Rule(
            id=f"{parent}_as_{a}_{b}",
            part=parent,
            children=(Child(a, 0, 0, 0), Child(b, _length(a), 0, 0)),
            penalty=PENALTY_LENGTH,
            kind="length",
            why=f"use {meta_mod.get(a).name} + {meta_mod.get(b).name} end to end "
                f"instead of one {meta_mod.get(parent).name}",
        ))

    for parent, half in _WIDTH_SPLITS:
        if not all(meta_mod.has(p) for p in (parent, half)):
            continue
        add(Rule(
            id=f"{parent}_as_two_{half}",
            part=parent,
            children=(Child(half, 0, 0, 0), Child(half, 0, 0, 1)),
            penalty=PENALTY_WIDTH,
            kind="width",
            why=f"use two {meta_mod.get(half).name} side by side instead of one "
                f"{meta_mod.get(parent).name}; the course above has to tie them together",
        ))

    for brick, plate in _BRICK_TO_PLATES:
        if not all(meta_mod.has(p) for p in (brick, plate)):
            continue
        add(Rule(
            id=f"{brick}_as_three_{plate}",
            part=brick,
            children=tuple(Child(plate, 0, dy, 0) for dy in range(3)),
            penalty=PENALTY_PLATES,
            kind="height",
            why=f"stack three {meta_mod.get(plate).name} instead of one "
                f"{meta_mod.get(brick).name}",
        ))

    return out


RULES: dict[str, Rule] = _build_rules()

_BY_PART: dict[str, tuple[Rule, ...]] = {}
for _r in RULES.values():
    _BY_PART[_r.part] = _BY_PART.get(_r.part, ()) + (_r,)
# Cheapest first, then by id so the order is reproducible run to run (invariant 6).
_BY_PART = {p: tuple(sorted(rs, key=lambda r: (r.penalty, r.id))) for p, rs in _BY_PART.items()}


def rules_for(part: str, *, flat_only: bool = False, max_width: int = 2) -> tuple[Rule, ...]:
    """Every rule that replaces `part`, cheapest first.

    `flat_only` drops the brick -> three plates rules, which a caller that cannot offset in Y
    must not be handed. `max_width` drops the side-by-side rules for a 1-wide row.
    """
    rules = _BY_PART.get(part, ())
    if flat_only:
        rules = tuple(r for r in rules if r.flat)
    if max_width < 2:
        rules = tuple(r for r in rules if r.width <= max_width)
    return rules


def get_rule(rule_id: str) -> Rule:
    """Look up a rule by the id the LLM chose. Raises KeyError on an invented id, deliberately."""
    return RULES[rule_id]


def apply_rule(part: str, rule: Rule | str) -> list[tuple[str, int, int, int]]:
    """`(part, dx, dy, dz)` for each replacement child, in the parent's rot-0 frame.

    This is the only function that turns a rule id into coordinates, which is exactly the seam
    invariant 4 asks for: the model picks `rule.id`, our code produces the numbers.
    """
    r = get_rule(rule) if isinstance(rule, str) else rule
    if r.part != part:
        raise ValueError(f"rule {r.id!r} replaces {r.part!r}, not {part!r}")
    return [(c.part, c.dx, c.dy, c.dz) for c in r.children]


def catalog_text(limit: int = 0) -> str:
    """The rule catalogue as the LLM sees it: ids and prose, and not one coordinate."""
    rows = sorted(RULES.values(), key=lambda r: (r.part, r.penalty, r.id))
    if limit:
        rows = rows[:limit]
    return "\n".join(f"- {r.id} [{r.kind}, cost {r.penalty}] -- {r.why}" for r in rows)
