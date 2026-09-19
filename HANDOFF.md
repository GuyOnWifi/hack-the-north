# Handoff — Lane B → UI

Everything the UI needs to integrate. Lane B (build system) is done and tested
(`PROVIDER=mock uv run --project brickify python bricolage/tests.py` → 33/33).

## Run the full demo stack

```bash
./run.sh          # builds the web app if needed, starts API (:8017) + app (:3000)
```
The designer is pipeline C (`brickify/`, see `docs/PIPELINES.md`): it needs
`uv`, the `claude` CLI and `codex login`. `ENGINE=a ./run.sh` runs the archived
layer builder instead; `PROVIDER=mock ./run.sh` is offline and instant.

## Fastest path: the live API

```bash
python bricolage/server.py          # http://localhost:8017  (open it — dev console works)
PROVIDER=claude_cli python bricolage/server.py   # use the real LLM designer (no key needed)
DEMO_SAFE=1 python bricolage/server.py           # force offline mock (wifi-dead insurance)
```

### Endpoints (all JSON, CORS open)
| method | path | body | returns |
|---|---|---|---|
| POST | `/api/build` | `{"prompt": "..."}` | `{version, build, report, steps, tape, tree}` |
| GET  | `/api/build_stream?prompt=...` | — | **SSE**: one tape event per `data:` line, then a final `{event:"done", ...}` |
| POST | `/api/edit` | `{"text": "make the chassis longer"}` | same payload shape |
| POST | `/api/try_another` | `{}` | re-runs the current op with a new seed (a sibling version) |
| POST | `/api/undo` / `/api/redo` | `{}` | moves the version-tree head |
| GET  | `/api/state` | — | current payload |
| GET  | `/api/ldr` | — | current model as **LDraw text** (feed three.js `LDrawLoader`) |
| GET  | `/api/compare?prompt=...` | — | **split-screen**: `{naive, verified}`, each `{build, report, physics}` — render side by side |

### New: physics + split-screen (the wow views)
- **Every payload now has `physics`**: `{stable, com:[x,z], base:[[x,z]...], topple_margin, failures[]}`.
  Draw the **centre-of-mass dot** at `com` and the **support polygon** through `base`
  (on the ground plane). Green when `stable`, red + show `failures[].human` when not.
- **`/api/compare`** returns the same request built two ways: `naive` ("LLM places
  bricks" — floating, disconnected, its `report.errors` full) vs `verified` (our
  solver — clean). Render both models side by side; it's the "not a GPT wrapper"
  money shot. On `build me a flower`, naive has ~12 floating parts; verified is valid.
- Colours: `physics`/`build` use LDraw colour codes; exact sRGB is in
  `bricolage/meta.py` `COLOR_RGB` (baked from the real `LDConfig.ldr`).

## The data shapes (also frozen as files in `fixtures/`)

- `fixtures/build.json` — the Build: `parts[]` each `{id, part, color, pos:[x,y,z], rot, sub}`
  - `part` = LDraw part number, `color` = LDraw colour code
  - grid units: x/z = studs, y = plates, +y up. Convert with the same math as `bricolage/ldraw.py` (or just use `/api/ldr`).
- `fixtures/report.json` — `{ok, errors[], warnings[], stats}`; render `error.human` / `warning.human` **verbatim** (they're written as UI copy).
- `fixtures/steps.json` — `{n_steps, steps[]}`; each step `{n, sub, layer, parts:[ids], elements}`.
- `fixtures/model.ldr` — full model with `0 STEP` separators (LDrawLoader reads steps natively).
- `fixtures/tape.sse` — a captured agent tape; each event `{t, actor, kind, text, status, ms, tokens}`.
  - `actor ∈ designer|inspector|repair|scribe|router` · `status ∈ ok|fail|warn|running`

## Rendering notes
- **3D**: three.js ships `LDrawLoader`; point it at `/api/ldr` (or `model.ldr`). Needs the LDraw parts library — it's at `~/ldraw` on this machine.
- **Colours**: `bricolage/meta.py` has `COLOR_RGB` (LDraw code → sRGB) for a quick map; the authoritative table is `~/ldraw/LDConfig.ldr`.
- **The tape is the money shot** — stream `/api/build_stream` and render events as they arrive (the dev console in `server.py` shows one way, ~40 lines of JS).

## Don't need the server?
Import directly: `from pipeline import build_from_prompt` (in `bricolage/`). See
`bricolage/README.md` for the module map and `STATUS.md` for what's built.
