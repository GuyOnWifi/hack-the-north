# Bricolage — design choices, in my words

_A cheat sheet for talking about the project as if I designed every decision — because
the reasoning is what a judge actually probes. Read this before the demo. Each section is
a decision, why I made it, and the line I say out loud._

---

## The one idea everything hangs off

**The LLM decides *what* to build. It never places a brick.**

The model only ever emits *choices* — which shape, which generator, which argument, which
socket. Every coordinate is computed by my code on an integer grid, and checked by a
validator that is ordinary code, not a model.

> "The designer in my system is creative and unreliable. The inspector is dumb and
> infallible. Reliability comes from the loop between them — not from trusting the model."

**Why I made this call:** it's the difference between a demo that stands up and the usual
AI-generated-LEGO demo with bricks floating in mid-air. It also means the model *cannot*
emit a bad coordinate, because it emits none.

---

## Why this isn't Brickit (the question I will get)

Brickit scans your pile and **matches it against a catalog of human-designed models**. It's
great, it shipped, millions use it. It cannot invent something new for your bricks, and it
does no structural analysis.

**I do the thing Brickit won't:** invent a *new* model to any request and **prove it stands
up**, using only the bricks you own.

> "Brickit retrieves. I generate and verify. Ask it for a flower it's never seen and it has
> nothing; ask mine and it designs one for your pile and proves it won't fall over."

---

## Why it isn't "just a GPT wrapper"

Because the model does the *easy* part (imagine a shape) and my system does the *hard* part
(make it real). Two things carry the weight, and neither is the LLM:

1. **A real physics engine** decides if it stands.
2. **A solver** turns an imagined shape into legal, connected, buildable bricks under a
   finite inventory.

> "Strip out the LLM and I still have a hard problem: legalize an arbitrary shape into
> stable brick geometry from a finite parts bin. That's NP-hard. The LLM just picks the
> target — the intelligence that makes it *buildable* is deterministic."

---

## Decision: real structural physics, not "does it rest on something"

My validator computes the **center of mass** and checks it against the **ground support
polygon** (does it topple?), and at every horizontal cut it checks whether the **stud-clutch
can hold the overhang above it** (does it shear off?). This is the approach from the
"Legolization" paper (SIGGRAPH Asia 2015).

**Why:** connectivity isn't stability. A tower can be perfectly connected and still tip
over. My favorite demo moment is a build the naive checker *accepts* and physics *rejects*:

> "This tower is fully connected — the old check passes it. Now watch physics: its center
> of mass is 3 studs outside its footprint. It topples. Rejected."

**Why an approximation and not a full FEM solve:** I need it to run in milliseconds inside a
repair loop and to be demonstrably correct on the cases that matter (topple, cantilever). A
center-of-mass + support-polygon + clutch-moment model is exactly that — rigorous where it
counts, and it never claims a false "stable."

---

## Decision: a solver legalizes arbitrary shapes (so it's not 6 templates)

For "build me a flower," the model imagines a **voxel shape**. My solver then does real
work, and **you watch it happen live**:

1. it notices the petals would **float**, and **adds support columns** under them;
2. it **tiles** each layer with a bonded 2×2 offset grid so the whole mass is connected
   (side-by-side bricks in one layer aren't attached — you need staggered courses, real
   masonry bond);
3. it verifies **physics + inventory**, and repairs anything that fails.

> "The model imagined a flower. It didn't know the petals would fall — my solver caught
> that and propped them up. You're watching it reason about gravity in real time."

**Why voxels and not free coordinates:** same core principle — the model proposes a shape
(a choice), my code places every brick. The shape can be anything; the legality is
guaranteed by me.

---

## Decision: integer stud/plate grid, 90° rotations only

No floats anywhere except the final LDraw export. **Why:** exact validation (no
floating-point "almost overlapping"), meaningful diffs, free undo, and the model literally
cannot express an off-grid position. Every hard question about correctness has the same
answer: it's integers, checked by code.

---

## Decision: typed + sized attachment sockets

Generators expose named sockets with a face (studs-up / anti-studs-down) and a footprint.
The model attaches a child by **socket name**, never a coordinate.

