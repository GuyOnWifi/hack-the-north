"""The EDIT loop (L2) — the best 20 seconds of the demo. "make the chassis
longer" re-runs ONE generator with new args; because the child attaches by
SOCKET NAME (not coordinate), the cabin and wheels reattach automatically even
though every coordinate under them moved. Attachment points are frozen; only
the edited node's args change.
"""
from __future__ import annotations
import copy
import re

from generators import expand

_DELTA = {"longer": ("length", +2), "shorter": ("length", -2),
          "wider": ("width", +1), "narrower": ("width", -1),
          "taller": ("height", +1), "lower": ("height", -1),
          "bigger": ("length", +2), "smaller": ("length", -2)}


def parse_edit(text, build):
    """Very small NL parser: '<make the> <gen> <longer|wider|taller>'. Returns
    (gen_name, arg, delta) or None. Targets a GENERATOR name (chassis, cabin)
    since that's how composition nodes are keyed."""
    t = text.lower()
    target = None
    for s in build.subs:
        if s.gen in t:
            target = s.gen
            break
    for word, (arg, d) in _DELTA.items():
        if word in t:
            return target or (build.subs[0].gen if build.subs else None), arg, d
    return None


def apply_edit(build, gen_name, arg, delta, seed=0):
    """Freeze attachment points, mutate one node's arg, re-expand. Returns a new
    Build. Attachment is by socket NAME, so children reattach even though every
    coordinate under them moved. If the target generator doesn't take `arg`
    (e.g. chassis has no height), the edit is a no-op — never an error."""
    from dataclasses import replace
    comp = copy.deepcopy(build.provenance["composition"])
    applied = [False]

    def walk(node):
        if node["gen"] == gen_name:
            args = node.setdefault("args", {})
            if arg in args:                       # only knobs this gen exposes
                args[arg] = max(2, args[arg] + delta)
                applied[0] = True
            return True
        return any(walk(c) for c in node.get("children", []))

    walk(comp["root"])
    if not applied[0]:
        return replace(build, version=build.version + 1)   # nothing to change
    nb = expand(comp, build_id=build.id, name=build.name, seed=seed)
    return replace(nb, version=build.version + 1)
