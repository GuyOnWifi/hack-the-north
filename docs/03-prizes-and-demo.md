# 03 — Prize strategy & the demo

## The decision: five targets, one per lane, ~1.5h of extra work each

Chasing prizes only sinks a project when one person absorbs all the integration cost. Distribute it
by lane and it's an afternoon's work in total.

| Prize | Owner lane | Extra cost | Why it's on the list |
|---|---|---|---|
| **Finalist** (main award) | FRONTEND | 0h — it *is* the project | Creative, tactile, surprising, physical. Built for their brief |
| **Rox — Best AI Agent ($10K / $2K)** | LLM | ~0.5h of *framing* | Their brief is a description of your inventory pipeline + fix loop. Highest expected value on the board |
| **Sentry** (guaranteed interviews) | FRONTEND | ~1.5h | Session Replay on capture + Tracing on the loop. Produces a real finding you can quote |
| **OpenAI API prizes** | LLM | ~1h + notes | One env var, because of the provider adapter. Keep notes on what Codex actually did |
| **Baseten** (SF trip, interviews) | CV | ~2h | Serve the trained segmenter. A real deployment, and it upgrades your weakest component |
| **Aramco — Best Beginner Hack** | — | 0h | Pure eligibility: every member has ≤1 prior hackathon. Tick it if true |

**Total added work: ~5 hours across three people.** Everything below is the reasoning, plus the
Tier-2 options if a lane finishes early.

> **Note on Lambda:** Lambda isn't a sponsor, so your GPU credits win no prize directly — they just
> make the CV lane free. Baseten is the prize-bearing deployment target: **train on Lambda, serve on
> Baseten, run ONNX locally for the demo.** All three, each doing what it's best at.

---

## The rule before the table

**Only add a sponsor integration if it does real work in the product.** Judges at every one of these
booths have seen fifty projects that `npm install`ed their SDK and called it a day. One integration
that genuinely carries a feature beats four stickers. Cap yourself at **4–5 submissions**.

---

## Tier 1 — do these (high fit, low cost)

### 🥇 Finalist (the main award)
*"Creative, surprising, original, clever technical work, playful."* This project is built for that
brief: a physical, tactile, slightly absurd idea with a genuinely hard technical core. **Lead with
the bin of real bricks on the table and the printed manual in your hand.** Cost: zero, it's the project.

### 🥇 Rox — Best AI Agent ($10K / $2K) ← highest expected value
Their brief is *"LLMs operating on real-world messy data… incomplete datasets, conflicting sources,
noisy data… data cleaning and validation, multi-source resolution, intelligent error handling,
robust decision-making under uncertainty."*

That is a description of this project's inventory pipeline and fix loop. You don't build anything
extra — you **frame** it:

- noisy data: brick recognition from one photo of a cluttered pile
- conflicting sources: Brickognize's mold guess vs our colour estimate vs the user's correction
- incomplete data: the "unknown" bucket, and builds designed around what's *missing*
- validation: a deterministic verifier that can reject the model's output
- decisions under uncertainty: the confidence policy and the escalation ladder
- meaningful action: it produces a manual you can physically follow

**Show the agent tape** (`04-loop.md` §6). It is the single most persuasive artifact you have for
this prize. Cost: ~30 minutes of framing. Do it.

### 🥈 Sentry — Best Use of Sentry (guaranteed interviews)
Needs ≥2 products beyond error monitoring. You get two almost free:
- **Tracing** — you're already emitting spans per loop iteration; wire them to Sentry and you get a
  flame graph of Designer → Inspector → Repair. That's a genuine debugging tool for *you*.
