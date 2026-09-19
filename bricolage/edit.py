"""The EDIT loop (L2). Natural-language edits to an existing build:
  - resize   "make the chassis longer"  -> re-run one generator (compose builds)
  - recolour "make the flower orange"    -> recolour the shape (any build)
Attachment points are frozen; children reattach by socket name.
"""
from __future__ import annotations
import copy
from dataclasses import replace

from generators import expand
from meta import NAME_TO_CODE

_DELTA = {"longer": ("length", +2), "shorter": ("length", -2),
          "wider": ("width", +1), "narrower": ("width", -1),
          "taller": ("height", +1), "lower": ("height", -1),
          "bigger": ("length", +2), "smaller": ("length", -2)}


def parse_edit(text, build):
    """Parse an edit into an op dict, or None if nothing recognisable."""
    t = text.lower()

    # recolour: any colour word -> repaint the shape
    for word, code in NAME_TO_CODE.items():
        if word in t:
            return {"kind": "recolor", "color": code, "word": word}

    # resize: a delta word, targeting a generator by name (compose builds)
    target = next((s.gen for s in build.subs if s.gen in t), None)
    for word, (arg, d) in _DELTA.items():
        if word in t:
            return {"kind": "resize",
                    "gen": target or (build.subs[0].gen if build.subs else None),
                    "arg": arg, "delta": d}
    return None


def apply_edit(build, op, seed=0):
    """Apply a parsed edit op -> new Build (new version)."""
    if op["kind"] == "recolor":
        # repaint every non-base part; the baseplate/stand stays neutral
        parts = tuple(p if p.sub == "base" else replace(p, color=op["color"])
                      for p in build.parts)
        return replace(build, parts=parts, version=build.version + 1)

    # resize — only meaningful for generator (compose) builds
    comp = build.provenance.get("composition")
    if not comp:
        return replace(build, version=build.version + 1)   # no-op on a mosaic
    comp = copy.deepcopy(comp)
    applied = [False]

    def walk(node):
        if node["gen"] == op["gen"]:
            args = node.setdefault("args", {})
            if op["arg"] in args:
                args[op["arg"]] = max(2, args[op["arg"]] + op["delta"])
                applied[0] = True
            return True
        return any(walk(c) for c in node.get("children", []))

    walk(comp["root"])
    if not applied[0]:
        return replace(build, version=build.version + 1)
    nb = expand(comp, build_id=build.id, name=build.name, seed=seed, lenient=True)
    return replace(nb, version=build.version + 1)
