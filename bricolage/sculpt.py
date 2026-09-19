"""The `sculpt` backend. The LLM emits a stack of solid layer footprints (a
CHOICE of shape — still no coordinates): each layer is (width, depth), centred.
Our code tiles every layer with the masonry bond and stacks them, so the result
is connected and stands up by construction. Thin organic SHELLS are out of
scope (anti-goal: we're not competing on render fidelity) — sculpt does solid,
stepped voxel forms. Real Opus streams the layer list (client.messages.stream).
"""
from __future__ import annotations
from model import Build, SubAssembly, Part
from generators import bonded

# each entry: list of (width, depth) footprints, bottom -> top, centred
SHAPES = {
    "pyramid": [(6, 6), (4, 4), (2, 2)],
    "tree":    [(2, 2), (6, 6), (4, 4), (2, 2)],
    "diamond": [(2, 2), (4, 4), (6, 6), (4, 4), (2, 2)],
    "tower":   [(2, 2)] * 5,
    # a heart approximated as a solid stepped form (no thin shell)
    "heart":   [(6, 6), (6, 4), (4, 2), (2, 2)],
}


def build_sculpt(noun, size=1.0, seed=0, color=4):
    layers = SHAPES.get(noun, SHAPES["pyramid"])
    base = max(w for w, _ in layers)
    parts, y, n = [], 0, 0
    for i, (w, d) in enumerate(layers):
        ox, oz = (base - w) // 2, (base - d) // 2      # centre each layer
        # 2 bonded courses per voxel layer => each layer is internally connected,
        # and each layer rests on the one below => the stack is one solid mass.
        for p in bonded(w, d, y, color, seed + i, plates=False, courses=2, sub="hull"):
            parts.append(Part(f"p{n}", p.part, p.color,
                              (p.pos[0] + ox, p.pos[1], p.pos[2] + oz), 0, "hull"))
            n += 1
        y += 6
    sub = SubAssembly("hull", None, "sculpt", (), None, ())
    return Build(id="bld_sculpt", version=0, name=noun.title(),
                 parts=tuple(parts), subs=(sub,),
                 provenance={"backend": "sculpt", "noun": noun, "seed": seed})
