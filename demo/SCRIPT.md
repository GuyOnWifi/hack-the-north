# The 3-minute demo

**Read this out loud twice before you present it.** The timings are not decoration — the judges
have a queue behind you, and the difference between a project that looks finished and one that
looks like a prototype is whether you got to 2:40.

Before you start: `scripts/demo_safe.sh` is running, the checklist in `CHECKLIST.md` is green,
and there is a **bin of loose bricks** and a **printed manual** on the table next to the laptop.

---

## The arc

One sentence to hold in your head while you talk:

> Every house with kids has a bin of orphaned bricks with no set and no manual, and nothing tells
> you what you can build from *that specific pile*. We take a photo of it and print you a manual.

And one more, for the question you will be asked:

> **The verifier in this system is not a model.** The designer is creative and unreliable; the
> inspector is ordinary deterministic code and is never wrong; the loop between them is where the
> reliability comes from.

---

## 0:00 — the bin in your hand *(15 s)*

Pick the bin up. Actually pick it up.

> "This is a real bin of loose LEGO. No set, no manual, no idea what's in it. Seventy-odd pieces,
> almost all of them singletons."

Do **not** start on the laptop. The physical object is the whole reason the project exists and it
is the only part of the demo no other team has.

## 0:15 — one photo → the inventory fills *(35 s)*

Show the photo, then the inventory grid.

> "One photo. SAM 2 segments it, each crop goes to a part classifier, and colour is computed —
> median LAB against the LDraw palette, never guessed by a language model."

**Click an amber row.** This is the beat people remember.

> "Amber means the system is not sure. It shows you the actual crop it took, and the alternatives
> it was choosing between. You pick. And because one correction re-ranks every similar row, fixing
> one row fixes several."

> "Recall is 0.88 on our own photos. Colour is our weakest stage at 0.70 — which is why colour is
> a hint to the solver, not a constraint."

Numbers you may be asked for, all measured tonight on these photos: 74 detections → 57 identified
pieces → 49 distinct part+colour combinations. SAM 2 doubled the classical pipeline (0.47/0.46 →
0.92/0.82) and the classical path is still there as the fallback.

## 0:50 — the ask, and the tape *(50 s — the technical story)*

Type the ask. Then **stop talking and point at the tape** while it streams.

> "The designer proposes a *composition* — `chassis(10, 4) + cabin(...)`. Notice what it does not
> emit: coordinates. It picks generators and arguments; our code places every brick on an integer
> stud grid."

> "Now the inspector. **This is not a model.** It is ordinary code checking overlap, support,
> connectivity, insertability and your actual inventory. It just rejected that proposal."

> "And the repair — that fix happened **without the LLM**. Rung one of an escalation ladder:
> re-run the same generator with smaller arguments. The model never saw the failure."

Land it:

> "That is the whole architecture. An unreliable thing that proposes, an infallible thing that
> checks, and a budget on the loop between them. The LLM cannot emit a bad coordinate because it
> emits no coordinates."

## 1:40 — the manual *(35 s)*

Scrub the steps. One page per step, camera fixed so the model grows in place.

> "Support-ordered — nothing is ever placed where you could not physically insert it, because
> insertion is straight down and we check the sweep."

Then **hold up the printed PDF**. Physical object number two.

> "Same document. The step renderer is pure Python — no LeoCAD, no CAD install, nothing to
> download. It works on a laptop with no internet, which is this laptop, right now."

## 2:15 — the edit *(25 s)*

> "Make the chassis longer."

> "Only that subtree regenerated. The cabin did not move, because attachment points are frozen
> during an edit. And it is a new immutable version in a tree — so undo, redo and *try another*
> are one mechanism, not three features."

Hit undo. Show it going back.

## 2:40 — the model on the table *(20 s)*

Pick up the model **you physically built from the generated manual**.

> "I built this from the manual the system printed. From the bricks in that bin. That is the
> product."

Stop. Do not add a feature list. Wait for questions.

---

## The three limits — say them, do not be caught by them

Stating a limit reads as engineering judgment. Being caught by one reads as a bug.

1. **Single-layer capture.** "We photograph bricks spread out in one layer, not heaped. That is
   the industry-standard operating condition, not our compromise — Brickit instructs users to do
   exactly the same, and every sorting machine separates mechanically before the camera. We
   measured a heap: SAM 2 returned 82 masks for about 14 bricks, because it boxed every stud."
2. **A ~200-part whitelist.** "The solver places about 200 common parts. Off-whitelist bricks
   still count in your bin — they just cannot be placed. It collapses the search space and it
   matches what is actually in a spare-parts bin."
3. **No Technic.** "No gears, axles, hinges or kinematics. Insertion is always straight down,
   which is what makes the physical validation exact instead of approximate."

If they push on the long tail — and a good judge will:

> "Yes. This bin is 49 part+colour combinations across 57 pieces — almost everything is quantity
> one, which is what a real bin looks like and what synthetic data never shows you. Ignore colour
> and the same bin is 29 distinct parts with twelve 2×4 bricks. Pooling across colour is the fix,
> and colour is a hint in the contract precisely because it is our weakest signal."

---

## The 60-second booth version

For the walk-past, the sponsor table, the person with one minute.

- **0:00** Hold up the bin. *"Bin of loose LEGO, no set, no manual. Nothing tells you what you can
  build from this specific pile."*
- **0:10** Photo → inventory. *"One photo. It knows what's in there, and it tells you when it
  isn't sure."*
- **0:25** The ask → the tape. *"An LLM proposes a structure. It never places a brick. A
  deterministic validator checks overlap, support and your actual inventory — and rejects it.
  The repair happens without the model."*
- **0:45** Hold up the printed manual and the built model. *"Step-by-step manual, printed. I built
  this from it."*
- **0:55** *"Everything you just saw runs on this laptop with the wifi off."*

---

## If something fails live

**The rule: name it in one sentence, move to the next beat, never debug on stage.** A confident
sentence about a limit costs you nothing; a silent thirty seconds of typing costs you the demo.

| What broke | What you say | What you do |
|---|---|---|
| Anything at all, and you are not already in demo-safe | "This is the cached run — conference wifi." | `scripts/demo_safe.sh`, keep talking over it |
| The camera / photo upload | "We've pre-loaded a bin from a photo we took this morning." | The canned session is already seeded; go to the grid |
| The build comes back tiny | "That's the long tail — almost every brick in this bin is a singleton, and right now the allocator matches on part *and* colour." | Go to the tape: the *reject → repair* story is stronger than the model |
| The tape doesn't stream | "Here's the recorded run." | `demo/canned/tape.jsonl`, or read the steps instead |
| The 3D viewer dies / projector hates it | "Let's use the printed one." | Hold up the PDF. It was always the better artifact |
| The edit returns "I can't do that" | "It's bounded on purpose — it tells you exactly what it *can* change rather than silently doing nothing." | Use the words it listed: longer, taller, wider, remove, add, recolour |
| A judge asks something you don't know | "I don't know — I'd have to measure it." | Never guess a number. Every number in this script is measured |

**What you never say:** "it usually works", "that's just a demo bug", or any sentence that starts
with "normally". Either it is a stated limit or it is a cached run. Those are the only two stories.

---

*LEGO® is a trademark of the LEGO Group, which does not sponsor, authorize or endorse this project.*
