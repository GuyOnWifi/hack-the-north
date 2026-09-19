# 04 — Loops: how the system iterates

Three loops make this project feel alive instead of like a one-shot prompt. They share one
mechanism: **every mutation produces a new immutable version, and every version is validated
before anyone sees it.**

```
   L1  FIX     generate → validate → repair → validate …      machine-driven, seconds, invisible
   L2  EDIT    user says something → re-generate one subtree   human-driven, the demo moment
   L3  CONFIRM recognize → user corrects → re-derive           human-in-the-loop, the trust story
```

---

## 0. The state model (shared by all three loops)

```python
@dataclass(frozen=True)
class Version:
    build_id: str
    version: int                 # monotonic
    build: Build                 # immutable snapshot (see 01 §1.2)
    report: Report               # validator output for THIS build
    op: Op                       # what produced it
    parent: int | None           # version it came from
    cost: Cost                   # {tokens_in, tokens_out, ms, llm_calls}
```

Rules, and they are not negotiable:

1. **Nothing mutates a `Build` in place.** Every operation is `Build -> Build`.
2. **No `Version` is created without a `Report`.** An invalid build can exist as a version (so you
   can inspect and repair it) but it is flagged `ok:false` and can never be exported.
3. **`parent` makes the history a tree, not a list** — so undo/redo and "try another variation"
   are the same mechanism. Undo = move the head pointer. That's it.
4. Every `Op` is serializable and replayable: `{kind, args, seed, model, prompt_hash}`. Replaying
   the op list from version 0 must reproduce the current head. This is your debugger, your undo,
   your cache key, and — when a judge asks "is it actually reasoning or is it canned?" — your proof.

Persist versions in Postgres (`build_versions`), keep the last ~30 hot in memory. At the scale of a
hackathon demo this is a table with a JSONB column. Don't over-engineer it; do not skip it.

---

## 1. Loop L1 — the FIX loop (generate → validate → repair)

The single most important loop. It is what lets you put an LLM anywhere near a physical structure.

```python
def build_with_fixes(spec, inventory, *, budget: Budget) -> Version:
    attempt = 0
    build = backend.generate(spec, inventory, seed=budget.seed)
    while True:
        report = validate(build, inventory, meta)
        emit_trace(attempt, build, report)          # streams to the UI — see §6
        if report.ok:
            return commit(build, report)
        if attempt >= budget.max_attempts or budget.exhausted():
            return commit_best(build, report)       # degrade, never hang — see §5
        strategy = choose_strategy(report, attempt) # ← the escalation ladder, §1.2
        build = strategy.apply(build, report, inventory)
        attempt += 1
```

### 1.1 Error taxonomy → repair strategy

**Do not send every failure to the LLM.** Most failures have a deterministic fix that runs in
microseconds. The LLM is the last resort, not the first.

| Validator error | Deterministic repair (try first) | Escalate to LLM only if |
|---|---|---|
| `OVERLAP` | nudge the later-placed part along its free axis by 1 stud; if no free cell, drop it and re-tile that region | the whole subassembly overlaps → re-pick generator args |
| `UNSUPPORTED` | search ±1 in y for a supported cell; else insert a support plate underneath if inventory allows | repeated in >20% of parts → the design is wrong, regenerate |
| `DISCONNECTED` | find the two nearest components' closest stud pair; insert a connector brick if inventory allows | the gap is >3 studs → the design is wrong, regenerate |
| `OUT_OF_BUDGET` | apply substitution rules (01 §5) in penalty order; then recolor if the part is internal | no rule reaches a part you own → ask the LLM to pick a different generator/shape |
| `UNSTABLE` | widen the base by one ring of plates | — |
| `WEAK_BOND` (warning) | re-run the tiler for that layer with a different scan origin | never |

Log which rung fixed it. **"87% of repairs never reach the model"** is a great line at the judging
table and it's a number you get for free from this table.

### 1.2 The escalation ladder

```
rung 0   deterministic local repair          µs      up to 3 rounds
rung 1   re-tile / re-run the generator with different args + a new seed   ms     up to 2 rounds
rung 2   LLM repair: hand it the report's `human` strings, ask for a
         revised composition or sculpt spec (same tool schema)             ~4 s   up to 2 rounds
rung 3   fall back to the next backend  (compose → sculpt → recall)        varies 1 round
rung 4   return the best-scoring invalid build, flagged, with the
         validation panel open and an explanation                          —      terminal
```

Never loop rung 2 more than twice. An LLM that failed twice on the same structured report will fail
a third time; the cost is real and the demo clock is not.

### 1.3 The repair prompt (rung 2)