**Why this pays off three times over:**
- **Editing by talking:** "make the chassis longer" re-runs one generator; because children
  attach by *name*, the cabin and wheels reattach automatically even though every coordinate
  under them moved.
- **Catching the model's mistakes cheaply:** when the real LLM tried to bolt a wall onto a
  socket too small for it, the size check rejected it *before placing any geometry*, and
  kept the model's good parts.

> "The model proposed a castle, and it made a mistake — tried to attach a slab with no
> mounting point. My system caught it, dropped just that piece, kept the rest, and verified
> the result. That exchange is the whole thesis, live."

---

## Decision: a repair ladder where the model is the *last* resort

When a build fails, deterministic fixes run first — local repair, re-generate smaller,
**substitute parts you don't have for ones you do** — and only if those fail does it go back
to the model. I log which rung fixed each error.

> "Most repairs never reach the model — on a bin with no 2×4s it swaps in 2×2s
> deterministically, zero LLM calls. Cheap, fast, and it's why it doesn't hallucinate its
> way out of problems."

**Why:** reliability and cost. The model is the expensive, unreliable component; I use it as
little as possible and prove everything it touches.

---

## Decision: every build is an immutable version in a tree

Undo, redo, "try another," and byte-for-byte replay are all one mechanism: I record the
*operation*, not the model's output, and replay re-applies the op. Same seed → identical
bricks.

> "I can replay any build from scratch and get the exact same bricks. The model is the only
> nondeterministic thing in the system, and it never touches the replay path."

---

## Decision: LDraw as the format, hand-rolled writer

LDraw is the open standard; three.js reads it natively with build-step support; it opens in
Studio. I verified my ~20-part metadata table against the **real LDraw library** — 19/19,
and the verifier caught one transposed slope, which I fixed. I write LDraw by hand (~40
lines) rather than pull a dependency, so the whole engine runs offline with zero installs.

---

## Prize-track strategy (where I aim this)

- **Agentic / reliability track (my main target):** this project is built for it — conflicting
  inputs (mold guess vs. color estimate vs. the user), decisions under uncertainty, a
  verifier that can *reject*, and an action that produces a physical artifact. **The agent
  tape is the exhibit** — a judge watches the agent propose, get rejected, and self-correct.
- **Best use of AI:** the framing is "we don't trust the model with geometry, and that's why
  it works" — a more sophisticated story than "we called an LLM."
- **Best design:** the live assembly + physics visualization (center-of-mass dot, support
  polygon, red/green) — the invisible hard work made visual.
- **Hardest technical problem:** inventory-constrained structural legalization with a
  provable stability guarantee — it's adjacent to published research, not a CRUD app.

---

## The 3-minute demo (the order that lands)

1. **Scan a real pile** (the hook, ~15s).
2. Type **"build me a flower"** and *watch the agent think* — sketch, spot the floating
   petals, add support, verify stability. This is the wow; nothing else on the floor does it.
3. Flip to the **split-screen**: "LLM places bricks" (floating, falls apart) next to
   "our solver" (stands). The thesis as a picture.
4. Show the **physics view** — center of mass inside the support polygon, green. Nudge it
   out → red, rejected → repaired → green.
5. **Print the manual, hold up the built thing.** "This was in no catalog. The AI invented
   it for these bricks and proved it stands."

---

## Questions a judge will ask, and my answers

**"Isn't this just an LLM wrapper?"** The LLM picks a shape. A deterministic solver makes it
buildable and a physics engine proves it stands. Remove the LLM and the hard problem
remains.

**"How is this different from Brickit?"** Brickit matches a catalog. I generate new models
and verify them structurally. It can't do a request it hasn't seen; I can.

**"How do you know it actually stands up?"** I compute the center of mass against the support
polygon and the stud-clutch limit at every joint. I'll show you a connected build that
physics rejects — the check is real.

**"What if the model proposes something impossible?"** Designed for. The verifier rejects it,
the repair ladder fixes what it can deterministically, and if the bin genuinely can't build
it, it tells you honestly what's missing instead of hallucinating.

**"What's the hard part?"** Legalizing an arbitrary shape into stable, connected geometry
from a finite multiset of parts. It's NP-hard, and it's the part the model never touches.
