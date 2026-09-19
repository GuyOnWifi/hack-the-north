# Bricolage

**Build anything from the LEGO you already own.**

Photograph a pile of loose bricks. Ask for something. Get a model that uses *only* the pieces you
actually have — proven physically buildable — with a real step-by-step instruction manual.

> Generative LEGO systems exist. BrickGPT/LegoGPT makes physically-stable models from text. But
> every one of them assumes an infinite supply of bricks: BrickNet's paper lists generation
> "conditioned on a specified part set" as *future work*. **Nobody generates builds constrained to
> the bricks you own.** That constraint is the whole problem, and it's what this does.

## The idea

**The LLM decides *what* to build. It never places a brick.**

Builds live on an integer grid — X/Z in studs, Y in plate heights, rotations in 90° steps. A
deterministic validator (ordinary code, *not* a model) checks overlap, support, connectivity,
insertability and inventory. The LLM only emits *choices*: which generator, which argument, which
substitution. Coordinates are computed by us.

The designer is creative and unreliable. The inspector is dumb and infallible. The loop between
them is where the reliability comes from.

## Status

Working and tested:

| | |
|---|---|
| `core/geom.py` | grid ↔ LDraw conversion, the only place floats exist |
| `core/model.py` | frozen `Build` / `Placed` / `Inventory` types |
| `core/meta.py` | part metadata for **8,455 parts**, derived from bricknet's connector table |
| `core/validate.py` | overlap · support · connectivity · inventory · seam-bond |
| `core/alloc.py` | inventory-constrained allocation with graceful degradation |
| `core/generators/` | 7 parametric subassembly generators |
| `core/compose.py` | generator tree → placed, collision-checked, validated build |
| `core/sequence.py` | step ordering with the insertion-sweep check |
| `core/ldraw.py` | `.ldr` export with `0 STEP` markers |
| `tests/` | 22 tests, including a cross-check against an independent LDraw implementation |

Not built yet: the LLM layer, the repair loop, the CV pipeline, the frontend. See `STATUS.md`.

## Quickstart

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest tests/ -q          # 22 passed
.venv/bin/python scripts/make_fixtures.py     # regenerate fixtures/
.venv/bin/python scripts/build_whitelist.py   # rebuild data/core_parts.json
```

```python
from core.compose import Composition, compose
from core.model import Inventory
from core.sequence import sequence
from core.ldraw import to_ldraw

inv = Inventory.from_pairs([("3001", 4, 8), ("3003", 4, 10), ("3023b", 15, 12)])
build, report, notes = compose(Composition("chassis", [
    {"id": "chassis", "gen": "chassis", "args": {"length": 10, "width": 4}},
    {"id": "cabin", "gen": "cabin", "attach_to": "chassis", "at": "top_rear"},
]), inv, name="Desk Rover")

print(report.ok, report.stats)
open("rover.ldr", "w").write(to_ldraw(build, sequence(build)))
```

Every error carries a `human` string that is both UI copy and the text fed back to the repair loop:

```
Needs 4x brick 2x4 in colour 4; you have 1. You have 6 in other colours.
brick 1x4 'p0013' floats at plate layer 4 with nothing under it.
3 part(s) in cabin form a separate piece that does not attach to the main model.
```

## Verified facts worth knowing

- **A brick's LDraw origin is the centre of its TOP face**, body spanning `y ∈ [0, +24]` downward
  (−Y is up). Checked against the real `3001.dat`. Getting this backwards inverts every model.
- **bricknet's keys are exact official LDraw filenames.** Plate 1×2 is `3023b`; `3023.dat` does
  not exist. There is no useful alias table — use the real filename.
- **A row of 1×N parts side by side is not connected.** Layers must cross-bind with 2-wide parts.
  The validator enforces this, which is why `core/alloc.py` prefers 2-wide moulds.
- **Nothing attaches on top of a tile.** Tiles have no studs; footprint overlap is not a join.

## Docs

`CONTEXT.md` is the self-contained project context — glossary, invariants, contracts. Start there.
`PLAN.md` indexes the rest; `docs/07-tooling-decisions.md` records what we adopted and rejected,
and why.

## Credits

See `CREDITS.md`. LEGO® is a trademark of the LEGO Group, which does not sponsor, authorize or
endorse this project.
