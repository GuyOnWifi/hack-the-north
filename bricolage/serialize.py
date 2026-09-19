"""Build/Report/steps -> the JSON contracts the frontend consumes (Contracts
2, 3 in lanes/00-contracts.md). Kept separate so the core model stays pure.
"""
from __future__ import annotations
import json


def build_json(build):
    return {
        "id": build.id, "version": build.version, "name": build.name,
        "parts": [{"id": p.id, "part": p.part, "color": p.color,
                   "pos": list(p.pos), "rot": p.rot, "sub": p.sub}
                  for p in build.parts],
        "subassemblies": {s.name: {"parent": s.parent, "gen": s.gen,
                                   "attach": s.attach, "sockets": list(s.sockets)}
                          for s in build.subs},
        # drop internal, non-JSON provenance (voxels has tuple keys; it's only
        # for replay). Keep composition (JSON-safe, useful to the UI).
        "provenance": {k: v for k, v in build.provenance.items()
                       if k not in ("voxels", "dropped")},
    }


def report_json(report):
    return report.as_dict()


def steps_json(steps):
    return steps


def dump(obj, path):
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)
    return path
