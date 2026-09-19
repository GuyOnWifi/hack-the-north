# CONTEXT — everything you need to work on this project

**Read this if:** you're a new teammate, or you're an LLM session starting fresh, or it's 4am and
you've forgotten why something is the way it is.

**This document is self-contained.** You can work from it without reading anything else. Everything
else in `docs/` is depth on one section of it.

---

## 1. What this is, in one paragraph

**Bricolage** takes a photo of a pile of loose LEGO bricks, works out what's in it, lets you ask for
something ("build me a rover"), designs a model that uses **only the bricks you actually own**,
proves that model is physically buildable, and generates a real step-by-step instruction manual for
it — as an interactive 3D viewer and as a printable PDF. It exists because every house with kids has
a bin of orphaned bricks with no sets and no manuals, and nothing tells you what you can build from
*that specific pile*, right now.

Built for Hack the North, 36 hours, 2–3 people.

---

## 2. The single idea everything follows from

> **The LLM decides *what* to build. It never places a brick.**

Builds live on an **integer grid**. A deterministic validator — ordinary code, not a model — checks
overlap, support, connectivity, physical insertability and inventory. The LLM only ever emits
*choices*: which generator, which argument, which substitution rule, which shape. Coordinates are
computed by our code.

This is not a stylistic preference. It's the reason the system produces structures that stand up
instead of hallucinated floating bricks, and it's the answer to almost every hard question a judge
will ask.

**Corollary, and it's the best line in the pitch:** *the verifier in this system is not a model.*
The designer is creative and unreliable; the inspector is dumb and infallible; the loop between them
is where reliability comes from.

---

## 3. Glossary — learn these, use them exactly

Domain vocabulary drift is expensive when three people and several LLM sessions are all touching the
same code. These are the words. Use them and no synonyms.

### LEGO / LDraw domain

| Term | Meaning |
|---|---|
| **stud** | The bump on top of a brick. Also our X/Z unit. 1 stud = 8 mm = 20 LDU. |
| **anti-stud** | The receiving cavity underneath a part. A connection is stud ↔ anti-stud. |
| **plate** | A thin part, ⅓ the height of a brick. Also our Y unit. 1 plate = 8 LDU = 3.2 mm. |
| **brick** | Standard height part = **3 plates** = 24 LDU. |
| **tile** | A plate with no studs on top. Nothing connects above it. |
| **LDU** | LDraw Unit, 0.4 mm. The LDraw file format's unit. **We do not use LDU in the build model** — only at export. |
| **LDraw** | The open standard for describing LEGO models as text. Our interchange format. |
| **`.dat` / `.ldr` / `.mpd`** | LDraw part file / model file / multi-part document (several models or subassemblies in one file). |
| **OMR** | LDraw **O**fficial **M**odel **R**epository — real LEGO sets published as `.mpd`, *with build steps*. Our `recall` corpus. |
| **MOC** | "My Own Creation" — a fan-designed model. Mentioned for context; we don't depend on MOC data. |
| **SNOT** | "Studs Not On Top" — building sideways. We support a couple of SNOT bricks; we don't do SNOT *techniques*. |
| **bond** | Whether vertical seams are staggered like masonry. Aligned seams = the model snaps in half. |
| **element** | A specific (part, colour) combination. "Part 3001 in colour 4" is an element. |

### Our system's vocabulary

| Term | Meaning |
|---|---|
| **Build** | The whole model: a list of placed parts + a subassembly tree. Immutable. |
| **Part** *(placed)* | One brick at one grid position: `{part, color, pos, rot, sub}`. |
| **subassembly** | A named node in the build tree — `chassis`, `cabin`, `wing`. Owns a set of parts and declares **attachment points**. |
| **attachment point** | Where a child subassembly connects to its parent. **Frozen during edits** — this is what makes "make the chassis longer" not break the cabin. |
| **generator** | A hand-written Python function that emits a valid subassembly from parameters: `chassis(length, width)`. |
| **composition** | What the LLM emits: a tree of generator calls with arguments. Never coordinates. |
| **backend** | One of three ways to get a Build: `compose` (generators), `sculpt` (voxel), `recall` (real sets). |
| **Report** | The validator's structured output — errors, warnings, stats, each with a `human` string. |
| **rung** | A level of the repair escalation ladder. Rung 0 is deterministic; rung 2 involves the LLM. |
| **the tape** | The streamed log of agent activity shown in the UI. Our best demo artifact. |
| **version** | An immutable snapshot of a Build + its Report + the op that produced it. Forms a tree. |
| **the whitelist** | The ~200 parts the solver is allowed to place. In `data/core_parts.yaml`. |
| **bin** | The user's inventory of loose bricks. The user-facing word. |

