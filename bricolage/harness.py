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

import bricks
import physics
from meta import NAME_TO_CODE

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
    out = subprocess.run(["claude", "-p", _fewshot_prompt(prompt)],
                         capture_output=True, text=True, timeout=150)
    return bricks.parse(out.stdout)


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
    """Emit a rolling 'designer is thinking' trace every few seconds until the
    LLM call returns, so a 60-130s claude -p wait shows life, not a spinner."""
    i = 0
    while not stop.wait(6.0):
        tape.emit("designer", "think", _THINKING[i % len(_THINKING)],
                  ms=0, tokens=180)
        i += 1


def _propose(prompt, tape=None):
    """Get a brick proposal, degrading gracefully: real LLM if available, else
    the offline 3D fallback. A failed/empty LLM call never propagates — it falls
    back so the stream always finishes with a real structure."""
    if available():
        import threading
        stop = threading.Event()
        if tape:
            threading.Thread(target=_think_while, args=(prompt, tape, stop),
                             daemon=True).start()
        try:
            items = _propose_claude(prompt)
            if items:
                return items
            if tape:
                tape.emit("designer", "propose", "model returned no bricks — "
                          "using the offline 3D fallback", status="warn", ms=2)
        except Exception as e:
            if tape:
                tape.emit("designer", "propose", f"designer call failed "
                          f"({type(e).__name__}) — using the offline 3D fallback",
                          status="warn", ms=2)
        finally:
            stop.set()          # halt the thinking trace the moment the LLM returns
    return _propose_mock(prompt)


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
    """Drop bricks with no support (nothing below / not ground), then keep
    dropping the physically worst bricks until the force-balance check passes."""
    # 1) support pass: bottom-up, keep only bricks resting on something
    items = sorted(items, key=lambda b: b[4])
    occ, kept = {}, []
    ground_z = min((b[4] for b in items), default=0)
    for (h, w, x, y, z) in items:
        supported = z == ground_z or any((x + dx, y + dy, z - 1) in occ
                                          for dx in range(h) for dy in range(w))
        if supported:
            for dx in range(h):
                for dy in range(w):
                    occ[(x + dx, y + dy, z)] = True
            kept.append((h, w, x, y, z))
    dropped = 0
    # 2) physics pass: if unstable, drop the highest bricks until it stands
    for _ in range(40):
        if physics.analyze(kept)["stable"] or len(kept) < 4:
            break
        top_z = max(b[4] for b in kept)
        before = len(kept)
        kept = [b for b in kept if b[4] < top_z]     # shed the top layer
        dropped += before - len(kept)
    if tape and dropped:
        tape.emit("repair", "shed", f"physics: shed {dropped} brick(s) that "
                  f"wouldn't hold, until it stands", ms=8)
    return kept


def build(prompt, name=None, tape=None, seed=0):
    """prompt -> a validated, stable, coloured 3D Build."""
    from tape import Tape
    tape = tape or Tape()
    tape.emit("designer", "think", f"planning a 3D build for '{prompt}'…",
              ms=1600, tokens=2000)
    items = _normalize(_propose(prompt, tape))
    tape.emit("designer", "propose", f"proposed {len(items)} bricks in 3D", ms=300)

    kept, issues = bricks.lint(items)
    for iss in issues[:4]:
        tape.emit("inspector", "reject", f"{iss['code']}: {iss['why']}",
                  status="warn", ms=3)
    if len(issues) > 4:
        tape.emit("inspector", "reject", f"…and {len(issues) - 4} more invalid bricks",
                  status="warn", ms=2)

    kept = _stabilize(kept, tape)
    # junk guard: if almost nothing survived lint+physics, the proposal was
    # garbage (apology text, all-collisions). Rebuild from the solid fallback so
    # the user never gets an "ok" 2-brick blob.
    if len(kept) < 6:
        tape.emit("inspector", "reject", f"only {len(kept)} brick(s) held up — "
                  f"rebuilding from a solid fallback", status="warn", ms=3)
        kept = _stabilize(bricks.lint(_normalize(_propose_mock(prompt)))[0], tape)
    res = physics.analyze(kept)
    tape.emit("inspector", "physics",
              f"force + torque check: {'stands up' if res['stable'] else 'would topple'} "
              f"({res.get('studs', 0)} stud joints)",
              status="ok" if res["stable"] else "warn", ms=45)

    return bricks.to_build(kept, name=name or prompt.title(), color=_color_for(prompt))
