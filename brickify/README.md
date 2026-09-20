# brickify: idea -> real LEGO model (pipeline C)

Type an idea ("dog", "hummingbird", "house"). Get a model built from real
LDraw parts that stands up, doesn't overlap, and looks like a LEGO set. This is
the app's designer (`./run.sh` at the repo root) and a CLI. How it relates to
the earlier pipelines A and B: `docs/PIPELINES.md`.

## The pipeline

```
idea ─► distill ─► concept ─► 3 briefs at once ─► build+check ─► render ─► pick ─┐
          │           │         │                    ▲                          │
       Claude      OpenAI    Claude              kernel                      Claude
   (make it     (LEGO set   (three designs    (real parts,              (which one reads
   buildable)    photo)      in parallel)      trims overlaps)            best, 0-10)
                    └─► side + back views, drawn while the briefs are written ───┘
```

| Stage | Who | What it does |
|---|---|---|
| distill | Claude (fast) | Rewrites the idea into something buildable: calm pose, chunky shapes, props simplified. "dog holding an umbrella" becomes "sitting dog wearing an umbrella hat". Rules in `DISTILL.md`. |
| concept | OpenAI images | Draws it as an official LEGO set photo. Low quality on purpose: 8s, and blockier art is closer to what the kit can build. |
| views | OpenAI images | The same model from the side and the back, drawn while the briefs are written, so the critic sees every angle for free. |
| briefs | Claude (design) | `--fan` designs at once: small stacked grids per sub-assembly, LEGO colours, connectors (hinges, side studs). Never 3D coordinates. Format in `BRIEF.md`. |
| build | code | Real parts: merge layout (every piece connected), curved-slope surfacing, connector geometry verified against the LDraw library, collision check, and a stability check. Trims the slivers where one sub-assembly reaches into another instead of asking a model. |
| render | code | Four fixed angles of every candidate, one browser, through the web app's `/lab` page. |
| pick | Claude (design) | Compares the candidates with the concept and keeps the one that reads best. `--rounds N` adds critic notes on top. |

Typical run: about 3 minutes, 80-250 parts. Almost all of it is model calls;
building and checking take milliseconds. The dial that matters is how hard the
models think (`BRICKIFY_EFFORT`): see the speed table in `AGENTS.md` before
changing it.

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

Options: `--fan N` (candidate designs, default 3), `--rounds N` (critic notes
after the first build, default 0 - revising the winner scored worse in every
run we measured), `--target 8` (stop early at this score), `--single-view`
(skip side/back views), `--no-distill` (send the idea as-is), `--concept
img.png` (skip image generation), `--edit RUN_DIR` (change a finished model in
plain language).
Env: `BRICKIFY_EFFORT` (thinking for briefs, default `medium`),
`BRICKIFY_JUDGE_EFFORT` (thinking for the critic, default `medium`),
`BRICKIFY_IMAGE_QUALITY` (`low`, `medium`, `high`; default `low`),
`ANTHROPIC_API_KEY` (use the API instead of the `claude` CLI),
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
