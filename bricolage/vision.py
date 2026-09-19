"""Vision-in-the-loop: the agent RENDERS what it imagined, LOOKS at it with a
multimodal model, and corrects it. This is what turns blind voxel-blobs into
something that actually reads as the thing you asked for.

  imagine mask -> render PNG -> "does this look like a <X>?" (with the image)
    -> corrected mask -> re-render -> repeat

Needs the real multimodal model (claude -p reads images via @path). No-ops
gracefully when it isn't available, so the mock path still works offline.
"""
from __future__ import annotations
import os
import subprocess

from render import render_build
from sculpt import build_voxels


def available():
    return os.environ.get("PROVIDER", "mock") in ("claude_cli", "claude-cli", "cli")


def _critique(image_path, prompt):
    """Show the render to the model. Returns {looks_right, critique, grid}."""
    from client import _first_json
    ask = (f"@{image_path}\n"
           f"This is a top-down render of LEGO pixel art meant to be: "
           f"\"{prompt}\". Study it. Does it clearly read as that? Reply with ONE "
           "JSON object, no prose:\n"
           '{"looks_right": true|false, "critique": "<=12 words on what is wrong", '
           '"grid": ["row","row", ...] }\n'
           "grid = a CORRECTED pixel-art picture (or null if it already looks "
           "right). Each row is an equal-length string; each char is a colour: "
           "r=red o=orange y=yellow g=green b=blue w=white k=black n=brown t=tan "
           "a=gray, .=empty. Draw the whole SOLID silhouette, centred, filled "
           "(not an outline), using colour to make it recognisable.")
    try:
        out = subprocess.run(["claude", "-p", ask], capture_output=True,
                             text=True, timeout=110)
        data = _first_json(out.stdout)
        if not data:
            return None
        grid = data.get("grid") or data.get("rows")
        if grid and isinstance(grid[0], list):
            grid = grid[0]
        return {"looks_right": bool(data.get("looks_right")),
                "critique": str(data.get("critique", ""))[:120],
                "grid": grid}
    except Exception:
        return None


def refine(build, voxels, prompt, tape, render_dir, rounds=2, seed=0):
    """Look-and-fix loop. Returns the best build. Streams to the tape so the
    judge watches the agent critique its own work."""
    if not available():
        return build
    from sculpt import parse_mask
    from validate import validate
    best = build
    for i in range(rounds):
        img = os.path.join(render_dir, f"look_{i}.png")
        render_build(best, img, view="top")   # plan view reads the picture clearly
        tape.emit("designer", "look", f"rendering and looking at my '{prompt}'…",
                  ms=1500, tokens=900)
        verdict = _critique(img, prompt)
        if not verdict:
            break
        if verdict["looks_right"] or not verdict.get("grid"):
            tape.emit("inspector", "vision",
                      f"looks right: {verdict['critique'] or 'matches the request'}",
                      status="ok", ms=1200)
            break
        tape.emit("inspector", "vision", f"not yet: {verdict['critique']}",
                  status="warn", ms=1200)
        try:
            voxels = parse_mask(verdict["grid"])
            if not voxels:
                break
            candidate = build_voxels(voxels, name=best.name, tape=None, seed=seed)
            rep = validate(candidate, physics=False)
            if any(e["code"] == "DISCONNECTED" for e in rep.errors) or len(candidate.parts) < 6:
                tape.emit("repair", "reject-revision",
                          "that redraw wouldn't hold together — keeping the "
                          "previous version", status="warn", ms=8)
                continue
            best = candidate
            tape.emit("designer", "revise", "redrew it from what I saw", ms=400)
        except Exception:
            break
    return best
