# 02 — 36-hour plan (2–3 people)

Build order follows one rule: **the grid model and validator exist before anything that produces a
build.** Everything downstream is a consumer of a type that is already trustworthy.

```
1. grid model + validator + LDraw export + render a HAND-WRITTEN build
2. instruction generator (ordering, insertion sweep, cameras, manual page)
3. parametric generators + LLM tool calls + the fix loop
4. natural-language editing (subtree replacement)
5. photo recognition                       ← last on purpose; type the inventory until then
```

Recognition is last **on purpose**: you can type an inventory until everything else works, and CV
is the least predictable hour-per-hour investment in the project. It is still a *parallel lane*
owned by one person from hour 8, because "use your spare bricks" is the pitch — it just must never
block the critical path.

---

## Before the event (the legal kind of prep)

Check Hack the North's rules — hackathons generally require the **project code** to be written
during the event, while these are fine and worth doing:

- [ ] Create accounts + API keys: Anthropic (and OpenAI if you're chasing that prize), Vercel, Neon/Supabase, R2/S3, Sentry, Rebrickable (free API key)
- [ ] **Download the data** (it's data, not code, and it's ~1GB you do not want to pull over conference wifi):
      LDraw `complete.zip`, the OMR archive, Rebrickable's bulk CSVs
- [ ] Read, don't write: the three.js `webgl_loader_ldraw` example, `packLDrawModel`, the LDraw
      file-format spec, Brickognize's OpenAPI page (`api.brickognize.com/docs`)
- [ ] **Bring bricks.** A real bin of loose LEGO on the judging table is worth more than any slide.
      Also bring: a white sheet of paper (your photo background), a printed scale card, a tripod or
      phone stand, and a long HDMI/USB-C adapter.
- [ ] Print 20 copies of the scale card.
- [ ] Verify one LDraw fact by hand so nobody argues about it at 3am: write a 2-brick `.ldr`, open it
      in a viewer, confirm that stacking means **y −= 24** and that a brick's origin is its TOP face
      (body spans y ∈ [0, +24]). Already verified in `core/geom.py`; re-check if anything looks upside down.

---

## Lanes

| Lane | Owner | Owns |
|---|---|---|
| **CORE** | strongest systems person | grid model, part metadata, validator, generators, substitution, sequencer, LDraw I/O |
| **RENDER** | strongest frontend/3D person | both render looks, step viewer, manual pages, PDF, inventory UI |
| **AGENT** | third person (or CORE, if two) | LLM tools, fix loop, SSE tape, then photo recognition |

**Two people?** Merge AGENT into CORE, RENDER takes the inventory UI, and cut `sculpt` and the
camera-scoring pass on day one rather than at hour 30.

---

## Hour by hour

Clock assumes a Friday 22:00 start. Adjust the wall times, keep the T+ offsets.

### T+0 → T+4 · Fri 22:00–02:00 — foundations

| Lane | Work |
|---|---|
| CORE | repo scaffold; `core/model.py` (frozen dataclasses); `scripts/build_part_meta.py` over the whitelist; **hand-verify the metadata table in a spreadsheet** |
| RENDER | Next.js up, deployed to Vercel in the first hour (deploy early, deploy often); `LDrawLoader` rendering a hard-coded `.ldr` with edge lines |
| AGENT | data ingest: Rebrickable CSVs → SQLite catalog; `LDConfig.ldr` → colour table; Brickognize smoke test on 5 hand-cropped photos |

**GATE A (T+4):** a hand-written `Build` → `.ldr` → renders in the browser with black edge lines.
*If not: everyone stops and fixes this. Nothing else matters yet.*

### T+4 → T+8 · 02:00–06:00 — the law

| Lane | Work |
|---|---|
| CORE | `core/validate.py`: overlap, support, connected, budget + the structured `Report` with `human` strings. **Write the 4 unit tests now**, not later |
| RENDER | step slider using `userData.buildingStep`; the two render setups split (manual look vs display look); pale-blue ground |
| AGENT | inventory model + typed-entry API + `import-set` from the CSVs; seed script for the canned 500-piece bin |

**GATE B (T+8):** validator catches all three bad builds and passes the good one. Inventory can be
typed in and imported from a set number.

> **Sleep rotation starts here.** Stagger it: one person down 06:00–10:00, next 10:00–14:00.
> Nobody pulls 36 straight — the 4am code is the code you delete at noon.

### T+8 → T+14 · 06:00–12:00 — instructions

| Lane | Work |
|---|---|
| CORE | `core/sequence.py`: topological order + **insertion sweep** + step grouping (1–6, prefer identical parts); subassembly callout ordering |
| RENDER | the manual page: big step number, parts panel with `2×` counts, page nav, drop-in animation; fixed isometric camera for now |
| AGENT | **photo lane starts**: OpenCV segmentation on a controlled background; per-crop Brickognize calls with a SHA-256 cache |

**GATE C (T+14):** a hand-written 40-piece build produces a browsable, correct, good-looking
step-by-step manual. **This is the demo floor — from here the project always has something to show.**

### T+14 → T+20 · 12:00–18:00 — generation

| Lane | Work |
|---|---|
| CORE | 6–8 parametric generators (`chassis`, `cabin`, `axle_pair`, `wing`, `tower`, `wall`, `roof`, `slab`) + the attachment-point contract + `core/substitute.py` rules |
| RENDER | inventory UI with confidence chips, evidence panel, alternatives; hero display-look viewer |
| AGENT | LLM tool defs (`propose_build`, `edit_subassembly`, `swap_part`); the **fix loop** with the deterministic rungs first; SSE agent tape |

**GATE D (T+20):** `"build me a rover"` + a typed inventory → a validated build → a real manual.
**End to end, no photos.** *If you are behind here, cut `sculpt` and the camera scoring now and say
so out loud — decide it awake at 6pm, not asleep at 4am.*

### T+20 → T+26 · 18:00–00:00 — the differentiators

| Lane | Work |
|---|---|
| CORE | `sculpt` backend: layer parser + greedy tiler with restarts + seam staggering |
| RENDER | PDF export; camera scoring via the ID buffer; arrows for ambiguous placements |
| AGENT | **edit loop**: "make the chassis longer" → subtree replacement → ghost-out/drop-in animation; confirm-loop anchoring (one correction fixes many rows) |

**GATE E (T+26):** photo → inventory → build → edit → manual → PDF. The whole story, once, live.

### T+26 → T+30 · 00:00–04:00 — harden

- **Feature freeze at T+28.** Anything not working at 28 does not exist.
- Build **demo-safe mode** (`DEMO_SAFE=1`): canned session, pre-generated build, cached renders,
  zero network. This is not optional — plan for the wifi to fail during judging, because it will.
- Run the golden-prompt set (10 prompts × backends) and fix only what it breaks.
- Empty states, error states, loading states. Every spinner needs an exit.
- **Actually build one of the generated models out of real bricks.** If it stands up, you get to say
  so while holding it. That one sentence beats every slide you could make.

### T+30 → T+34 · 04:00–08:00 — the demo is a deliverable

- Write and **rehearse the 3-minute script out loud, four times, on the real machine** (see
  `03-prizes-and-demo.md`). Time it. It will be 4:30 the first time.
- Record the 2-minute video **now**, while things work — not at T+35.
- README: problem, architecture diagram, the three loops, limits, credits, run instructions.
- Devpost draft with every sponsor prize you're eligible for.

### T+34 → T+36 · 08:00–10:00 — submit

- Submit at **T+34**, not T+36. Devpost goes down at the deadline, every single time.
- Sleep, shower, eat. Re-run the golden set once before judging.
- Have the laptop plugged in, the projector tested, demo-safe mode verified, and a bin of real
  bricks and a printed manual on the table.

---

## Risk register

| Risk | P | Impact | Mitigation | Trigger to act |
|---|---|---|---|---|
| Part metadata table has wrong rows | high | fatal — everything downstream is wrong | hand-verify all 200 rows in a spreadsheet at T+2; unit-test 10 known parts | any validator failure you can't explain |
| Brickognize is down / rate-limits / changes | med | loses the photo path only | cache by crop hash; fall back to a vision-model call with the whitelist as candidates; typed inventory always works | 2 failures in 10 calls |
| Segmentation fails on real piles | high | photo path unusable | controlled background + scale card + spread-out UX; accept fewer, higher-confidence detections; the confirm screen absorbs the rest | >40% unknown on a test photo |
| LLM proposes unbuildable things | **certain** | none — this is designed for | the fix loop's deterministic rungs; it is the feature, not the bug | — |
| three.js perf tanks on the projector | med | ugly demo | pre-baked GLB, instanced studs, cap at ~300 pieces; **test on the projector at T+26** | <30fps |
| Scope creep into Technic/hinges | med | eats the night | the whitelist is a hard boundary in `core_parts.yaml` | anyone says "it'd be cool if" after T+20 |
| Wifi dies during judging | **high** | fatal without prep | demo-safe mode, built at T+28 | — |
| Everyone awake for 36h | high | 4am code you delete at noon | staggered 4h sleeps from T+8 | — |

## Definition of done (per feature, enforce it)

1. It works from a cold start on a second machine.
2. It has an empty state and an error state.
3. It's in the demo script or it's cut.
4. It survives `DEMO_SAFE=1`.
