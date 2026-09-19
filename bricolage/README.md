# Bricolage — Lane B (build system, reasoning & loops)

`inventory + prompt → validated build + steps + agent tape`. Pure Python, **zero
dependencies** (runs under DEMO_SAFE with wifi off). The LLM sits behind a
one-file provider adapter; a deterministic mock stands in so the whole loop runs
offline. Real Opus drops in by setting `PROVIDER=anthropic` — same output shape.

## Run it

```bash
python bricolage/demo.py     # end-to-end: 6 scenarios + consequences
python bricolage/tests.py    # 16 checks: validator law, invariants, version tree, golden set
python bricolage/server.py   # zero-dep HTTP API + dev console at http://localhost:8017
```

Set `PROVIDER=claude_cli` on any of them to use the authenticated `claude -p`
CLI as the designer instead of the deterministic mock (no API key needed).

## The one rule

> The LLM decides **what** to build. It never places a brick.

The model emits a *composition* — a tree of `generator(args)` + socket names.
Coordinates are computed by `expand()` on an integer grid and checked by
`validate()`, which is ordinary code, not a model.

## Map

| file | what |
|---|---|
| `model.py` | frozen `Build/Part/SubAssembly/Inventory`; integer grid, cells/occupancy |
| `meta.py` | ~20-part whitelist metadata + colours + substitution rules |
| `generators.py` | typed+sized **sockets**, masonry-bond tiler, 8 generators, `expand()` |
| `validate.py` | **the law**: overlap · support (per-component) · connectivity · inventory |
| `substitute.py` | deterministic part-swap search (repair rung 2) |
| `repair.py` | the FIX loop + escalation ladder (rungs 0–4) + budget, logs which rung fixed |
| `sequence.py` | topo order + **insertion sweep** + step grouping → `steps.json` |
| `ldraw.py` | grid → LDraw `.ldr` with `0 STEP` (the only place floats/LDU exist) |
| `edit.py` | the EDIT loop: freeze sockets, re-run one node, children reattach |
| `sculpt.py` | voxel backend (solid stepped shapes, bonded layers) |
| `router.py` | heuristic-first backend routing (compose \| sculpt), LLM fallback |
| `client.py` | provider adapter (anthropic/openai/mock) — `PROVIDER` switches here only |
| `proposer.py` | the mock designer's composition synthesis |
| `pipeline.py` | the whole thing wired: `build_from_prompt()` |
| `session.py` | version tree: build/edit/try-another/undo/redo + byte-identical replay |
| `tape.py` | the streamed agent tape (Contract 4) |
| `serialize.py` | Build/Report/steps → the JSON contracts the frontend consumes |
| `server.py` | zero-dep HTTP API over the session + a self-contained dev console |

## Consequences you can see in the demo

1. **Happy path** — prompt → valid build → sequenced steps → LDraw.
2. **Repair ladder** — adversarial bin (no 2×4s) → rung-2 substitution fixes it
   with **0 LLM calls**. The "% closed without the model" stat is printed.
3. **Honest rejection** — near-empty bin → the verifier spends its budget, then
   tells the truth about what won't fit. No hallucinated floating bricks.
4. **Edit loop** — "make the chassis longer" → cabin + wheels reattach for free.
5. **Determinism** — replay the recorded op → byte-identical LDraw.
6. **Sculpt** — organic-ish shape via the voxel path.
