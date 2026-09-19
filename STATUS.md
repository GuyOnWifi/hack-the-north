# STATUS — living state

_Updated 2026-09-19._

## THE PIVOT (this is the project now)
Not "what can I build from my pile" (that's Brickit, shipped). We do what Brickit
**won't**: **invent a new model to any request and PROVE it stands up, from your
bricks.** Two hard cores make it not-a-GPT-wrapper:
- **Real physics** (`stability.py`): static-stability analysis — centre of mass
  vs. ground support polygon (topple) + per-cut stud-clutch overhang (joint rip).
  Catches builds the connectivity validator passes. (à la "Legolization", 2015.)
- **Arbitrary-shape solver** (`sculpt.py`): "build me a flower" → LLM imagines a
  voxel shape → the solver **adds support columns under overhangs**, tiles with a
  bonded 2x2 offset grid, verifies physics + inventory — **streaming every step**.
  The LLM imagines; the solver does provably-hard work; you watch it live.


## Lane B (build system) — **working end-to-end, offline**

`python bricolage/demo.py` and `python bricolage/tests.py` both run with zero
dependencies and no network.

### Done
- [x] Integer-grid model (`Build/Part/SubAssembly/Inventory`), frozen, no floats.
- [x] ~20-part whitelist metadata + colours + 7 substitution rules (`meta.py`).
- [x] `validate()` — overlap, support (per **component**, so under-slung wheels
      are grounded), connectivity, inventory; structured `Report` with `human` strings.
- [x] **4 validator unit tests** (3 bad builds, 1 good) — all pass.
- [x] Typed + sized **sockets**; 8 semantic-knob generators; masonry-bond tiler
      (seams offset in both axes so wide areas are genuinely one connected mass).
- [x] `expand()` — composition tree → placed parts; rejects bad socket
      type/size **before** placing geometry.
- [x] `sequence()` — topo order + insertion sweep + step grouping → `steps.json`.
- [x] LDraw export with `0 STEP` separators.
- [x] Heuristic-first router (compose | sculpt; recall CUT).
- [x] Deterministic mock LLM behind a provider adapter (`PROVIDER` switch).
- [x] **Repair ladder** rungs 0–2 deterministic, 3–4 LLM (mock), budget-bounded,
      logs which rung closed each error → "% closed without the model" stat.
- [x] **Edit loop** — "make the chassis longer", children reattach by socket name.
- [x] Determinism: same seed → byte-identical LDraw (replay/undo fall out of it).
- [x] `sculpt` backend (solid stepped voxel shapes, bonded layers).
- [x] Golden set: 8/8 prompts reach a valid, sequenced build.
- [x] Honest-rejection path: impossible bin degrades to a truthful message.
- [x] Fixtures for the frontend: `fixtures/{build,report,steps}.json`,
      `model.ldr`, `tape.sse`.
- [x] **Version tree** (`session.py`): build/edit/try-another/undo/redo, ops
      recorded, `replay()` byte-identical. **16/16 tests pass.**
- [x] **`claude -p` provider** (`PROVIDER=claude_cli`): uses the authenticated
      CLI as the designer, no API key; falls back to mock on any failure.
- [x] Cabin walls rebuilt from staggered 1x2 bricks (fewer parts, real bond).

### Decisions locked this session (mirror into CONTEXT.md §8)
- One-shot compose (LLM emits the whole tree; incremental only for edits).
- Ship **compose + sculpt**; **cut `recall`** (OMR grid-snap unproven, riskiest).
- **Heuristic-first router**, LLM only as tiebreak.
- Sockets are **typed + sized**; generators expose **semantic knobs** only.
- Floating is a **per-component** property, not per-part (wheels hang below).
- Flat areas need **≥2 bonded courses** — a single course of loose bricks is
  (correctly) rejected as disconnected.

- [x] **Live SSE streaming**: `GET /api/build_stream?prompt=` streams each tape
      event as it fires; the console renders it via `EventSource`.
- [x] **Partial socket rejection**: `expand(lenient=True)` keeps the model's
      valid children and drops only the impossible ones (recorded in
      `provenance.dropped`); the pipeline uses it for live LLM output.
- [x] **Richer generators**: roof `pitch=flat|hip|gable`, wing `sweep=flat|
      swept|tapered`. Fixed an id-collision bug in `bonded` (courses reused ids).
- [x] **`scripts/build_part_meta.py`**: parses real LDraw `.dat` description
      headers to auto-generate + verify the metadata table; parser unit-tested
      against a synthetic dir (works before the 80MB library is downloaded).

**25/25 tests pass.**

- [x] **Verified the metadata table against the real LDraw library** (`~/ldraw`):
      19/19 parts confirmed. The verifier follows `~Moved to` redirects
      (3023→3023b, 4073→6141, 3040→3040b) and caught exactly one real error —
      the 3040 slope was transposed (dx/dz swapped); now fixed to match LDraw.
      Colour table `~/ldraw/LDConfig.ldr` is available for accurate colours.

### Not done / next
- [ ] Keep-valid-subparts is whole-child granularity; could go finer.
- [ ] Parse `LDConfig.ldr` into `meta.COLOR_RGB` for exact colours (invariant #6).
- [ ] 3D render + PDF manual live in Lane C (frontend), against `fixtures/` + the API.

## Lane C (frontend) - `web/`, integrated with the API

See `web/README.md`. Talks to `server.py` through a Next proxy; falls back to
`fixtures/` offline.
- [x] All screens: splash, home, scan, scanning, inventory (confidence chips +
      evidence panel), build ideas, designing (live SSE tape), build detail,
      3D viewer (timeline ghosts), step-by-step manual, parts page, PDF export.
- [x] Renders `/api/ldr` via a bundled 100 KB LDraw pack (`web/public/ldraw/`).
- [x] Edit / try another / undo / redo; report `human` strings shown verbatim.
- [x] Added to Lane B's server: `POST /api/inventory` (the scanned pile becomes
      `SESSION.inv`), and `/api/ldr` now includes the `0 STEP` markers.

### Found while integrating (for Lane B) — ALL FIXED (integration/wow)
- [x] `/api/edit` empty tape → edits now run the full FIX loop with a tape
      (streams, and self-heals inventory/physics); replay still byte-identical.
- [x] "a small truck" overlap at (0,-1,0) → the shrink collapsed the chassis to
      length 2, coinciding the front/rear axle sockets. Fixed with per-arg
      minimums (length≥4) so a shrink can never produce self-overlap.
- [x] substitution gaps → added recursive rules (Plate 1x2→2×1x1, Brick
      1x2→2×1x1) so a swap bottoms out at 1x1 instead of failing mid-chain.

## Lane A (CV) - owned by a teammate
The app's inventory screen consumes `{part, color, count, confidence, crop,
alternatives}` per detection (see `web/src/lib/types.ts`).
