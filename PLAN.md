# BRICOLAGE — build anything from the LEGO you already own

> **bricolage** *(n.)* — construction or creation from whatever materials happen to be at hand.

**Pitch (say this exact sentence at the judging table):**
> "Dump your loose LEGO on a table, take one photo, and tell us what you want to build.
> We design something that uses *only the bricks you actually have*, prove it's physically
> buildable, and hand you a real step-by-step manual for it."

**Why this is novel (verified by a 90-finding ecosystem sweep):** generative LEGO systems exist —
BrickGPT/LegoGPT makes physically-stable models from text — but every one of them assumes an
infinite supply of bricks. BrickNet's paper lists generation "conditioned on a specified part set"
as *future work*. **Nobody generates builds constrained to the bricks you actually own.** That
constraint is the entire problem, and it's ours.

Every house with kids has a bin of orphaned bricks — the sets are gone, the manuals are lost, and
nobody knows what to do with 400 random pieces. Rebrickable can tell you which *official sets* you
could almost build. Nothing tells you what you can build **right now, from exactly this pile**, and
then teaches you how.

---

## Read these in order

| Doc | What's in it |
|---|---|
| **[`CONTEXT.md`](CONTEXT.md)** | **The whole-project context document — glossary, invariants, type contracts, decisions, anti-goals. Self-contained; start here.** |
| [`STATUS.md`](STATUS.md) | Living state: gates, lane status, what's broken. Update it as you go |
| [`CLAUDE.md`](CLAUDE.md) | Operational rules auto-loaded by Claude Code |
| **[`docs/07-tooling-decisions.md`](docs/07-tooling-decisions.md)** | **Post-research verdict: what we adopt, reject and must build ourselves. Deletes ~15h of planned work. Read before writing code.** |
| [`docs/00-synthesis.md`](docs/00-synthesis.md) | The two competing designs, merged — what won and why. **Read first.** |
| **[`docs/lanes/`](docs/lanes/)** | **Three owner-scoped plans — one per person.** [`00-contracts.md`](docs/lanes/00-contracts.md) (the seams, frozen at T+1) · [`cv.md`](docs/lanes/cv.md) · [`llm.md`](docs/lanes/llm.md) · [`frontend.md`](docs/lanes/frontend.md) |
| [`docs/01-architecture.md`](docs/01-architecture.md) | The grid build model, validator, three generation backends, substitution, inventory, stack, API |
| [`docs/04-loop.md`](docs/04-loop.md) | **The three loops** — fix, edit, confirm — state model, escalation ladder, budgets, determinism, observability |
| [`docs/05-manual-and-render.md`](docs/05-manual-and-render.md) | Step ordering with insertion sweep, camera selection, arrows, parts panel, the two render looks, PDF |
| [`docs/06-cv-training.md`](docs/06-cv-training.md) | Training your own brick detector: synthetic rendering, two-stage model, what to photograph, compute budget |
| [`docs/02-schedule.md`](docs/02-schedule.md) | Pre-event prep, lanes, hour-by-hour 36h plan, gates, risk register |
| [`docs/03-prizes-and-demo.md`](docs/03-prizes-and-demo.md) | Which sponsor prizes to chase and what each costs, the 3-minute demo script, submission checklist |

---

## The one idea that makes this work

> **The LLM decides *what* to build. It never places a brick.**

Every build lives on an **integer stud grid** — X/Z in studs, Y in plate heights, rotation in 90°
steps. A deterministic validator checks overlap, support, connectivity, physical insertability, and
your actual inventory. The model only ever emits *choices*: which generator, which arguments, which
substitution rule, which shape. Coordinates are computed by code.

That single constraint is what turns "an LLM that hallucinates LEGO" into a system that produces
structures that stand up. It is also the answer to every hard question a judge will ask.

```
prompt + your bin ──► Designer (LLM) ──► Build on the grid ──► Inspector (pure code)
                          ▲                                          │
                          └──────────  repair ladder  ◄──────────────┘
                                   (most repairs never reach the model)
                                              │
                                              ▼
                              step sequencer ──► 3D manual + PDF
```

---

## The four screens

