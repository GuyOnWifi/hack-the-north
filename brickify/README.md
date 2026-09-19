# brickify: idea -> real LEGO model

Type an idea ("dog", "hummingbird", "house"). Get a model built from real
LDraw parts that stands up, doesn't overlap, and looks like a LEGO set, shown
in the web app at `/lab?m=<name>`.

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
| distill | Claude | Rewrites the idea into something buildable: calm pose, chunky shapes, props simplified. "dog holding an umbrella" becomes "sitting dog wearing an umbrella hat". Rules in `DISTILL.md`. |
| concept | Codex | Draws it as an official LEGO set photo (`codex exec`, ChatGPT login, no API key). |
| views | Codex | Redraws the same model from the side and back, using the concept as a reference image, so the designer sees depth. |
| brief | Claude | Reads the images and writes the build brief: small stacked grids per sub-assembly, LEGO colours, connectors (hinges, side studs). Never 3D coordinates. Format in `BRIEF.md`. |
| build | code | Assembles real parts: merge layout (every piece connected), curved-slope surfacing, connector geometry verified against the LDraw library, world collision check. Rejected briefs go back to Claude with the reasons. |
| render | code | Four fixed angles through the web app's `/lab` page (headless Chromium). |
| critique | Claude | Compares renders with the concept views, scores 0-10, returns a revised brief. Repeats; the best round wins. |

Typical run: 6-10 minutes, 100-260 parts. Almost all of the time is model
calls; building and checking take milliseconds.

## Setup (once)

```bash
# 1. Python deps (uv: https://docs.astral.sh/uv/)
cd brickify && uv sync

# 2. The web app renders the models
cd ../web && npm install && npx playwright install chromium

# 3. Model CLIs, signed in with your own accounts
#    Claude Code: https://claude.com/claude-code  (the `claude` command)
npm i -g @openai/codex && codex login     # sign in with ChatGPT
```

## Run

```bash
# terminal 1: the web app (the pipeline renders through it)
cd web && npm run dev -- -p 3210

# terminal 2
cd brickify
uv run python -m brickify.pipeline "dog"
uv run python -m brickify.pipeline "hummingbird" --concept concepts/hummingbird-gemini.png --rounds 1
```

Open the printed URL, e.g. http://localhost:3210/lab?m=dog. Everything the run
did is in `runs/<name>/`: `tape.jsonl` (step log), `distilled.json`,
`brief-N.json`, `views-rN/*.png`, `result.json`.

Options: `--rounds N` (critique rounds, default 2), `--target 8` (stop early at
this score), `--single-view` (skip side/back views), `--no-distill` (send the
idea as-is), `--concept img.png` (skip image generation).
Env: `BRICKIFY_MODEL` (Claude model, default `claude-opus-5`), `BRICKIFY_WEB`
(web app URL, default `http://localhost:3210`).

## Other entry points

```bash
uv run python -m brickify briefs/hummingbird.json out/hb.ldr   # build a hand-written brief
uv run python -m brickify meshes/bunny.ply --length 32         # mesh -> bricks (sculpture mode)
```

## Map

| File | What |
|---|---|
| `brickify/pipeline.py` | the design loop above (stages are plain functions) |
| `brickify/assembly.py` | brief -> placed parts: bodies, connectors, details, surfacing |
| `brickify/kit.py` | part geometry (verified against LDraw) and placement maths |
| `brickify/merge.py` | connectivity-first brick layout (no loose pieces) |
| `brickify/check.py` | world collision check; cosmetic slopes yield to structure |
| `BRIEF.md` / `DISTILL.md` | the specs the models write against |
| `briefs/` | hand-written reference briefs |
| `web/scripts/render-views.mjs` | fixed-angle renders for the critic |
| `web/scripts/build-ldraw-pack.mjs` | bundles the parts the kit uses (re-run after adding parts) |
