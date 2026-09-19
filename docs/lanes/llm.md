# LANE B — Build system, reasoning & loops

**You own:** `inventory.json` + a prompt → a **validated** `build.json` + `steps.json` + the agent
tape. You are the critical path. Everything else in the project consumes your output.

**You do not own:** photos, pixels, or CSS.

**Your contracts:** consume Contract 1, produce Contracts 2, 3 and 4 in `00-contracts.md`.

> Technical detail: [`../01-architecture.md`](../01-architecture.md) (model, validator, generators,
> substitution) and [`../04-loop.md`](../04-loop.md) (the loops — read this one twice).

---

## The rule that defines this lane

> **The LLM decides *what* to build. It never places a brick.**

Every tool the model can call returns a *choice* — a generator name, an argument, a rule id, a shape.
Coordinates are computed by your code, on an integer grid, and checked by a validator that is not a
model. If you ever find yourself writing a prompt that asks for `x, y, z`, you have taken a wrong turn.

---

## Build order (strict — each step depends on the one before)

### T+0 → T+4 · the model
- [ ] `core/model.py` — frozen dataclasses: `Build`, `Part`, `SubAssembly`, `Inventory`.
- [ ] `scripts/build_part_meta.py` — parse the ~200 whitelist `.dat` files → size in studs/plates,
      voxel cells, studs, anti-studs. **Hand-verify every row in a spreadsheet.** 20 minutes of
      tedium that prevents a 3-hour bug at 2am.
- [ ] Commit `fixtures/build.json` — a hand-written 40-piece build. Unblocks frontend immediately.
- [ ] Verify the LDraw facts yourself: stacking is `y -= 24`, a brick's origin is its bottom face.

### T+4 → T+8 · the law
- [ ] `core/validate.py`: overlap · support · connected · inventory, returning the structured
      `Report` with `human` strings.
- [ ] **The 4 unit tests, now.** Three bad builds (overlap / floating / disconnected), one good.
      If the validator is right, nothing downstream can produce a model that doesn't exist.
- [ ] `core/ldraw/write.py` + the round-trip test.

> Those `human` strings are user-facing copy *and* prompt text. Write them once, well.

### T+8 → T+14 · sequencing
- [ ] `core/sequence.py` — topological order + **insertion sweep** (can a hand physically get the
      piece there?) + step grouping (1–6 pieces, same subassembly, same layer, prefer identical parts).
- [ ] Emit `.ldr` with `0 STEP`; commit `fixtures/steps.json`.
- [ ] If `raise Unbuildable` ever fires on a valid build, your validator has a hole — that's a gift,
      go fix the validator.

### T+14 → T+20 · generation and the fix loop
- [ ] 6–8 parametric generators (`chassis`, `cabin`, `axle_pair`, `wing`, `tower`, `wall`, `roof`,
      `slab`) with the attachment-point contract asserted in the base class.
- [ ] `core/substitute.py` + 40 rules in YAML. Grid offsets, not matrices.
- [ ] Tool defs: `propose_build`, `edit_subassembly`, `swap_part`.
- [ ] **The fix loop with the deterministic rungs first.** Rung 0 (local repair) and rung 1
      (re-generate with new args/seed) before the LLM ever sees a failure. Log which rung fixed it —
      *"87% of repairs never reach the model"* is a number you get for free and it's a great line.
- [ ] SSE tape emitting Contract 4.

**GATE (T+20): prompt + typed inventory → validated build → steps. No photos, no polish.**
If this isn't done, cut `sculpt` and say so out loud.

### T+20 → T+26 · the differentiators
- [ ] **Edit loop** — `"make the chassis longer"` → freeze the node's attachment points →
      re-run only that generator → reattach children → revalidate → new version.
      *This is the best 20 seconds of the demo. Prioritise it over `sculpt`.*
- [ ] Version tree with undo/redo and "try another" (same op, new seed, sibling version).
- [ ] `sculpt` backend — LLM emits layer-by-layer ASCII maps, greedy tiler with 20 randomized
      restarts, seam staggering on odd layers.

### T+26 → T+28 · freeze
- [ ] Golden set: 10 prompts × backends, all reaching `ok:true` within budget. Run it before
      every demo — 90 seconds, and it's the difference between knowing and hoping.
- [ ] Adversarial inventories (no 2×4s; plates only) to prove the substitution rungs actually fire.
- [ ] Demo-safe mode: `DEMO_SAFE=1` serves a pre-generated build with zero network.

---

## Model configuration

```python
client.messages.create(
    model="claude-opus-5",
    max_tokens=16000,
    system=SYSTEM,                   # catalog + generators + rules, with cache_control ephemeral
    thinking={"type": "adaptive"},   # budget_tokens 400s on Opus 5 — do not use it
    output_config={"effort": "high"},
    tools=TOOLS,
    messages=msgs,
)
```

- Structured output is `output_config={"format": ...}`; the old `output_format` param is deprecated.
- Stream for `sculpt` (`client.messages.stream(...).get_final_message()`) — it's a long output.
- The system prompt never changes → cache it → the repair rungs get cheap and fast.
- `PROVIDER` env var switches Anthropic/OpenAI **inside `llm/client.py` only**. Never at a call site.

## Budgets — enforce them in code, not in hope

```python
Budget(max_attempts=6, max_llm_calls=3, max_wall_ms=25_000, max_tokens=60_000, seed=...)
```

**25 seconds wall clock, hard.** The tape streams the whole time so it reads as "working", not
"frozen". Past budget you degrade (`../04-loop.md` §5) — you never wait.

Cache LLM calls by `hash(system, messages, tools)` in dev. You'll run the same prompt 200 times.

---

## Prize hooks (this lane carries most of them)

| Prize | What you specifically do |
|---|---|
| **Rox ($10K)** ← your main target | Nothing extra to build — **frame it**. Conflicting sources (mold guess vs colour estimate vs user), incomplete data (the unknown bucket), validation that can *reject* the model, decisions under uncertainty, and an action that produces a physical artifact. **The agent tape is the exhibit.** |
| **OpenAI** | Flip `PROVIDER=openai`. Keep notes on one concrete thing Codex did for you |
| **Cloudflare** (optional) | A Durable Object per build session holding the version tree; D1 for inventory; R2 for renders. Genuinely the right shape for your state model — but commit before T+14 or not at all |
| **Elastic** (optional) | Only if `recall` ships: hybrid BM25 + dense + rerank over the OMR corpus |

## Definition of done

1. Ten golden prompts produce valid builds within budget, from a cold start.
2. Replaying any build's op list from v0 reproduces it byte-for-byte.
3. An impossible request terminates within budget and degrades to a *useful* message.
4. `DEMO_SAFE=1` works with wifi off.