Give it: the failing subassembly only (not the whole build), the `human` error strings, the
inventory summary, and the generator catalog. Ask for a **replacement composition for that node**.
It is literally the `edit_subassembly` tool from L2 — the fix loop and the edit loop share one
code path, which is why this stays small enough to build in a night.

```
The 'wing' subassembly failed structural validation:
  - DISCONNECTED: 'wing' touches the rest of the model at 0 studs (needs ≥1)
  - OUT_OF_BUDGET: needs 6× Plate 1x8 in white, you have 2
Inventory (relevant): Plate 1x8 white ×2, Plate 1x4 white ×9, Plate 1x2 white ×14, Brick 1x4 white ×6
Propose a replacement `wing` using the generator catalog. Keep its attachment to 'chassis' at [4,6,2].
```

Note what the model is *not* given: coordinates, the grid, or any freedom to place a part.

### 1.4 Budgets (per build request)

```python
Budget(max_attempts=6, max_llm_calls=3, max_wall_ms=25_000, max_tokens=60_000, seed=...)
```

Wall-clock is the one that matters at a demo table. **25 seconds, hard.** The UI streams progress
the whole time (§6) so 25s reads as "working", not "frozen". Anything not done by then degrades
(§5) rather than waits.

---

## 2. Loop L2 — the EDIT loop (this is your demo's best 30 seconds)

The subassembly tree makes natural-language editing nearly free:

> **"I don't like the chassis, make it longer and lower."**

```
1. resolve   LLM maps the utterance to a node + an op:
             {tool:"edit_subassembly", node:"chassis", gen:"chassis",
              args:{length:12, style:"lowered"}}
2. freeze    collect the node's attachment points as HARD CONSTRAINTS —
             every child (cabin, axles) keeps the exact grid coords where it attaches
3. regen     re-run only that generator, satisfying the frozen attach points
4. reattach  children are translated, not regenerated
5. validate  full-build validate() — a longer chassis may now clip the cabin
6. fix       if it fails → drop straight into L1, scoped to the changed subtree
7. commit    new Version, parent = previous head
```

**The attachment-point contract is the whole trick.** A generator declares what it offers
(`attach: [{at:[x,y,z], face:"top", studs:[...]}]`); a re-generation must offer a superset of the
points its children are using, or it's rejected and retried with adjusted args. Codify this as an
assertion in the generator base class so a broken generator fails loudly at dev time.

### 2.1 What the user can say (support these five, they cover everything)

| Utterance shape | Op | Notes |
|---|---|---|
| "make the X bigger / longer / taller" | `edit_subassembly(X, args±)` | numeric nudge on the named arg |
| "I don't like the X" / "different X" | `edit_subassembly(X, new seed)` | same generator, new seed → visibly different result |
| "make it red" / "make the wings white" | `recolor(node, color)` | pure inventory check, no geometry — instant |
| "remove the X" | `delete_node(X)` | then L1 fixes the connectivity hole |
| "add a Y" | `add_node(gen=Y, attach_to=?)` | LLM picks the parent + attach point from the catalog |

Anything else → the model says what it *can* do, listing the nodes by name. A bounded, honest
"here's what I can change" beats a free-text box that silently no-ops.

### 2.2 UI behaviour during an edit

Ghost the old pieces out, drop the new ones in, and run a live counter of **inventory remaining**.
Three seconds of animation carries the entire story of what the system just did.

### 2.3 Undo / redo / branch

Undo is a pointer move on the version tree. Add a "try another" button that re-runs the *same* op
with a new seed and creates a **sibling** version — now the user can flip between variants. Nearly
free given the state model, and it makes the thing feel like a tool rather than a slot machine.

---

## 3. Loop L3 — the CONFIRM loop (recognition ⇄ human)

```
photo → segment → classify → colorize → propose rows
   ↓
 user confirms / fixes / deletes a row
   ↓
 correction is recorded as {crop_id, model_said, user_said, scores}
   ↓
 ┌─ within the session: the reconciler re-runs with the confirmed rows as anchors —
 │  "crops 4, 9 and 17 were confirmed as 3003; crop 12 at 0.55 has the same footprint,
 │   raise it to 3003 too"  → other ambiguous rows update
 └─ across sessions: corrections accumulate as a local prior; next time a crop looks like
    that one, the confirmed answer ranks first
```

Two properties to demo out loud:
- **One correction fixes many rows.** Confirm one brick, watch four amber rows go green. That is a
  20-line feature (re-run the reconciler with confirmed anchors) and it looks like magic.
- **Nothing silently changes.** Suggestions arrive with their reason string, and the user accepts.

---

## 4. The agent view (for the multi-agent sponsor prizes)