**Do not say:** "voxel" for a placed part (voxels are cells, parts occupy cells) · "model" for both
the LLM and the LEGO build (say **the LLM** and **the build**) · "piece" and "part" interchangeably
in code (in code it's always `part`).

---

## 4. Invariants — violating any of these is a bug, not a tradeoff

1. **No floats in the build model.** `pos` is integer `[x, y, z]`; `rot ∈ {0, 90, 180, 270}`.
   Floats exist only inside `ldraw/write.py`.
2. **Every mutation goes through `validate()`.** Generators, LLM edits, substitutions, manual UI
   edits — one function, no exceptions, no "this path is safe".
3. **Nothing mutates a Build in place.** Every operation is `Build -> Build` and produces a new version.
4. **The LLM never emits a coordinate.** If a prompt asks for `x, y, z`, it's wrong.
5. **`part` is always an LDraw part number.** Not Rebrickable, not BrickLink. One key everywhere.
6. **Colour is computed, never learned and never guessed by the LLM.** Median LAB → nearest of ~40
   common colours.
7. **The classical CV path is never deleted.** The trained model is an alternative behind the same
   interface, selected by env var.
8. **Every loop has a budget and a degradation path.** Nothing spins forever; nothing shows a
   spinner with no exit.
9. **Every generator and tiler takes an explicit `seed`.** Same inputs + same seed = byte-identical
   output. Undo, replay and "try another" all depend on this.
10. **The inventory grid is always editable.** The AI never blocks the user from fixing their own data.

---

## 5. Domain cheat-sheet (the numbers you'll look up twenty times)

```
1 LDU          = 0.4 mm
1 stud (X/Z)   = 20 LDU  = 8 mm
1 plate (Y)    =  8 LDU  = 3.2 mm
1 brick        = 3 plates = 24 LDU
−Y IS UP.  Stacking a brick means y_ldu -= 24.
A standard brick's origin is the CENTRE OF ITS TOP FACE; its body spans y ∈ [0, +24] (downward).
  VERIFIED 2026 against the real library file. 3001.dat contains
      4 16 -40 0 -20  -40 24 -20  40 24 -20  40 0 -20
  so the body runs from y=0 to y=24, and since −Y is up, y=0 is the TOP.
  bricknet agrees: studs sit at y=0, anti-studs at y=24.
  (An earlier draft of this document said "bottom face, y ∈ [−24, 0]". That was wrong.)
```

LDraw line type 1 (a part reference):
```
1 <colour> <x> <y> <z> <a> <b> <c> <d> <e> <f> <g> <h> <i> <part>.dat
      matrix [a b c; d e f; g h i] applied BEFORE the translation
      identity      = 1 0 0 0 1 0 0 0 1
      90° about Y   = 0 0 -1 0 1 0 1 0 0
`0 STEP` on its own line ends a build step — LDrawLoader reads this natively.
```

Part numbers you'll type by hand:
```
3001 Brick 2x4    3003 Brick 2x2    3004 Brick 1x2    3005 Brick 1x1    3010 Brick 1x4
3020 Plate 2x4    3022 Plate 2x2    3023 Plate 1x2    3024 Plate 1x1
3068b Tile 2x2    3069b Tile 1x2    3040 Slope 45 2x1  3039 Slope 45 2x2
```

Colour codes (parse `LDConfig.ldr` for the real table — these are just for debugging):
```
0 black · 1 blue · 2 green · 4 red · 14 yellow · 15 white
71 light bluish gray · 72 dark bluish gray · 70 reddish brown · 19 tan · 25 orange
```

---

## 6. System map

```
 ┌── LANE A: CV ──────────────┐   ┌── LANE B: build system ─────────┐   ┌── LANE C: frontend ──┐
 │ photo                      │   │ prompt + inventory summary      │   │ /capture             │
 │  → segment  (OpenCV | model)│   │  → router → backend            │   │ /bin                 │
 │  → classify (Brickognize |  │   │      compose | sculpt | recall │   │ /ask                 │
 │              model)         │   │  → Build (integer grid)        │   │ /manual/[id]         │
 │  → colour   (always ours)   │   │  → validate()  ← THE LAW       │   │                      │
 │  → confirm  (always human)  │   │  → repair ladder (rung 0..4)   │   │ two render styles    │
 │                             │   │  → sequence() → 0 STEP         │   │ step viewer + PDF    │
 │ ⇒ inventory.json            │   │ ⇒ build.json, steps.json, tape │   │ agent tape panel     │
 └─────────────────────────────┘   └────────────────────────────────┘   └──────────────────────┘
        Contract 1  ──────────────────────►        Contracts 2,3,4  ──────────────────────►
```

**The three loops** (detail in `docs/04-loop.md`):
- **L1 FIX** — generate → validate → repair → validate. Machine-driven, seconds, invisible.
  Deterministic rungs run *before* the LLM ever sees a failure.
- **L2 EDIT** — "make the chassis longer" → regenerate that subtree only, attachment points frozen.
  Human-driven. The best 20 seconds of the demo.
- **L3 CONFIRM** — recognise → human corrects → re-derive. One correction fixes many rows.

---

## 7. The type contracts (inline, so this doc stands alone)

```jsonc
// Inventory — CV produces, everyone consumes
{ "session_id": "ses_...",
  "items": [ { "id": "inv_001", "part": "3001", "color": 4, "qty": 6,
               "source": "photo",            // photo | typed | set_import
               "confidence": {"part": 0.93, "color": 0.81},
               "status": "confirmed",        // confirmed | needs_review | unknown
               "evidence": {"crop_url": "...", "alternatives": [...]} } ],
  "totals": {"pieces": 412, "distinct": 63, "unknown": 11} }

// Build — the build system produces, frontend consumes
{ "id": "bld_...", "version": 7, "name": "Desk Rover",
  "parts": [ {"id":"p12","part":"3001","color":4,"pos":[2,3,0],"rot":90,"sub":"chassis"} ],
  "subassemblies": { "chassis": {"parent": null, "attach": [...]} },
  "provenance": {"backend":"compose","prompt":"...","seed":41} }

// Report — validator produces, frontend renders `human` verbatim,
//          the repair prompt feeds on `human` verbatim
{ "ok": false,
  "errors":   [ {"code":"OUT_OF_BUDGET","parts":["p12"],
                 "human":"Needs 4× Brick 2x4 in red; you have 1"} ],
  "warnings": [ {"code":"WEAK_BOND","sub":"wing","human":"..."} ],
  "stats": {"parts":147,"studs_used":312,"inventory_remaining":265} }

// Tape event — SSE, one JSON per line
{ "t":1739, "actor":"designer", "kind":"propose", "text":"chassis(10,4) + cabin(open)",
  "status":"ok", "ms":1900, "tokens":2400 }
  // actor ∈ designer|inspector|repair|scribe|cataloguer · status ∈ ok|fail|warn|running
```

---

## 8. Decisions, with the reasoning (so nobody re-litigates them)

| # | Decision | Because |
|---|---|---|
| D1 | Integer stud/plate grid, 90° rotations only | Exact validation, meaningful diffs, free undo, and the LLM *cannot* emit a bad coordinate because it emits none |
| D2 | LLM composes; code places. Tool calls, never raw geometry | The reliability of the entire system rests here |
| D3 | The verifier is deterministic code, not a model | Correctness, and the best sentence in the pitch |
| D4 | Three backends, one output type | They fail differently, so they cover for each other |
| D5 | LDraw as interchange format | Open standard; IDs align with Rebrickable/BrickLink; three.js ships `LDrawLoader` with native build-step support; Studio opens it; plain text |
| D6 | ~200-part whitelist with a hand-verified metadata table | Collapses the search space, and matches what's actually in a spare-parts bin |
| D7 | Subassembly tree with attachment-point contracts | NL editing, manual callouts and scoped repair all fall out of it |
| D8 | CV is a parallel lane, never the critical path | You can type an inventory until everything works; CV is the least predictable spend |
| D9 | Next.js web app, not Electron | A URL you hand a judge beats an installer. Service worker covers offline; `getUserMedia` covers the camera |
| D10 | `claude-opus-5` behind a one-file provider adapter | Makes the OpenAI prize a 30-min decision at hour 30 rather than a fork at hour 0 |
| D11 | Every mutation is an immutable validated version in a tree | Undo, redo, "try another", replay and the tape are all one mechanism |
| D12 | Train on Lambda, serve on Baseten, run ONNX locally for the demo | Each does what it's best at; the demo depends on no network |
| D13 | Two CV implementations behind one interface, forever | The classical path is the floor; it's also a better story than one path |
| D14 | **MIT/Apache licence posture.** Reject pyldraw3 / legolization / hbmartin-rebrickable | GPL-3.0 + single-author, 6-stars-combined. Most hackathons require publishing the repo, so the licence question is not deferrable. *Note: the "forced 3.12 migration" half of this argument no longer applies — we build on Python 3.14 — but the copyleft and single-author risks stand on their own.* |
| D15 | **`bricknet` (MIT) replaces the part metadata table** | Connector poses for 14,603 parts in a 487 KB wheel. Verified directly on PyPI |
| D16 | **SAM 2 (Apache) replaces stage-1 training and the whole synthetic-render pipeline** | Pretrained class-agnostic segmentation is exactly our stage 1. Its absence from 90 findings was the sweep's biggest miss |
| D17 | **LeoCAD → PNG → WeasyPrint → PDF** for the manual; LPub3D time-boxed to 30 min | LPub3D was rated a strong accelerator three times by researchers who each admitted they couldn't verify headless operation |
| D18 | **Inventory becomes a CP-SAT hard constraint**, not a post-hoc validator rule | It's the project's actual contribution; make it rigorous rather than checked afterwards |
| D19 | Vendor BrickGPT's MIT files; **do not** take `stability_analysis.py` | It imports `gurobipy` at module top level and the free licence is size-capped — it fails on a few-hundred-brick model at the worst moment |

---

## 9. Anti-goals — we deliberately do NOT do these

Stating a limit reads as engineering judgment. Failing to state it reads as a bug. Say these out loud.

- **No Technic, hinges, gears, axles, or anything needing kinematics.** Insertion is always straight down.
- **No SNOT techniques**, only a couple of SNOT parts.
- **Not a CAD editor.** You edit by talking, not by dragging bricks around.
- **Not competing with BrickLink Studio on render quality.** The manual has to be *readable*, not photoreal.
- **Not a parts marketplace.** ("You're 3 bricks away" is a stretch goal, not the product.)
- **No minifigure posing, no stickers, no printed parts.**
- Off-whitelist parts still count in your bin — they just can't be *placed*.

---

## 10. Known risks, and what we already decided to do

| Risk | Decision already made |
|---|---|
| Part metadata table has wrong rows | Hand-verify all 200 in a spreadsheet at T+2. It's the foundation |
| Brickognize down / rate-limited | Cache by crop hash; trained model as alternative; typed inventory always works |
| Segmentation fails on real piles | Fix the *capture UX* first (plain background, spread out, scale card), not the model |
| LLM proposes unbuildable things | **Certain, and designed for.** That's the repair ladder. It's the feature |
| three.js dies on the projector | Pre-baked GLB, instanced studs, cap ~300 pieces, test on the projector at T+26 |
| Wifi dies during judging | `DEMO_SAFE=1` built by T+30. Plan for it; it happens |
| Scope creep into Technic | `core_parts.yaml` is a hard boundary |
| 36 hours awake | Staggered 4h sleeps from T+8. 4am code is code you delete at noon |

---

## 11. Where things live

```
PLAN.md                 the pitch, scope, cut-lines, decisions
CONTEXT.md              ← you are here
CLAUDE.md               operational rules auto-loaded by Claude Code
STATUS.md               living state: what works right now, blockers — UPDATE THIS
docs/
  00-synthesis.md       two competing designs merged; what won and why
  01-architecture.md    grid model, validator, backends, substitution, inventory, stack, API
  02-schedule.md        36h plan, gates, risk register, pre-event prep
  03-prizes-and-demo.md prize targets by lane, the 3-minute demo script, submission checklist
  04-loop.md            the three loops, escalation ladder, budgets, determinism, observability
  05-manual-and-render.md step ordering, cameras, arrows, parts panel, render styles, PDF
  06-cv-training.md     synthetic rendering, two-stage model, what to photograph, compute
  lanes/
    00-contracts.md     THE SEAMS. Frozen at T+1. All three lanes agree here
    cv.md  llm.md  frontend.md    one owner each
fixtures/               hand-written examples every lane develops against
data/real/              your phone photos (see its README for the shot list)
```

---

## 12. Context discipline for AI sessions

This project has more documentation than fits comfortably in one working session. Load by lane:

| Working on | Load | Don't load |
|---|---|---|
| CV / training | `CONTEXT.md` §3–5, `docs/lanes/cv.md`, `docs/06-cv-training.md` | the loop doc, the render doc |
| Build system / loops | `CONTEXT.md` (all), `docs/lanes/llm.md`, `docs/01-architecture.md`, `docs/04-loop.md` | CV training, prizes |
| Frontend / 3D | `CONTEXT.md` §3, §6, §7, `docs/lanes/frontend.md`, `docs/05-manual-and-render.md` | CV, loops |
| Demo / submission | `PLAN.md`, `docs/03-prizes-and-demo.md`, `STATUS.md` | everything technical |

**Starting a fresh LLM session:** paste §2, §3, §4 and §7 of this file. That's the minimum viable
context — the idea, the vocabulary, the invariants, and the types. Everything else can be read on demand.

**When a decision gets made in chat, write it into §8 of this file.** A decision that lives only in
a chat log will be re-litigated at 3am by someone who wasn't there.

---

## 13. External dependencies and credits

| Source | Gives us | Note |
|---|---|---|
| **LDraw parts library** (`ldraw.org`, complete.zip ~80MB) | `.dat` geometry, primitives, `LDConfig.ldr` colours | Required by the GLB bake, the metadata script, and rendering |
| **LDraw OMR** (`omr.ldraw.org`) | Real official sets as `.mpd`, **with step data** | The `recall` corpus. Coverage is partial and theme-skewed |
| **Rebrickable** (bulk CSVs + API v3) | Parts, colours, sets, inventories; `external_ids.LDraw` mapping | Set import + catalog. Free API key |
| **Brickognize** (`api.brickognize.com`) | Image → ranked part candidates, free, no key | A free hobby service — cache aggressively and self-rate-limit |
| Public LEGO datasets | Pre-training + validation | Nature Sci. Data 2023 (155k photos + 1.5M renders), B200C, Gdańsk sets |

`CREDITS.md` names all of these. Footer line, non-negotiable:
*"LEGO® is a trademark of the LEGO Group, which does not sponsor, authorize or endorse this project."*
No LEGO wordmark, logo or corporate font in our own branding.

---

## 14. Open questions

Update as they're resolved; delete when they are.

- [ ] Does Hack the North's ruleset allow a model trained before the event? (§ `docs/06-cv-training.md` §7 —
      the mitigation is to render and train *during*, which the compute budget allows.)
- [ ] OMR's real coverage for our whitelist — how many models survive grid-snapping? Decides whether
      `recall` is worth shipping.
- [ ] Brickognize's terms of use and actual rate limit. Check the site before demo day.
- [ ] Licence check on each public dataset before anything ships.
