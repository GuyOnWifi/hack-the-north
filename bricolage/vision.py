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
    """Show the render to the model. Returns {looks_right, critique, layers}."""
    from client import _first_json
    ask = (f"@{image_path}\n"
           f"This is an isometric render of a LEGO model that is supposed to be: "
           f"\"{prompt}\". Study the image. Judge whether it actually reads as "
           f"that. Reply with ONE JSON object and nothing else:\n"
           '{"looks_right": true|false, "critique": "<=12 words on what is wrong", '
           '"layers": [["##.","###"], ...] }\n'
           "layers = a CORRECTED voxel model, bottom layer first, each layer a "
           "list of equal-length rows of '#'(brick) or '.'(empty), max 8x8. Use "
           "null if it already looks right. RULES so it holds together as real "
           "LEGO: make a SOLID FILLED silhouette of the shape (fill the interior, "
           "not a thin outline); every '#' must touch another '#' on the same "
           "layer; keep the shape at least 2 cells thick everywhere; most cells "
           "should sit on a '#' in the layer below. Think of the shape's filled "
           "footprint, not its edges.")
    try:
        out = subprocess.run(["claude", "-p", ask], capture_output=True,
                             text=True, timeout=120)
        data = _first_json(out.stdout)
        if not data:
            return None
        return {"looks_right": bool(data.get("looks_right")),
                "critique": str(data.get("critique", ""))[:120],
                "layers": data.get("layers")}
    except Exception:
        return None


def _layers_to_voxels(layers, color=15):
    v = {}
    for y, layer in enumerate(layers):
        for z, row in enumerate(layer):
            for x, ch in enumerate(str(row)):
                if ch == "#":
                    v[(x, y, z)] = color
    return v


def refine(build, voxels, prompt, tape, render_dir, rounds=2, seed=0):
    """Look-and-fix loop. Returns the best build. Streams to the tape so the
    judge watches the agent critique its own work."""
    if not available():
        return build
    best = build
    for i in range(rounds):
        img = os.path.join(render_dir, f"look_{i}.png")
        render_build(best, img, view="top")   # plan view reads a silhouette clearly
        tape.emit("designer", "look", f"rendering and looking at my '{prompt}'…",
                  ms=1500, tokens=900)
        verdict = _critique(img, prompt)
        if not verdict:
            break
        if verdict["looks_right"] or not verdict.get("layers"):
            tape.emit("inspector", "vision",
                      f"looks right: {verdict['critique'] or 'matches the request'}",
                      status="ok", ms=1200)
            break
        tape.emit("inspector", "vision", f"not yet: {verdict['critique']}",
                  status="warn", ms=1200)
        try:
            voxels = _layers_to_voxels(verdict["layers"])
            if not voxels:
                break
            candidate = build_voxels(voxels, name=best.name, tape=None, seed=seed)
            # only accept a revision that actually holds together — a thin/
            # scattered mask that would collapse is worse than what we had.
            from validate import validate
            rep = validate(candidate, physics=False)
            disconnected = any(e["code"] == "DISCONNECTED" for e in rep.errors)
            if disconnected or len(candidate.parts) < 6:
                tape.emit("repair", "reject-revision",
                          "that redraw wouldn't hold together — keeping the "
                          "sturdier version", status="warn", ms=8)
                continue
            best = candidate
            tape.emit("designer", "revise", "redrew the shape from what I saw", ms=400)
        except Exception:
            break
    return best
