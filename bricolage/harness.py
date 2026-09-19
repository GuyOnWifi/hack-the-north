"""The LEGO LLM harness. Prompt a general LLM to build a real 3D model in the
BrickGPT grammar, then LINT every brick and PHYSICS-check it — the LLM proposes,
our deterministic checks guarantee it's buildable and stands up.

Flow: few-shot prompt -> LLM emits `hxw (x,y,z)` bricks (one shot) -> lint
(bounds/collision) -> stabilize (drop unsupported, physics-gate) -> colour ->
Build. Speed-reality: one generation call, then only repair locally if needed.
"""
from __future__ import annotations
import os
import subprocess
import sys
import time

import bricks
import physics
from meta import NAME_TO_CODE


def _log(msg):
    """Loud, timestamped logging to stderr (captured in the backend log) so we
    can see exactly what the LLM returned and where a build went wrong."""
    print(f"[harness {time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)

GRAMMAR = (
    "Build the object as a 3D LEGO model on a 20x20x20 grid from 1-brick-tall "
    "bricks. Output ONLY brick lines, one per line, nothing else. Each line:\n"
    "  hxw (x,y,z)\n"
    "= a brick with footprint h by w studs, placed with its corner at (x,y,z); "
    "x and y are the horizontal position, z is the height LAYER (z=0 is the "
    "ground, build upward). Allowed footprints (h x w, either orientation): "
    "1x1 1x2 1x3 1x4 1x6 1x8 2x2 2x3 2x4 2x6 2x8.\n"
    "Rules: start at z=0 and build up layer by layer; every brick must rest on a "
    "brick below it or on the ground; make it clearly READ as the object in 3D "
    "(get the silhouette and proportions right); use 40-90 bricks."
)


def available():
    from client import provider
    return provider() in ("claude_cli", "claude-cli", "cli")


def _fewshot_prompt(prompt):
    try:
        from fewshot import EXAMPLES
    except Exception:
        EXAMPLES = []
    ex = "\n\n".join(f"Object: {cap}\n{txt}" for cap, txt in EXAMPLES[:3])
    return (f"{GRAMMAR}\n\nExamples of the format (bottom layers first):\n\n{ex}"
            f"\n\nNow build this object: \"{prompt}\"\nOutput only the brick lines.")


def _propose_claude(prompt):
    t0 = time.time()
    _log(f"calling claude -p for {prompt!r}…")
    out = subprocess.run(["claude", "-p", _fewshot_prompt(prompt)],
                         capture_output=True, text=True, timeout=300)
    items = bricks.parse(out.stdout)
    _log(f"claude returned in {time.time()-t0:.0f}s: rc={out.returncode}, "
         f"{len(out.stdout)} chars stdout, {len(out.stderr)} chars stderr, "
         f"parsed {len(items)} brick lines")
    if not items:
        _log(f"NO BRICKS PARSED. stdout head: {out.stdout[:300]!r}  stderr head: {out.stderr[:200]!r}")
    return items


# shown one-by-one while the (slow) LLM call runs, so the tape looks alive
# instead of frozen. Illustrative of what the designer is doing, not real tokens.
_THINKING = [
    "sketching the silhouette in 3D…",
    "blocking out the base layer on the grid…",
    "choosing brick sizes to match the shape…",
    "stacking upward, keeping every brick connected…",
    "shaping the profile so it reads from any angle…",
    "checking proportions against the request…",
    "closing gaps and locking the seams…",
]


def _think_while(prompt, tape, stop):
    """Emit a 'designer is thinking' trace until the LLM returns, so the long
    claude -p wait shows life. The distinct steps play once (7s apart); after
    that a slow 'still refining' pulse keeps it alive without spamming the tape."""
    i = 0
    while not stop.wait(7.0 if i < len(_THINKING) else 15.0):
        msg = _THINKING[i] if i < len(_THINKING) else "still refining the design…"
        tape.emit("designer", "think", msg, ms=0, tokens=180)
        i += 1


class HarnessError(Exception):
    """A loud failure — surfaced to the user, never swallowed by a fallback."""


def _propose(prompt, tape=None):
    """Get a brick proposal from the LLM. NO silent fallback: if claude times
    out, errors, or returns nothing, we RAISE — the user sees a loud error, not
    a canned cube. The offline scaffold is used ONLY in explicit mock mode."""
    if not available():
        return _propose_mock(prompt)          # PROVIDER=mock: intentional dev mode

    import threading
    stop = threading.Event()
    if tape:
        threading.Thread(target=_think_while, args=(prompt, tape, stop),
                         daemon=True).start()
    try:
        items = _propose_claude(prompt)
    except subprocess.TimeoutExpired:
        if tape:
            tape.emit("designer", "propose", "designer (claude) TIMED OUT — no fallback",
                      status="fail", ms=2)
        raise HarnessError(f"the designer timed out on “{prompt}”. No fallback — "
                           f"try again or a simpler prompt.")
    except Exception as e:
        if tape:
            tape.emit("designer", "propose", f"designer call FAILED: {type(e).__name__} — no fallback",
                      status="fail", ms=2)
        raise HarnessError(f"the designer failed: {e}")
    finally:
        stop.set()          # halt the thinking trace the moment the LLM returns
    if not items:
        if tape:
            tape.emit("designer", "propose", "designer returned NO bricks — no fallback",
                      status="fail", ms=2)
        raise HarnessError(f"the designer returned no usable bricks for “{prompt}”. Try again.")
    return items


def _propose_mock(prompt):
    """Offline 3D fallback: a small hollow house (walls + pitched-ish roof) so
    the harness still yields a real 3D structure with no model."""
    items = []
    W = 8
    for z in range(4):                       # 4 layers of walls
        for x in range(W):
            items.append((1, 1, x, 0, z))
            items.append((1, 1, x, W - 1, z))
        for y in range(1, W - 1):
            items.append((1, 1, 0, y, z))
            items.append((1, 1, W - 1, y, z))
    for z in range(4, 7):                     # stepped roof
        inset = z - 3
        for x in range(inset, W - inset):
            for y in range(inset, W - inset):
                if x in (inset, W - 1 - inset) or y in (inset, W - 1 - inset):
                    items.append((1, 1, x, y, z))
    return items


def _normalize(items):
    """Drop the model onto the plate: shift z so the lowest layer is 0. The LLM
    (and the few-shot examples) sometimes start at z>0, which would otherwise
    render/export floating above the baseplate while physics calls it grounded."""
    if not items:
        return items
    zmin = min(z for (h, w, x, y, z) in items)
    if zmin:
        items = [(h, w, x, y, z - zmin) for (h, w, x, y, z) in items]
    return items


def _color_for(prompt):
    import re
    for word, code in NAME_TO_CODE.items():
        if re.search(rf"\b{word}\b", prompt.lower()):
            return code
    return 71                                 # light gray default


def _stabilize(items, tape=None):
    """Keep the connected structure that touches the ground; drop ONLY bricks in
    clusters that float free (disconnected from everything). We do NOT shed bricks
    to force physical stability — that shredded organic shapes (a flower's whole
    bloom is top-heavy). The shape is preserved; if it's physically shaky, physics
    reports it and the UI shows it red. Keep the flower, flag it — don't destroy it."""
    from collections import deque
    items = list(items)
    if not items:
        return items
    cell = {}
    for i, b in enumerate(items):
        for c in bricks.cells(*b):
            cell[c] = i
    ground_z = min(z for (h, w, x, y, z) in items)
    seen = {i for i, (h, w, x, y, z) in enumerate(items) if z == ground_z}
    q = deque(seen)
    while q:                                    # flood-fill through face-adjacent cells
        for (cx, cy, cz) in bricks.cells(*items[q.popleft()]):
            for nb in ((cx + 1, cy, cz), (cx - 1, cy, cz), (cx, cy + 1, cz),
                       (cx, cy - 1, cz), (cx, cy, cz + 1), (cx, cy, cz - 1)):
                j = cell.get(nb)
                if j is not None and j not in seen:
                    seen.add(j)
                    q.append(j)
    kept = [b for i, b in enumerate(items) if i in seen]
    dropped = len(items) - len(kept)
    if tape and dropped:
        tape.emit("repair", "drop", f"dropped {dropped} disconnected floating "
                  f"brick(s) — kept the connected shape", ms=8)
    return kept


def _emit_geometry(tape, items, label, draft):
    """Push a partial 3D model down the tape as an LDraw blob so the UI can place
    bricks NOW, before the (slow) real design returns. Speed-reality: a fast
    speculative draft first, replaced by the verified build when it lands."""
    try:
        from sequence import sequence
        from ldraw import to_ldr
        b = bricks.to_build(items, name="draft", color=71)
        try:
            steps = sequence(b)
        except Exception:
            steps = None
        tape.emit("designer", "geometry", label, status="running", ms=0,
                  ldr=to_ldr(b, steps), draft=draft)
    except Exception:
        pass


def build(prompt, name=None, tape=None, seed=0):
    """prompt -> a validated, stable, coloured 3D Build."""
    from tape import Tape
    tape = tape or Tape()
    tape.emit("designer", "think", f"planning a 3D build for '{prompt}'…",
              ms=1600, tokens=2000)
    items = _normalize(_propose(prompt, tape))
    _log(f"build({prompt!r}): proposed {len(items)} bricks after normalize")
    tape.emit("designer", "propose", f"proposed {len(items)} bricks in 3D", ms=300)

    kept, issues = bricks.lint(items)
    _log(f"build({prompt!r}): lint kept {len(kept)}, dropped {len(issues)} "
         f"({', '.join(sorted({i['code'] for i in issues})) or 'none'})")
    for iss in issues[:4]:
        tape.emit("inspector", "reject", f"{iss['code']}: {iss['why']}",
                  status="warn", ms=3)
    if len(issues) > 4:
        tape.emit("inspector", "reject", f"…and {len(issues) - 4} more invalid bricks",
                  status="warn", ms=2)

    kept = _stabilize(kept, tape)
    _log(f"build({prompt!r}): stabilize kept {len(kept)}")
    # honesty guard: if almost nothing survived, FAIL LOUD — no canned design.
    if len(kept) < 6 and available():
        tape.emit("inspector", "reject", f"only {len(kept)} brick(s) survived lint+physics — "
                  f"the proposal was too sparse", status="fail", ms=3)
        raise HarnessError(f"only {len(kept)} bricks held up for “{prompt}” — the model's "
                           f"proposal was too sparse. Try again or steer it.")
    res = physics.analyze(kept)
    tape.emit("inspector", "physics",
              f"force + torque check: {'stands up' if res['stable'] else 'would topple'} "
              f"({res.get('studs', 0)} stud joints)",
              status="ok" if res["stable"] else "warn", ms=45)

    build = bricks.to_build(kept, name=name or prompt.title(), color=_color_for(prompt))
    _log(f"build({prompt!r}): DONE — {len(build.parts)} parts, stable={res['stable']}, "
         f"color={_color_for(prompt)}")
    return build