The same three loops, named as roles. Do not add agents to have more agents — these four exist
because each has a genuinely different input, output and failure mode:

| Agent | Sees | Emits | Fails by |
|---|---|---|---|
| **Cataloguer** | crops, candidate lists, sizes | inventory corrections | over-confident mold guesses → caught by the human confirm step |
| **Designer** | prompt, inventory summary, generator catalog | a composition or sculpt spec | proposing something unbuildable → caught by the Inspector |
| **Inspector** | a Build | a structured Report | — *it is deterministic code, not a model*, which is the point |
| **Scribe** | a validated Build | step grouping hints, step captions, the model's name | bad prose → harmless |

The interesting sentence, and it's true: **the verifier in this system is not a model.** The
Designer is creative and unreliable; the Inspector is dumb and infallible; the loop between them is
where the reliability comes from. That's a better multi-agent story than four LLMs reviewing each
other, and you can prove it live by breaking an inventory and watching the loop route around it.

---

## 5. Degradation ladder (what happens when a loop runs out)

Never hang, never show a spinner with no exit, never show a stack trace.

```
1. best valid version so far                     → ship it, note "2 substitutions were needed"
2. no valid version, but a near-valid one        → ship flagged, open the validation panel,
                                                   say exactly what's wrong in plain English
3. backend failed entirely                       → fall back:  compose → sculpt → recall
4. all backends failed                           → `recall` on the inventory alone:
                                                   "here are 3 real sets you can nearly build"
5. network/LLM down (the actual hackathon risk)  → DEMO-SAFE MODE:  a pre-generated build,
                                                   pre-computed steps, cached renders, no network
```

**Build rung 5 by hour 30.** `DEMO_SAFE=1` in the env, a canned session id, everything served from
disk. Every hackathon has a wifi outage during judging; the teams who planned for it look like
wizards and the ones who didn't look like they have nothing.

---

## 6. Observability: make the loop visible

Stream every loop iteration to the client over SSE and render it as an **agent tape** in a side
panel:

```
▸ Designer      proposed  chassis(10,4) + axle_pair + cabin(open)        1.9s   2.4k tok
▸ Inspector     ✗ 1 error   OUT_OF_BUDGET: needs 4× Brick 2x4 red, you have 1
▸ Repair r0     substituted 3× (Brick 2x4 → 2× Brick 2x2)               0.4ms
▸ Inspector     ✗ 1 warning WEAK_BOND: chassis seam_score 0.51
▸ Repair r1     re-tiled layer 2 with offset origin                     1.1ms
▸ Inspector     ✓ valid   147 parts · 312 studs · 265 bricks left
▸ Scribe        24 steps, 3 subassembly callouts                        2.2s
```

This panel is worth more at the judging table than any amount of polish elsewhere. It makes the
invisible work visible, it shows the deterministic rungs doing the heavy lifting, and it answers
"how does it know it works?" before the question is asked. It's also your debugger — you will use
it more than you use the UI.

Wire Sentry tracing to the same spans (see the prizes doc — it's a real integration, not a sticker).

---

## 7. Determinism, caching, idempotency

- Every generator and tiler takes an explicit `seed`. Same (spec, inventory, seed) → byte-identical
  Build. Non-negotiable: it's what makes replay, undo, and "try another" work.
- `POST /builds` takes an `Idempotency-Key`; a repeat returns the same build_id. Prevents the
  double-tap-at-the-demo-table disaster.
- Cache by content hash: `hash(prompt, inventory_digest, backend, seed)` → build_id. Re-demoing the
  same prompt is then instant, which is exactly what you want when you demo it forty times.
- Cache LLM calls by `hash(system, messages, tools)` in dev — you will run the same prompt 200 times
  and this both speeds you up and keeps your API spend sane.
- Mark the system prompt (catalog + generators + rules — it never changes) with `cache_control`
  ephemeral so the repair rungs are cheap and fast.

---

## 8. Testing the loops

| Test | What it catches |
|---|---|
| **Golden prompts** — 10 prompts × 3 backends, asserted to reach `ok:true` within budget | regressions in generators or the repair ladder |
| **Adversarial inventories** — the same 10 prompts against a bin with *no* 2×4s, then one with only plates | that the substitution and repair rungs actually fire |
| **Replay** — for each golden build, replay its op list from v0 and assert byte-equality | broken determinism, which silently breaks undo |
| **Loop bounds** — a deliberately impossible request ("a 60-stud tower" with 12 bricks) must terminate within budget and degrade to a *useful* message | infinite loops, token burn, and the worst demo failure mode there is |

Run the golden set before every demo. It takes 90 seconds and it's the difference between knowing
the demo works and hoping.
