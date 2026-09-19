# STATUS — living state

_Updated 2026-09-19._

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

## Lanes A (CV), C (frontend) — owned by teammates
Frontend can start now against `fixtures/`.
