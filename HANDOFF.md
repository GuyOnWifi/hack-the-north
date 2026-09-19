# Handoff — Lane B → UI

Everything the UI needs to integrate. Lane B (build system) is done and tested
(`python bricolage/tests.py` → 26/26). Pure Python, **zero dependencies**.

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
