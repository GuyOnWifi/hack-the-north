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
    """Very small NL parser: '<make the> <sub> <longer|wider|taller>'. Returns
    (sub_name, arg, delta) or None."""
    t = text.lower()
    target = None
    for s in build.subs:
        if s.gen in t or s.name in t:
            target = s.name
            break
    for word, (arg, d) in _DELTA.items():
        if word in t:
            return target or (build.subs[0].name if build.subs else None), arg, d
    return None


def apply_edit(build, sub_name, arg, delta, seed=0):
    """Freeze attachment points, mutate one node's arg, re-expand. Returns a new
    Build (new version). Same composition minus one changed number."""
    comp = copy.deepcopy(build.provenance["composition"])

    def walk(node, path):
        name = node.get("as") or node["gen"]
        if name == sub_name or node["gen"] == sub_name:
            args = node.setdefault("args", {})
            args[arg] = max(2, args.get(arg, 4) + delta)
            return True
        return any(walk(c, path) for c in node.get("children", []))

    if not walk(comp["root"], []):
        # target is the root gen
        args = comp["root"].setdefault("args", {})
        args[arg] = max(2, args.get(arg, 4) + delta)

    nb = expand(comp, build_id=build.id, name=build.name, seed=seed)
    # carry the version forward (immutable tree, invariant #3 / D11)
    from dataclasses import replace
    return replace(nb, version=build.version + 1)
