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

### Found while integrating (for Lane B)
- [ ] `/api/edit` returns an empty tape; the UI shows a one-line summary instead.
- [ ] With a tighter bin, "a small truck" came back invalid with
      "Two parts occupy the same space at (0, -1, 0)" (generator overlap?).
- [ ] With a sparse bin, house/jet failed on single missing elements the
      substitution rung didn't cover (e.g. 1x2 tan, 2x2 plate white).

## Lane A (CV) - owned by a teammate
The app's inventory screen consumes `{part, color, count, confidence, crop,
alternatives}` per detection (see `web/src/lib/types.ts`).

---

# CV lane (vision/) — measured results

## THE SURFACE IS THE WHOLE BALLGAME (measured 2026-09-19)

Three conditions, same bricks, same phone:

| condition | detections | named | unknown |
|---|---|---|---|
| blanket / pegboard, full-res | 1296 | 641 | **51%** |
| plain table, chat-compressed | 266 | 124 | **53%** |
| **plain table, full-res** | 270 | 218 | **19%** |

Two independent failures, each fixed by one change:

1. **Patterned surfaces manufacture bricks.** Hand-labelling all 1,296 crops from the blanket and
   pegboard photos showed **43% were not bricks at all** — woven motif and pegboard slots segment
   as perfect brick-sized blobs, and the classifier answers "Bread / Baguette" (x282) and
   "Technic Axle 2L" (x179). On a plain table that drops to roughly zero.
2. **Compressed images starve the classifier.** A chat-compressed 924x2000 copy yields 91px crops
   (46 of 73 under 100px) and Brickognize returns NOTHING for 47% of them. The 1848x4000 original
   yields 187px crops and that failure disappears.

**So: shoot on a plain surface, and use the original file.** Together they take unknown from 51%
to 19% with no model change at all.

### Then a retry ladder took it to 13%

Of the 19% remaining on good photos: **80% named and placeable · 14% the API returned NOTHING ·
6% named but genuinely unplaceable** (dragon head, minifig cape, lattice pane — our grid model
legitimately cannot place those, so refusing is the correct answer, not a failure).

Looking at the 14%: they are REAL parts, mostly shot at an oblique angle or specialty shapes.
Crop size was not the cause (160px vs 167px for successes). Brickognize's API notes that multiple
views of an item improve accuracy, so `RETRY_VARIANTS` retries only the crops that returned
nothing, with rot90 / unmasked / rot180 / pad40. Measured: **56% of them recover an answer, 44%
become placeable**, and no single variant dominates (rot90 x4, unmasked x3, rot180 x1, pad40 x1)
which is why it is a ladder rather than a better default.

Unknown: **19% -> 13%.** Four extra API calls per failing crop, no training.

## The collection tracker — `vision/store.py`

A scan is a moment; a COLLECTION is what you own. The store keeps them apart:

| promise | guarded by |
|---|---|
| Re-shooting the same pile does not double your bricks | `test_rescanning_the_same_pile_does_not_double_your_bricks` |
| A correction sticks, and applies to every FUTURE scan | `test_a_correction_sticks_and_applies_to_future_scans` |
| Bricks in a build are still owned, just not available | `test_reserving_a_build_removes_bricks_from_available_but_not_from_owned` |
| Taking a build apart returns them | `test_taking_a_build_apart_returns_its_bricks` |
| Availability never goes negative | `test_availability_never_goes_negative` |
| Every change is recorded with its cause | `test_every_change_is_recorded` |

Running on the real collection:

```
owned 641 · available 641 · 261 elements · 102 distinct parts · 79x brick 2x4
build a rover from AVAILABLE bricks -> 25 parts, valid
reserve  -> owned 641, available 616, reserved 25
release  -> available 641
```

The overcount direction is the dangerous one: an inflated collection produces instructions for
bricks that do not exist, while an undercount is fixed by scanning again. So when the duplicate
detector is unsure, the store keeps the SMALLER interpretation and says so.

## Real-bricks results (measured 2026-09-19 on James's 9 photos)

| | |
|---|---|
| segmentation on a patterned blanket, oblique | 74 clean detections on photo 1; SAM 2 + shape filter |
| **full-resolution crops** (was cropping the 1600px downscale) | unknown **64/74 -> 17/74**, identified 10 -> 57 |
| 9 photos merged | 1,296 pieces · 261 part+colour combos · **102 distinct parts** · 79x brick 2x4 |
| "a little rover" | **25 parts, 7 steps, valid on the first attempt** |
| "a small house" / "a tower" | 23 / 28 parts, both valid |
| manual | real PDF + step PNGs from the real build |

### The long-tail fix, which was the whole point of this round

A real bin is almost all quantity-one: 57 identified pieces across **49** part+colour combos, but
only **29** distinct parts ignoring colour — with twelve brick 2x4s. Two changes followed:

1. **Colour pooling** (`core/alloc.py`) — `take_color()` satisfies a request from any colour of
   that part, honouring Contract 1's per-row `color_mode`, and records every substitution with
   UI-ready copy ("used blue instead of red — you had no red 2x4").
2. **Degrade instead of refuse** (`_lay_best` / `_row_best` / `_Ledger.row|rect`) — generators now
   build the largest rectangle the bin can cover and report the size they managed, instead of
   returning `None` on any shortfall.

Rover on one photo's bin: **3 parts -> 8 -> 12**. Generators producing parts: **8/15 -> 10/15**.

## Is there anything to TRAIN? No — checked properly, 2026-09-19

The measured weakness is false positives (SAM boxing studs, baseplate texture, carpet). A
brick/not-brick filter is the obvious fix, and auto-labelling every SAM detection against the
ground-truth boxes we already have yields **~5,400 positive and ~700 negative crops** — enough to
train a small CNN, no photographs needed.

I tried the cheap thing first. **Four arithmetic comparisons** (area relative to the photo's median
detection, aspect ratio, solidity, bbox fill) match what that CNN would do, fitted on 8 photos and
validated on 10 **held-out** ones:

| `VISION_SHAPE_FILTER` | recall | precision |
|---|---|---|
| `0` (default) | **0.88** | 0.89 |
| `1` | 0.82 | **0.98** |

86% of false positives removed for 6% of true bricks. Left **off by default**: it was fitted on
one dataset of small Technic parts on white, and trading recall for precision is a product call to
make against OUR photos. Turn it on and re-measure once they exist.

**So: no GPU training is worth doing.** Not because training is hard, but because the cheap thing
won on held-out data, and it has no model to train, host or keep in sync.

## The real photos arrived, and a third of every scan was the blanket — 2026-09-19

Segmenting the user's own 9 phone photos gave **1,296 crops. 562 of them (43%) are not LEGO.**
They are the surface underneath: a woven blanket in six photos, the oval slots of a white
pegboard in the other three. They pass the shape gate (solidity 0.96, plausible area), and
Brickognize — which never returns nothing and never scores below 0.50 — calls them
"4342 Bread/Baguette" (×282) or "3704 Technic Axle 2L" (×179). **479 of the 562 resolved to a
placeable part**, i.e. phantom bricks in the inventory, each one also costing an API call.

**All 1,296 crops were then labelled by eye** (`data/real/crop_labels.json`): 730 brick,
562 not_brick, **4 unsure**. An earlier pass had tuned against a proxy ("the classifier said 4342
or 3704, so it must be blanket"), which is circular. Scored against the real labels the proxy
turns out to be perfectly precise (461/461) but to **miss 101 of the 562 artefacts** — a filter
tuned to reproduce it would have been taught to keep those 101.

`vision/brickness.py` is a 12-feature logistic regression on the crop (saturation spread, sharpness,
internal straight-line length, stud circles, geometry), 0.9 ms per crop. **Held out by whole
photo** — never by crop, because hundreds of the artefacts are near-duplicates within a photo:

| `VISION_BRICKNESS` | real bricks lost | phantoms kept | brick P / R | not_brick P / R |
|---|---|---|---|---|
| `0` (default) | 0 / 730 | 562 / 562 | — | — |
| `1` (thr 0.20) | **9 (1.2%)** | **31 (5.5%)** | 0.959 / 0.988 | 0.983 / 0.945 |

The threshold sits below the balanced point on purpose: a discarded brick is a piece the user owns
and cannot get back, a kept phantom is one wasted call and one visible wrong row.

**What it does not do.** Held out by artefact FAMILY instead of by photo — train on two surfaces,
test on a third never seen — it removes 0.94 of unseen pegboard and 0.91 of unseen blanket, but
only **0.04 of unseen pale towel fabric**. And the 9 bricks it does lose are all light grey, white
or black. It has learned these two surfaces, not "LEGO". **Off by default** for exactly that
reason; `.venv/bin/python scripts/fit_brickness.py` reprints every number above.

## Not built yet

| | Owner lane |
|---|---|
| **Your real-photo baseline (needs the photos)** | A ← the only CV item left |
| Frontend: viewer, inventory UI, manual pages | C |
| `recall` (OMR) backend | B — blocked, see below |

## Gaps the agents reported honestly (do not rediscover these)

- **The real Anthropic provider has still never executed.** `anthropic` 1.7.0 is now INSTALLED,
  but there is no `ANTHROPIC_API_KEY` in this environment, so the live call remains written-but-unrun.
  The stub path is tested and everything works without a key. **This is the single highest-risk
  untested path — run one live `propose_build` the moment you have a key.**
- ~~Builds are not byte-reproducible.~~ **FIXED** — `compose()` now calls `reset_ids()`, so the
  same composition + inventory produces a byte-identical Build, part ids included. Verified.
- **Generators take no `seed`**, so "try another" cannot yet produce a different result from the
  same args.
- **`asyncio.create_task` + `fastapi.TestClient` never completes the job** (works fine under real
  uvicorn — verified). Don't chase it; test the API with a live server.
- `POST /inventory/import-set` returns 501 — no Rebrickable client.
- Store is in-memory: restarting the server loses sessions and builds.
- **LDraw OMR is unreachable** — every direct `.mpd` link 404s and the site is a JS app. The
  `recall` backend and step-order validation against real sets are blocked on finding a download path.

## CV numbers (measured 2026-09-19, on REAL photos)

| run | n | recall | precision |
|---|---|---|---|
| opencv, real photos | 20 | 0.47 | 0.46 |
| **sam 2, real photos** | 40 | **0.92** | **0.82** |
| synthetic piles (varied bg/colour/noise) | 4 | 0.86 | 0.88 |
| colour, real photos, high-confidence only | 723 | 0.703 | — |

**SAM 2 is the default** when `SAM2_CHECKPOINT` is set; opencv is the automatic fallback and is
never deleted. Installed and working: torch 2.14 on MPS, `sam2.1_hiera_small`, ~10 s/image.

**SETTLED BY RESEARCH: nobody segments a heap.** Brickit instructs users to spread into a
"one-brick-thick layer"; every sorting machine separates bricks mechanically before the camera;
Brickognize's API is documented as single-item. Single-layer capture is the industry-standard
operating condition, not our compromise. Say it on stage.

**BIGGEST ENGINEERING FINDING: heaped piles break both backends.** An annotated dataset said SAM 2 scored 0.92.
One unlabelled Wikimedia photo of a real heap showed 82 masks for ~14 bricks — it had boxed every
individual stud. Containment suppression cut that to 34 and improved scattered precision (0.82 →
0.88), but 34 for 14 is still wrong. **Spreading bricks out is load-bearing, not a nicety** — the
capture UX must insist on a single layer with gaps, and heaped-pile support is a stated limit.

Four findings, all of which required REAL photos and were invisible to synthetic data:
- **per-component watershed seeding** — a global `0.45*dist.max()` let one big brick suppress
  every small brick's seed: opencv real recall **0.149 → 0.462**
- **SAM 2 nearly doubles opencv** on both recall and precision (0.47/0.46 → 0.92/0.82)
- **grey-world white balance** — real-photo colour confusions were all warm shifts
  (Black→Dark Brown, Grey→Medium Nougat): high-confidence colour accuracy **0.605 → 0.703**
- **containment suppression** — IoU-based NMS cannot drop a stud mask inside a brick mask
  (IoU ≈ 0.02). Testing containment instead: heaped 82 → 34 masks, scattered precision 0.82 → 0.88

## Facts established during the spike (do not re-derive these)

- **A brick's LDraw origin is the centre of its TOP face**, body spanning `y ∈ [0, +24]` downward.
  Verified against the real `3001.dat`. The earlier docs said "bottom face" — that was wrong and is
  now corrected everywhere.
- **bricknet keys are exact official LDraw filenames.** Plate 1×2 is `3023b`; `3023.dat` does not
  exist. The alias table has one entry — do not rely on it.
- **bricknet's `graph.parse_ldr` works with no mesh download** (61 parts → 136 edges on their
  sample), so it is usable as an independent cross-check of our geometry. It is wired into the
  test suite as exactly that.
- **A row of 1×N parts side by side is not connected.** Physically true; the validator enforces it.
  This is why `core/alloc.py` bridges rows with 2-wide parts.
- **Nothing attaches on top of a tile.** Tiles have no studs.
- **`library.ldraw.org` 403s urllib's default User-Agent.** Send a real UA; same wall exists on
  rebrickable.com/downloads, where a browser download is the fallback.
- **Brickognize returns BrickLink part ids, not LDraw filenames.** `3023` → `3023b`, `3040` →
  `3040b`, `3068` → `3068b`. Without `vision/resolve.py` the commonest parts silently become
  unplaceable and vanish from the inventory — nothing errors. Measured, not assumed.
- **The `a` variant is usually the old/special mould, `b` the plain modern one.** `3023a` is
  "plate 1×2 with flat pin". Resolve by plainest name, never alphabetically.
- **Every Brickognize `predict/*` endpoint is `deprecated: true`** in its live spec. Cache from
  call one; we do.
- **No online LEGO dataset has HEAPED bricks.** Measured: 1.59% of brick pairs overlap in the two
  best real-photo sets. Our watershed stage splits *touching* bricks and nothing online tests it.
- **The eval matches on bounding boxes, not masks.** Label boxes; polygons are discarded.
- **`data/external/` is CC BY-NC-ND** — evaluate locally, never commit or redistribute. Gitignored.
- **Slopes and round parts get box-shaped occupancy.** Conservative: refuses legal placements,
  never accepts illegal ones. `PartMeta.shape` is there to refine it later.

## Gates

| T+ | Gate | State |
|---|---|---|
| 1 | contracts + fixtures committed | ✅ **done ahead of time** |
| 4 | hand-written build → `.ldr` renders with edge lines | ⬜ (backend half done; viewer not started) |
| 8 | validator passes its tests; inventory typed + imported | ✅ **validator done**, import not started |
| 14 | a 40-piece build browses as a correct manual | ⬜ |
| 20 | prompt → validated build → manual, end to end | ⬜ (everything but the LLM layer exists) |
| 26 | photo → build → edit → manual → PDF | ⬜ |
| 28 | **feature freeze** | ⬜ |
| 30 | demo-safe mode verified offline | ⬜ |
| 34 | submitted | ⬜ |

## Known rough edges

- `WEAK_BOND` fires at 50% on the demo rover. The allocator's stagger logic is weak when one part
  spans the full width. Cosmetic (warning only) but worth 20 minutes.
- `core/compose.py` anchor names (`top_front`, `top_rear`…) are coarse — fractions of the parent
  footprint, not real semantics.
- No `sculpt` or `recall` backend yet, so "build me a dog" has nowhere to go.
- Generators cover vehicles and boxes. Nothing organic, nothing with wheels attached.

## Cut list

_(nothing cut yet)_