1. **Capture** — spread bricks on a plain surface, one photo, guided overlay + printed scale card.
2. **Your Bin** — live inventory grid with confidence chips. Amber rows show the crop they came from
   and their top-3 alternatives. Always editable, always usable, never blocked by the AI.
   Also: type parts in, or import a set number.
3. **Ask** — *"build me a rover."* Watch the agent tape: proposed → validated → repaired → valid.
4. **Manual** — orbit the model, scrub the steps, watch pieces drop in, download the PDF.

---

## Scope

### Must work by T+20 (the demo floor)
- Integer grid build model + part metadata table
- Validator: overlap · support · connected · inventory (+ stability, bond as warnings)
- LDraw export with `0 STEP`, rendering in the browser with black edge lines
- Step sequencer with the **insertion sweep** check
- 6–8 parametric generators + LLM composition via tool calls + the fix loop
- Typed / set-import inventory
- The manual page: step number, parts panel with `2×` counts, drop-in animation

### Then, in this order
1. **Natural-language editing** — "make the chassis longer" → subtree regeneration with frozen
   attachment points. *Your best 20 seconds of demo.*
2. **Photo recognition** — segment → Brickognize → our own colour estimation → confirm screen
3. **PDF export**
4. `sculpt` backend — freeform voxel shapes for "a dog", "a dragon", things no generator covers
5. Per-step camera scoring, ambiguity arrows
6. `recall` backend — real official sets (LDraw OMR) that fit your bin

### Explicit non-goals (say these out loud; a stated limit reads as judgment)
- No Technic, hinges, gears, axles or anything needing kinematics. Insertion is always straight down.
- ~200-part whitelist for placement. Off-list parts still count in your bin, they just can't be placed.
- Not a CAD editor — you edit by talking, not by dragging.
- Not competing with BrickLink Studio on render quality. It has to be *readable*, not photoreal.

---

## Cut-lines — decide these awake, at the gate, not asleep at 4am

| T+ | Gate | If behind, cut |
|---|---|---|
| 4 | hand-written build → `.ldr` → renders with edge lines | nothing — everyone stops and fixes this |
| 8 | validator passes its 4 unit tests; inventory typed + imported | — |
| 14 | a 40-piece build produces a browsable manual | camera scoring, arrows |
| 20 | prompt → validated build → manual, end to end, no photos | `sculpt`, `recall` |
| 26 | photo → build → edit → manual → PDF | photo path (demo with typed + set-import) |
| 28 | **feature freeze** | everything not already working |
| 30 | demo-safe mode built and verified offline | — |
| 34 | submitted | — |

---

## Decisions log

| # | Decision | Why |
|---|---|---|
| D1 | **Integer stud/plate grid, 90° rotations only.** No floats in the build model | Makes the validator exact, diffs meaningful, undo free, and makes it impossible for the LLM to emit a bad coordinate — it never emits one |
| D2 | **LLM composes; code places.** Tool calls, never raw geometry | The reliability of the whole system |
| D3 | **The verifier is not a model.** The Inspector is deterministic code | The best sentence in your pitch, and true |
| D4 | Three backends, one output type: `compose` (parametric, reliable) → `sculpt` (voxel, surprising) → `recall` (real sets, safe) | Each fails differently, so they cover for each other |
| D5 | LDraw is the interchange format | Open standard, IDs align with Rebrickable/BrickLink, three.js ships `LDrawLoader` with native build-step support, Studio opens it, plain text |
| D6 | ~200-part whitelist, hand-verified metadata table | Collapses the search space and matches what's actually in a spare-parts bin |
| D7 | Subassembly **tree**, with attachment-point contracts | Natural-language editing, manual callouts, and scoped repair all fall out of it |
| D8 | Recognition is a parallel lane, never on the critical path | You can type an inventory until everything else works; CV is the least predictable hour-per-hour spend |
| D9 | Next.js web app, not Electron | A URL you hand a judge beats an installer. Service worker covers offline; `getUserMedia` covers the camera |
| D10 | `claude-opus-5` behind a one-file provider adapter | Keeps the OpenAI sponsor prize a 30-minute decision at hour 30 instead of a fork at hour 0 |
| D11 | Every mutation is an immutable, validated version in a tree | Undo, redo, "try another", replay, and the agent tape — all one mechanism |