- **Logs** — the agent tape, shipped.
- (**Session Replay** on the capture flow if you want a third: watching a real person fail to
  photograph bricks is the best UX feedback you'll get all weekend.)

Their criterion is *"how meaningfully Sentry data influenced what you built."* So use it and note
one real thing it caught — a slow Brickognize call, a tiler that blew up on a 400-piece build.
Cost: ~1.5h.

### 🥈 OpenAI — API Prizes
Two halves: the API powers the experience, and Codex meaningfully helped you build it. Your
`llm/client.py` adapter (`01-architecture.md` §8) makes the first half a ~30-minute flip. The second
half you should be doing anyway — just **keep notes as you go**: one concrete thing ("Codex wrote the
LDraw transform math and its round-trip test while I built the validator"). Cost: ~1h + notes.

> If you'd rather stay on Claude, that's a legitimate call — the adapter means it's a decision you
> can make at hour 30 rather than hour 0. Don't fork the codebase for it.

### 🥉 Aramco — Best Beginner Hack
Pure eligibility check: every team member has attended ≤1 prior hackathon. If that's you, tick it.
Cost: zero.

---

## Tier 2 — do one of these if the lane owner is ahead of schedule

| Prize | What it'd actually be | Cost | Verdict |
|---|---|---|---|
| **Baseten** (SF trip, interviews) | Host the segmentation model on Baseten — swap OpenCV for **SAM 2** behind the same interface, or serve a fine-tuned brick classifier. Genuine upgrade to the weakest part of the pipeline | 2–3h | **Best Tier-2 pick** if the vision lane is healthy. It improves the product, not just the submission |
| **Browserbase** ($2,000) | The "you're 3 bricks away" feature: given the missing parts, browse BrickLink for price + availability and build a shopping list | ~2h | Good if the missing-parts feature ships. Stacks with a commerce angle |
| **Cloudflare** — Best Agent with a Brain | Move the orchestration layer into Workers: a **Durable Object per build session** holding the version tree, D1 for inventory, R2 for renders/PDFs, Vectorize for the `recall` corpus. The DO-per-session mapping is genuinely the right shape for our state model | ~4h | Only with three people and only if you commit before T+14. Changing backend topology at hour 25 is how demos die |
| **Elastic** — Find the Signal | Hybrid BM25 + dense + reranking over the OMR/part corpus for the `recall` backend | ~3h | Only if `recall` ships |
| **Huawei openJiuwen** — multi-agent | Cataloguer / Designer / Inspector / Scribe already map cleanly onto their rubric, but eligibility wants JiuwenSwarm or WorkSwarm | ~4h | Read their eligibility carefully at the booth before committing an evening to it |

---

## Tier 3 — skip (say why, it'll come up)

**Expo** (a second native frontend — 5h+ for a duplicate UI), **Shopify** (the commerce angle is
bolted on and their rubric wants merchant impact), **Backboard** (conflicts with the direct-API
architecture), **GPTZero / RBC / Federato / QNX / Dryft / CSE / Tether / Intact / Dominion / Bracket
Bot / LeLamp / Linq / Zip** (no honest fit — don't contort a good project to chase them).

**Solana's Badge Hack** is explicitly allowed to be unrelated to your main project. If someone hits a
two-hour block where they're waiting on a teammate, it's a legitimate side quest. Don't let it touch
the main build.

---

## The 3-minute demo script

Rehearse this **out loud, four times, on the real machine**. It will run 4:30 the first time.

> **[0:00 — the bin, in your hands]**
> "This is my little brother's LEGO bin. Four hundred pieces, no sets, no manuals. Every house with
> kids has one of these and nobody knows what to do with it."
>
> **[0:15 — one photo]**
> Spread bricks on the white sheet, phone overhead, one tap.
> "One photo. We segment it, identify every part, and estimate colour separately from the mold."
> Inventory fills in. **Click an amber row.** "This one it's only 60% sure about — here's the crop
> it came from and its top three guesses. We never silently guess; you confirm." Tap the right one —
> **three other amber rows go green.** "One correction propagates."
>
> **[0:50 — the ask]**
> Type: *"build me a little rover"*.
> **Point at the agent tape as it streams.** "The model proposes a *composition* — chassis, axles,
> cabin — it never touches a coordinate. Then a deterministic validator checks overlap, support,
> connectivity, and your actual inventory. It failed here: not enough red 2×4s. It substituted two
> 2×2s — that's arithmetic, not the model. Most repairs never reach the LLM at all."
>
> **[1:40 — the manual]**
> Scrub the steps. "Real step ordering — including a check that you can physically insert each piece,
> so it never tells you to slide a brick under something you already built. Camera picks itself per
> step by scoring how visible the new pieces are."
> **Hold up the printed PDF.** "And it exports a manual."
>
> **[2:15 — the edit, your best 20 seconds]**
> Type: *"I don't like the chassis, make it longer."*
> Ghost out, drop in. "It regenerates only that subassembly. The attachment points are frozen, so
> the cabin and the axles still fit. Everything revalidates."
>
> **[2:40 — the close]**
> **Hold up the model you actually built out of real bricks.**
> "We built this one. From the manual it generated. Out of that bin."

Then stop talking. That last beat is the whole pitch.

### Adaptations
- **60-second booth version:** bin → photo → prompt → scrub the manual → hold up the physical build.
- **If wifi dies:** `DEMO_SAFE=1`, and say "we pre-cached this because conference wifi" — poise about
  a failure reads better than a working demo.
- **If a judge is technical:** skip straight to the validator and the escalation ladder. That's the
  part that impresses engineers, and it's the part most projects don't have.

---

## Submission checklist (do this at T+34, not T+36)

- [ ] Devpost: title, tagline, the bin-of-bricks photo as the hero image
- [ ] 2-minute video, recorded at T+31 while things work
- [ ] Every eligible sponsor prize ticked, each with a **specific** sentence about how it's used
- [ ] Repo public, README with: problem, architecture diagram, the three loops, **stated limits**
      (no Technic, ~200-part whitelist, confirmation step required), setup + run instructions
- [ ] `CREDITS.md`: LDraw, OMR, Rebrickable, Brickognize — plus the LEGO trademark disclaimer
- [ ] A live URL that works from someone else's phone
- [ ] Demo-safe mode verified on a laptop with wifi turned off
- [ ] Golden-prompt set re-run and green
