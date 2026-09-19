# LEGO LLM Harness — the multi-agent, layer-by-layer approach

> One of two approaches under comparison. This is the "orchestrated agents build
> bottom-up, deterministic code verifies every layer" branch. Written so it can
> be diffed against the other approach and the best of both merged.

## Goal

Prompt a general LLM (Claude, via the `claude -p` CLI — **no API key**) to design
**real, physically-buildable 3D LEGO models** from natural language ("a flower",
"a house"), render them live in a web UI, and let the user **steer** in plain
language. The LLM decides *what* to build; deterministic code lints, physics-checks,
colours, and assembles.

## The core idea (what changed from one-shot)

We started with a **one-shot** harness (one big `claude -p` call → all bricks at
once, ~130–220s, no feedback until the end, not actually multi-agent). We replaced
it with a **multi-agent, layer-by-layer** builder — both for quality *and* because
it's the [Huawei openJiuwen](../README.md) multi-agent story (Planner → Executor →
Reviewer, with real inter-agent feedback).

```
prompt
  │
  ▼
PLANNER (sonnet)      decompose object → ordered layer-bands
  │                   e.g. flower = [pot z0-1, stem z2-6, calyx z7-8, bloom z9-11]
  ▼
for each band, bottom-up:
  BUILDER (sonnet)    emit ONLY this band's bricks, given the plan + the bricks
  │                   below + an ASCII SUPPORT GRID of the layer beneath
  ▼
  INSPECTOR (code)    lint (bounds/collision) + connectivity; a mostly-broken
  │                   band goes BACK to the builder once with the errors inlined
  ▼
  stream the accumulated model to the UI  ── builds brick-by-brick on screen
  │
  ▼ (after all bands)
VISION CRITIC (opus)  render the model, LOOK at the image, score 0-10 + say
                      what's structurally wrong ("no petals, shapeless cluster")
  │
  ▼
colour by band role → force/torque + stands() check → LDraw → assemble
```

## The grammar (BrickGPT)

Every brick is one line: `hxw (x,y,z)` — footprint h×w studs, corner at (x,y,z),
`z` = integer height **layer** (z=0 is the ground). 20×20×20 grid, 1-brick-tall
bricks. Allowed footprints: `1x1 1x2 1x3 1x4 1x6 1x8 2x2 2x3 2x4 2x6 2x8`.
This is [BrickGPT / StableText2Brick](https://avalovelace1.github.io/BrickGPT/)
(Pun et al., ICCV 2025). Fewer tokens than raw LDraw, and it carries dimensions
so we can validate every placement.

## Key files

| File | Role |
|---|---|
| `bricolage/agents.py` | **the orchestrator** — planner/builder/inspector/critic loop, colouring, streaming |
| `bricolage/bricks.py` | grammar parse/lint, grid ↔ Lane-B Build ↔ LDraw |
| `bricolage/physics.py` | `analyze()` = rigorous force/torque LP; `stands()` = lenient COM+connectivity for the UI |
| `bricolage/harness.py` | the older **one-shot** builder + shared helpers (`available`, `_color_for`, `_normalize`, `_stabilize`, `_emit_geometry`) |
| `bricolage/fewshot.py` | diverse validated few-shot (real StableText2Brick rows + corbelled flower/tree/mushroom) |
| `bricolage/pipeline.py` | wires `agents.build` into the pipeline; `_finish_harness` (valid ⇢ has bricks, not stability) |
| `bricolage/server.py` | stdlib SSE API; streams tape + geometry events to the web app |
| `web/src/app/create/page.tsx` | the designing screen — skeleton, streaming 3D render, joints toggle, steer bar |
| `web/src/components/three/ModelView.tsx` | Three.js LDraw renderer + brick-by-brick assembly + joint markers |
| `web/scripts/build-ldraw-pack.mjs` | bundles the LDraw parts the harness can emit into `public/ldraw/parts.pack.ldr` |

## Hard-won lessons (the non-obvious stuff to keep when merging)

1. **`claude -p` per-call cost is dominated by the CWD.** In the repo dir it loads
   CLAUDE.md + every MCP server + skills → ~40–70s of pure overhead per call. From
   `/tmp` it's ~3–8s. `agents._claude` runs with `cwd="/tmp"`. This is what makes a
   many-small-call multi-agent loop viable at all.
2. **haiku intermittently hangs** on the complex per-band prompt (3s…>180s). **sonnet**
   is fast *and* reliable for the builder; **opus** is reserved for the vision critic
   (one call, needs the visual judgment).
3. **The rigorous force/torque LP is too strict for a UI badge** — it fails a clean
   solid house *and* a 4-leg table, because it only models vertical stud joints, not
   LEGO's horizontal plate-bonding, so any slab spanning supports "fails." We kept it
   for the joint count but the "will it stand?" badge uses `physics.stands()`:
   centre-of-mass over the base + ~everything connected to ground through the
   structure. That fixed "always shows won't stand."
4. **Don't flood-fill-to-ground at the end** — it deleted a flower's entire bloom as
   "disconnected." Keep the whole inspected shape; only drop *truly isolated* stray
   bricks (`_drop_islands`). Instability is *reported* (red), never *deleted*.
5. **Colour by band role** is the single biggest readability win: brown base, green
   stem/leaves, coloured bloom. Gray tree → red flower took the vision score 4 → 7.
6. **No silent fallbacks.** If the LLM times out / errors / returns junk, we raise a
   loud error and the UI shows it — never a canned cube. (Earlier, a silent fallback
   to a mock house was the mysterious "why is it always a cube.")
7. **Stream the SSE directly to the backend**, not through the Next dev proxy — the
   proxy buffers streaming responses so the browser saw nothing until the end.
8. **Corbel prompt rules** for wide-on-narrow (bloom on stem): planner inserts a
   "calyx" transition band; builder is told a brick may overhang its support by ≤ half
   its length. Plus a top-down **ASCII support grid** of the layer below turns "don't
   float" into "stack on the `#`s."

## What works today

- "a flower" → a **red-bloom / green-stem / brown-pot rose** that **stands**, built
  layer-by-layer, streamed brick-by-brick, vision critic ~7/10.
- Full multi-agent tape visible in the UI (Planner/Builder/Inspector/Critic).
- Stop-and-steer in natural language; joints overlay; honest red flag for genuine tippers.

## Known limits / open items

- **Speed is CLI-bound**: ~1–3 min per build, high variance (each call 3s–140s). The
  real unlocks are an **API key** (→ ~30s total) or **parallel bands** (breaks the
  brick-by-brick streaming, hurts quality — deliberately not done).
- **Bloom is a bit blocky** (vision critic's remaining note) — no distinct layered petals.
- **Symmetry** is not enforced; Agent-C research suggested build-half-and-mirror for
  balance + cleaner petals (not yet implemented).
- Physics `analyze()` returns only a boolean; no per-brick blame/margin for targeted repair.

## Ideas worth stealing from *either* approach when merging

- Speculative parallel-band build + sequential repair sweep (faster, if we can keep streaming).
- Deterministic mirror for symmetric objects (flowers, faces, vehicles).
- Vision-critic-driven **repair** (currently the critic only judges; it should feed a fix).
- Per-brick stability blame (leave-one-out on the LP) for "the weak joint is here" callouts.
- Retrieval of a close StableText2Brick example as a planning prior ("inspo").
