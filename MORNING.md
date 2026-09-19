# Good morning — here's what happened overnight

_Everything is on the branch **`integration/wow`** (main + your teammate's `lane-c/frontend`
merged, plus the night's work). Nothing was pushed to `main` — review, then merge when happy._

## TL;DR
Your project pivoted from "too simple / GPT wrapper / Brickit exists" to something with a
real, defensible core, and it's **verified working end-to-end**: `python bricolage/tests.py`
→ **33/33**, `next build` compiles clean, and a build through the app returns a valid,
physics-stable model with a live agent tape.

## What I built while you slept
1. **Fixed the 3 integration bugs** your teammate found (truck overlap, empty edit-tape,
   substitution gaps) — plus a live crash (repair now degrades instead of throwing when the
   LLM proposes something invalid).
2. **Real physics** (`bricolage/stability.py`): center-of-mass vs. support-polygon (topple)
   + stud-clutch overhang (joint rip). It **rejects** a connected-but-leaning build, **self-
   repairs** a toppling one (adds a foundation), and scores **sturdiness 0–10** with a
   weakest-joint callout.
3. **"Build anything"** (`sculpt.py`): "build me a flower" → the LLM imagines a voxel shape,
   the solver adds support columns under overhangs, tiles with a bonded grid, verifies — and
   streams every step. Works live via `claude -p` (no API key) for arbitrary requests.
4. **The split-screen** (`/api/compare`): the same request as "LLM places bricks" (floating,
   falls apart) next to our verified build. The "not a GPT wrapper" money shot.
5. **Exact LDraw colours** baked from the real `~/ldraw/LDConfig.ldr`.
6. **Verified the full stack runs** (frontend proxy → backend → build/compare all reachable).

## The doc you asked for
**`docs/DESIGN.md`** — every design decision in your own voice, with the justification, the
prize-track strategy, the 3-minute demo order, and the exact answers to the judge questions
you'll get ("isn't this a wrapper?", "how is this different from Brickit?"). Read it before
the demo; it's written so the choices read as yours.

## Run the demo (two terminals)
```bash
python bricolage/server.py                       # backend  (PROVIDER=claude_cli for real LLM)
cd web && npm install && npm run build && BRICOLAGE_URL=http://127.0.0.1:8017 npm start
# open http://localhost:3000   (the app is "Brickbook")
```

## Decisions for you (I didn't want to make these unilaterally)
- **Merge `integration/wow` → `main`?** It's your teammate's UI + my Lane B work; tests
  green, build clean. I kept it on a branch so you review first.
- **The split-screen + physics views are backend-ready but need a frontend screen.**
  Everything's in `HANDOFF.md` (endpoints, the `physics` payload with `com`/`base`/
  `sturdiness`). That's the highest-leverage thing left for the frontend — it's the wow view.
- **Prize aim:** point the pitch at the agentic/reliability track (the tape is the exhibit).
  Rationale in `docs/DESIGN.md`.

## Loop status
I kept a background loop running to re-merge any further UI pushes and do light polish. It'll
stop on its own; I'll send a push notification with the final state.
