# 00 — Synthesis: merging the two plans

Two designs were on the table. This file records what won, what lost, and why — so nobody
re-litigates it at 4am.

**The second plan's central claim is correct and it reframes the project:**

> *The hardest part isn't the rendering. The hard part is getting a model to produce a buildable
> brick structure. Design everything around a strict, checkable model of the build, and keep the
> LLM at the level of deciding **what** to build rather than placing individual bricks.*

Everything below follows from that.

| # | Topic | Plan A (mine) | Plan B (yours) | **Decision** |
|---|---|---|---|---|
| 1 | Coordinate system | LDraw LDU floats + AABB collision | **Integer stud/plate grid, 90° rotations only** | **B.** Grid is the source of truth. LDU only exists at export. Integers make the validator exact, make diffs meaningful, make the LLM's life irrelevant (it never sees coordinates), and make undo trivial. |
| 2 | Connection model | "footprints overlap and Y ranges touch" | **studs / anti-studs / voxel volume / insertion direction per part** | **B.** Derived once at build time into a part-metadata table. A stud-level connection graph is what lets you check "can this piece physically be inserted here". |
| 3 | Generative approach | LLM emits layer-by-layer voxel maps | **LLM composes hand-written parametric generators** (`chassis(l,w)`, `wing(span)`) | **Both, as two backends.** `compose` (B) for structured things — vehicles, buildings, robots. `sculpt` (A) for freeform things — a dog, a dragon, a logo. A router picks; both emit the same grid Build. B is more reliable, A is more surprising. Shipping both is the difference between a good project and a memorable one. |
| 4 | Retrieval | OMR `.mpd` corpus as the MVP path | seed/inspiration | **Keep as a third backend, `recall`.** It's the one path that cannot fail, so it's the demo floor. |
| 5 | LLM interface | structured JSON output | **tool calls** (`propose_build`, `edit_subassembly`, `swap_part`) | **B.** Tools are what make the whole thing loopable — see `04-loop.md`. Strict schemas on every tool. |
| 6 | Step ordering | layer-by-layer + connectivity | + **insertion sweep check** (can the hand physically get it there?) + subassembly callouts | **B**, plus A's adaptive step sizing (3 pieces for the first steps, 5–8 later). |
| 7 | Camera per step | one fixed isometric | **ID-buffer visibility scoring across candidate angles, penalize camera changes** | **B**, with A's fixed isometric as the fallback if you run out of time. |
| 8 | Part rendering | `LDrawLoader` at runtime | **pre-bake ~200 parts to GLB with `packLDrawModel`, instance the studs** | **B** for the shipped app, A for the dev loop (runtime loading is fine while you have 12 parts on screen). |
| 9 | Manual aesthetics | "render a step, put a number on it" | **blue ~#CFE3F4 ground, ortho/low-FOV iso camera, black LDraw edge lines, parts panel, 2× counts, arrows only when ambiguous** | **B, wholesale.** The edge lines are most of the effect. This is the cheapest wow-per-hour in the entire project. |
| 10 | App shell | Next.js web + FastAPI | Electron + React + Vite | **A (web).** A hackathon demo needs a URL you can hand a judge and a phone camera that works without an install. B's real point — cache the parts library, work offline — is satisfied by a service worker + the pre-baked GLB pack. |
| 11 | Recognition in the build order | early-ish, parallel | **last** | **Split the difference.** Recognition is a *separately owned parallel workstream* from hour 0, but the core pipeline is developed against a typed inventory and **never blocks on CV**. B is right that recognition is unreliable and A is right that "use your spare pieces" is the entire pitch — so it must exist, it just must not be on the critical path. |
| 12 | Natural-language editing | not in plan | **subtree replacement over the subassembly tree** | **B, and promote it to a headline feature.** "I don't like the chassis" → regenerate only that subtree, keep its attachment points → everything else still fits. This is the best demo moment in either plan and it is the reason the build model needs a tree. |

## What this makes the project

Not "an LLM that draws LEGO". It's:

> **A typed, validated, integer-grid build system for LEGO — with an LLM driving it through tools,
> a deterministic validator refusing anything unbuildable, and a renderer that emits real instruction manuals.**

The LLM is the designer. The grid model is the law. The validator is the judge. That framing is
what you say to a judge, and it's what makes the sponsor-prize story land (see `03-prizes-and-demo.md`).
