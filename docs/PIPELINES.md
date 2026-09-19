# Design pipelines: A, B and C

How the app turns "a dog" into a LEGO model. Two approaches were built in
parallel (A and B); C merges the best of both and is what the app runs.

| | A: layer builder | B: brickify | **C: current** |
|---|---|---|---|
| Where | `bricolage/agents.py` | `brickify/` | `brickify/` + `bricolage/engine_c.py` |
| Archived as | tag `archive/pipeline-a` | tag `archive/pipeline-b` | `main` |
| Who places bricks | the model (BrickGPT grammar, band by band) | code, from the model's brief | code, from the model's brief |
| Parts | 1-brick-tall rectangular bricks | real LDraw parts: plates, bricks, curved slopes, hinges, side studs, bars | same as B |
| Sees a picture first | no | yes: concept + side/back views (Codex) | yes |
| Checks | lint, connectivity, force/torque, vision score | collisions, connectivity, vision critique rounds | B's checks + **stands** (centre of mass over the base) |
| Streams to the app | yes, each band | no (CLI only) | yes, every tape event and every built round |
| Edits ("Change it") | Lane B edit ops | none | revises the brief in plain language, rebuilds |

## Why C looks like it does

- **B's core wins on looks.** A model placing bricks one by one gives blobs
  and overlaps; a model describing shapes on small grids, with code placing
  real parts (slopes, hinges, side studs), reads as a LEGO set. Concept images
  make the brief concrete.
- **From A:**
  - Keep the model calls lean. With `ANTHROPIC_API_KEY` set, C calls the API
    directly with the images attached; without one it falls back to headless
    `claude` from an empty directory with no MCP servers. (A measured 40-70s of
    per-call overhead from the repo cwd on its machine; on ours that gap was
    2-3s, but a clean prompt and no MCP stall risk are worth having anyway.)
  - The fast model does the small steps (distill, repair) and the strong model
    does design and judgement.
  - A stability gate.
  - Live streaming of each built round to the create screen.
  - No silent fallbacks: a failed run is an error, never a canned model.
- **Not taken from A:** colour by band role (C's colours come from the concept
  image, which is better) and the BrickGPT grammar.

## Run them side by side

```bash
# C, the default
./run.sh                                   # the app (http://localhost:3000)
cd brickify && uv run python -m brickify.pipeline "dog"     # CLI

# A, in the same checkout
ENGINE=a ./run.sh

# exact archived snapshots, in their own folders
git worktree add ../htn-a archive/pipeline-a
git worktree add ../htn-b archive/pipeline-b
```

Compare by running the same ideas through each and looking at the renders in
`brickify/runs/<run>/views-rN/` (C and B) or the app (A).
