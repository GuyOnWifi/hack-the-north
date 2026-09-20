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
        # for replay) and the bulky LDraw text + embedded part library, which
        # have their own endpoint (/api/ldr) and would add ~560 KB per poll.
        "provenance": {k: v for k, v in build.provenance.items()
                       if k not in ("voxels", "dropped", "ldr", "lib")},
    }


def edit_json(res, path, dry_run=False, tape=None, human=None):
    """An edits.Result -> the `edit` key every mutating response carries
    (docs/EDITING.md D.1). `tape` holds only this edit's own events."""
    events = tape if tape is not None else _events(getattr(res, "events", ()))
    return {
        "accepted": bool(res.accepted), "dry_run": bool(dry_run), "path": path,
        "code": res.code, "human": human if human is not None else res.human,
        "ops": [dict(o) for o in res.ops],
        "changed": list(res.changed), "added": list(res.added), "removed": list(res.removed),
        "landed": [dict(l) for l in res.landed],
        "candidates": [], "culprits": list(res.culprits), "offer": res.offer,
        "tape": events,
    }


def _events(raw):
    out, t = [], 0
    for actor, kind, text, status in raw:
        t += 1
        out.append({"t": t, "actor": actor, "kind": kind, "text": text,
                    "status": status, "ms": 0, "tokens": 0})
    return out


def nav_json(path, human, accepted=True, kind="edit.nav", actor="router"):
    return {"accepted": accepted, "dry_run": False, "path": path, "code": None,
            "human": human, "ops": [], "changed": [], "added": [], "removed": [],
            "landed": [], "candidates": [], "culprits": [], "offer": None,
            "tape": [{"t": 1, "actor": actor, "kind": kind, "text": human,
                      "status": "ok" if accepted else "warn", "ms": 0, "tokens": 0}]}


def report_json(report):
    return report.as_dict()


def steps_json(steps):
    return steps


def dump(obj, path):
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)
    return path
