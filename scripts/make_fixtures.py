#!/usr/bin/env python3
"""Generate the fixtures every lane develops against. Run: python scripts/make_fixtures.py

These are real outputs of the real pipeline, not hand-written mocks -- so the frontend builds
against the exact shapes the backend will produce, and a contract change that breaks a lane
shows up here first.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from core.compose import Composition, compose
from core.ldraw import to_ldraw
from core.model import Inventory
from core.sequence import sequence
from core import meta

OUT = pathlib.Path(__file__).resolve().parents[1] / "fixtures"
OUT.mkdir(exist_ok=True)

# A plausible home bin: common parts, uneven quantities, three main colours.
BIN = [
    ("3001", 4, 8), ("3001", 15, 6), ("3001", 0, 4), ("3003", 4, 10), ("3003", 15, 6),
    ("3002", 4, 4), ("2456", 15, 3), ("3007", 0, 2), ("3006", 4, 1),
    ("3004", 4, 12), ("3004", 15, 9), ("3005", 4, 14), ("3005", 0, 8),
    ("3010", 4, 6), ("3622", 15, 5), ("3009", 0, 3), ("3008", 4, 2),
    ("3020", 15, 7), ("3022", 4, 9), ("3021", 0, 4), ("3795", 15, 3), ("3034", 4, 2),
    ("3023b", 4, 15), ("3023b", 15, 11), ("3024", 4, 18), ("3024", 0, 10),
    ("3623", 15, 6), ("3710", 4, 5), ("3666", 0, 3), ("3460", 15, 2),
    ("3069b", 4, 6), ("3070b", 15, 8), ("2431", 0, 4), ("3068b", 4, 3),
]

CONFIDENCE = {  # what the CV lane would attach; a few deliberately uncertain rows
    "3003": (0.62, [("3001", "brick 2x4", 0.41), ("3002", "brick 2x3", 0.22)]),
    "3023b": (0.58, [("3069b", "tile 1x2", 0.44), ("3024", "plate 1x1", 0.19)]),
}


def inventory_json() -> dict:
    items = []
    for i, (part, color, qty) in enumerate(BIN, 1):
        m = meta.get(part)
        conf, alts = CONFIDENCE.get(part, (0.94, []))
        status = "confirmed" if conf >= 0.85 else "needs_review"
        src = "photo" if i % 3 else "typed"
        item = {
            "id": f"inv_{i:03d}",
            "part": part,
            "name": m.name,
            "color": color,
            "qty": qty,
            "source": src,
            "confidence": {"part": conf, "color": 0.88},
            "status": status,
        }
        if src == "photo":
            item["evidence"] = {
                "crop_url": f"https://example.invalid/crops/{i:03d}.png",
                "alternatives": [
                    {"part": p, "name": n, "score": s} for p, n, s in alts
                ],
            }
        items.append(item)
    return {
        "session_id": "ses_fixture",
        "items": items,
        "totals": {
            "pieces": sum(q for _, _, q in BIN),
            "distinct": len(BIN),
            "unknown": 2,
        },
    }


def build_json(build, report, steps) -> dict:
    return {
        "id": build.id,
        "name": build.name,
        "version": build.version,
        "parts": [
            {"id": p.id, "part": p.part, "color": p.color,
             "pos": list(p.pos), "rot": p.rot, "sub": p.sub}
            for p in build.parts
        ],
        "subassemblies": {
            s.id: {"parent": s.parent,
                   "attach": [{"at": list(a.at), "face": a.face,
                               "studs": [list(x) for x in a.studs]} for a in s.attach]}
            for s in build.subassemblies
        },
        "provenance": build.provenance,
    }


def steps_json(steps) -> dict:
    out = []
    for i, group in enumerate(steps, 1):
        counts: dict[tuple[str, int], int] = {}
        for p in group:
            counts[(p.part, p.color)] = counts.get((p.part, p.color), 0) + 1
        out.append({
            "index": i,
            "parts": [{"id": p.id, "part": p.part, "color": p.color,
                       "pos": list(p.pos), "rot": p.rot, "sub": p.sub} for p in group],
            "callout": [{"part": k[0], "name": meta.get(k[0]).name, "color": k[1], "qty": n}
                        for k, n in sorted(counts.items())],
        })
    return {"steps": out, "total": len(out)}


TAPE = [
    {"t": 0,    "actor": "cataloguer", "kind": "ingest",  "text": "34 distinct parts, 2 need review", "status": "ok", "ms": 820},
    {"t": 820,  "actor": "designer",   "kind": "propose", "text": "chassis(10,4) + cabin(4,4,open)", "status": "ok", "ms": 1900, "tokens": 2400},
    {"t": 2720, "actor": "inspector",  "kind": "validate","text": "OUT_OF_BUDGET: needs 4x brick 2x4 in colour 4; you have 1", "status": "fail", "ms": 3},
    {"t": 2723, "actor": "repair",     "kind": "rung0",   "text": "substituted 3x (brick 2x4 -> 2x brick 2x2)", "status": "ok", "ms": 1},
    {"t": 2724, "actor": "inspector",  "kind": "validate","text": "WEAK_BOND: chassis seams stack", "status": "warn", "ms": 3},
    {"t": 2727, "actor": "repair",     "kind": "rung1",   "text": "re-tiled course 1 with an offset origin", "status": "ok", "ms": 2},
    {"t": 2729, "actor": "inspector",  "kind": "validate","text": "valid - 21 parts, 22 joins", "status": "ok", "ms": 3},
    {"t": 2732, "actor": "scribe",     "kind": "sequence","text": "6 steps", "status": "ok", "ms": 2200},
]


def main() -> None:
    inv = Inventory.from_pairs(BIN)
    comp = Composition("chassis", [
        {"id": "chassis", "gen": "chassis", "args": {"length": 10, "width": 4}, "color": 4},
        {"id": "cabin", "gen": "cabin", "attach_to": "chassis", "at": "top_rear",
         "args": {"length": 4, "width": 4, "height": 6}, "color": 15},
    ])
    build, report, notes = compose(comp, inv, name="Desk Rover", build_id="bld_fixture")
    steps = sequence(build)

    (OUT / "inventory.json").write_text(json.dumps(inventory_json(), indent=2) + "\n")
    (OUT / "build.json").write_text(json.dumps(build_json(build, report, steps), indent=2) + "\n")
    (OUT / "report.json").write_text(json.dumps(report.to_dict(), indent=2) + "\n")
    (OUT / "steps.json").write_text(json.dumps(steps_json(steps), indent=2) + "\n")
    (OUT / "model.ldr").write_text(to_ldraw(build, steps))
    (OUT / "tape.jsonl").write_text("".join(json.dumps(e) + "\n" for e in TAPE))

    print(f"build:  {len(build.parts)} parts, valid={report.ok}, {len(steps)} steps")
    for n in notes:
        print(f"  note: {n}")
    print(f"wrote {len(list(OUT.iterdir()))} fixtures to {OUT}")


if __name__ == "__main__":
    main()
