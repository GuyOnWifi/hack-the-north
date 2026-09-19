# brickify: idea -> real LEGO model (pipeline C)

Type an idea ("dog", "hummingbird", "house"). Get a model built from real
LDraw parts that stands up, doesn't overlap, and looks like a LEGO set. This is
the app's designer (`./run.sh` at the repo root) and a CLI. How it relates to
the earlier pipelines A and B: `docs/PIPELINES.md`.

## The pipeline

```
idea ─► distill ─► concept ─► side/back views ─► brief ─► build ─► render ─► critique ─┐
          │           │              │              │        ▲                          │
       Claude      Codex          Codex          Claude      └──── revised brief ◄──────┘
   (make it     (LEGO set     (same model,   (grids, colours,   kernel + checker      Claude
   buildable)    photo)       new angles)     connectors)       (real parts only)   (score 0-10)
```

| Stage | Who | What it does |
|---|---|---|
| distill | Claude (fast) | Rewrites the idea into something buildable: calm pose, chunky shapes, props simplified. "dog holding an umbrella" becomes "sitting dog wearing an umbrella hat". Rules in `DISTILL.md`. |
| concept | Codex | Draws it as an official LEGO set photo (`codex exec`, ChatGPT login, no API key). |
| views | Codex | Redraws the same model from the side and back, using the concept as a reference image, so the designer sees depth. |
| brief | Claude (design) | Reads the images and writes the build brief: small stacked grids per sub-assembly, LEGO colours, connectors (hinges, side studs). Never 3D coordinates. Format in `BRIEF.md`. |
| build | code | Assembles real parts: merge layout (every piece connected), curved-slope surfacing, connector geometry verified against the LDraw library, world collision check, and a stability check (centre of mass over the base). Rejected briefs go back to Claude (fast) with the reasons. |
| render | code | Four fixed angles through the web app's `/lab` page (headless Chromium). |
| critique | Claude (design) | Compares renders with the concept views, scores 0-10, returns a revised brief. Repeats; the best round wins. |

Typical run: 6-10 minutes, 100-260 parts. Almost all of the time is model
calls; building and checking take milliseconds.

## Setup (once)

```bash
# 1. Python deps (uv: https://docs.astral.sh/uv/)
cd brickify && uv sync

# 2. The web app renders the models
cd ../web && npm install && npx playwright install chromium

# 3. Model access
#    Claude: either an API key (faster) or the `claude` CLI login.
echo 'ANTHROPIC_API_KEY=sk-ant-...' > brickify/.env.local   # gitignored
#    ...or install Claude Code (https://claude.com/claude-code) and sign in.
#    Images: Codex, signed in with ChatGPT (no key needed).
npm i -g @openai/codex && codex login
```

With `ANTHROPIC_API_KEY` set (in `.env.local` or the environment) brickify
calls the API directly and attaches the images to each request. Without one it
shells out to `claude -p` and the run works the same, just slower.

## Run

In the app: `./run.sh` at the repo root, then type an idea on the home screen.
The create screen streams every step and shows each built round.

CLI (the web app must be running; the renderer goes through its `/lab` page):

```bash
cd brickify
uv run python -m brickify.pipeline "dog"
uv run python -m brickify.pipeline "hummingbird" --concept concepts/hummingbird-gemini.png --rounds 1
uv run python -m brickify.pipeline --edit runs/<run> "make the ears longer"
```

Each run gets its own folder, `runs/<date>-<time>-<name>/`, so runs can go in
parallel: `tape.jsonl` (step log), `distilled.json`, `concept*.png`,
`brief-N.json`, `rN.ldr`, `views-rN/*.png`, `result.json`. The CLI also copies
the winner to `web/public/lab/<name>.ldr` and prints its `/lab?m=<name>` URL.

Options: `--rounds N` (critique rounds, default 2), `--target 8` (stop early at
this score), `--single-view` (skip side/back views), `--no-distill` (send the
idea as-is), `--concept img.png` (skip image generation), `--edit RUN_DIR`
(change a finished model in plain language).
Env: `ANTHROPIC_API_KEY` (use the API instead of the `claude` CLI),
`BRICKIFY_MODEL` (design model, default `claude-opus-5`), `BRICKIFY_FAST`
(distill and repair, default `claude-sonnet-5`), `BRICKIFY_WEB` (web app URL,
default `http://localhost:3000`), `BRICKIFY_RUNS` (where runs go).

## Other entry points

```bash
uv run python -m brickify briefs/hummingbird.json out/hb.ldr   # build a hand-written brief
uv run python -m brickify meshes/bunny.ply --length 32         # mesh -> bricks (sculpture mode)
```

## Map

| File | What |
|---|---|
| `brickify/pipeline.py` | the design loop above (stages are plain functions), plus `edit()` |
| `../bricolage/engine_c.py` | plugs this pipeline into the app's API (streaming, steps, edits) |
| `brickify/assembly.py` | brief -> placed parts: bodies, connectors, details, surfacing |
| `brickify/kit.py` | part geometry (verified against LDraw) and placement maths |
| `brickify/merge.py` | connectivity-first brick layout (no loose pieces) |
| `brickify/check.py` | world collision check (cosmetic slopes yield to structure) and `stands()` |
| `BRIEF.md` / `DISTILL.md` | the specs the models write against |
| `briefs/` | hand-written reference briefs |
| `web/scripts/render-views.mjs` | fixed-angle renders for the critic |
| `web/scripts/build-ldraw-pack.mjs` | bundles the parts the kit uses (re-run after adding parts) |
