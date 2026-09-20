"""Pipeline C (brickify) as the app's build engine.

brickify designs from a concept image and places real LDraw parts, including
hinged and sideways ones, so its parts don't fit this package's grid model
(`Part.pos`/`rot`). A C build therefore carries its own LDraw text, steps and
stability in `provenance`, and every grid-only helper (sequence, footprint,
ldraw.to_ldr, physics) is skipped for it: see `is_c`.

    ENGINE=c (default)  pipeline C          ENGINE=a  the layer builder (agents.py)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import base64
import io
import threading

from model import Build, Part, SubAssembly

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brickify"))
from brickify import pipeline as c  # noqa: E402
from brickify.assembly import assemble  # noqa: E402
from brickify.check import resolve  # noqa: E402
from brickify.kit import PLATE, STUD  # noqa: E402

BACKEND = "brickify"
CHOICE_WAIT = 180  # how long a run waits for a person before the critic decides


def is_c(build) -> bool:
    return build is not None and build.provenance.get("backend") == BACKEND


# The run waits here while someone picks a design; POST /api/choose answers it.
CHOICE = {"event": threading.Event(), "answer": None, "open": False}


def choose(index: int | None, note: str = ""):
    """The answer from the app: which design, and anything to change about it
    (index None = let the critic decide)."""
    CHOICE["answer"] = {"index": index, "note": note}
    CHOICE["event"].set()


def _thumb(path: str, side: int = 460) -> str | None:
    """A small JPEG data URL, so pictures can ride the tape without bloating it."""
    try:
        from PIL import Image

        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((side, side))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=82)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def _listeners(tape):
    """brickify events -> this package's tape (and so the SSE stream)."""

    def on_event(ev):
        extra = {k: v for k, v in ev.items() if k not in ("t", "actor", "kind", "text", "status")}
        tape.emit(ev["actor"], ev["kind"], ev["text"], status=ev["status"], **extra)

    def on_model(m):
        # every built round goes to the screen straight away, like A's bands did
        tape.emit("builder", "geometry", f"round {m['round']}: {m['parts']} parts", status="running", ldr=m["ldr"], draft=bool(m.get("draft")))

    def on_image(img):
        thumb = _thumb(img["path"])
        if thumb:
            tape.emit("designer", "art", f"{img['role']} art", status="ok", role=img["role"], image=thumb)

    def on_choice(candidates):
        """Show the designs and wait. The critic takes over if nobody answers."""
        CHOICE["event"].clear()
        CHOICE["answer"], CHOICE["open"] = None, True
        tape.emit("critic", "choices",
                  "your design is ready: keep it or say what to change" if len(candidates) == 1
                  else f"{len(candidates)} designs to choose from", status="running",
                  choices=[{"n": i + 1, "style": c.get("style", ""), "stands": c["stands"],
                            "preferred": bool(c.get("preferred")), "parts": c.get("parts"),
                            "image": _thumb(c["front"]), "ldr": c["ldr"]} for i, c in enumerate(candidates)])
        answered = CHOICE["event"].wait(timeout=CHOICE_WAIT)
        CHOICE["open"] = False
        if not answered:
            tape.emit("critic", "choices", "nobody picked, so the critic will", status="ok")
        return CHOICE["answer"] if answered else None

    return on_event, on_model, on_image, on_choice


def build(prompt: str, name: str, tape) -> Build:
    on_event, on_model, on_image, on_choice = _listeners(tape)
    result = c.design(prompt, on_event=on_event, on_model=on_model, on_image=on_image, on_choice=on_choice, echo=False)
    return from_result(result, name)


def edit(current: Build, instruction: str, tape) -> Build:
    on_event, on_model, _, _ = _listeners(tape)
    result = c.edit(Path(current.provenance["run"]), instruction, on_event=on_event, on_model=on_model, echo=False)
    b = from_result(result, current.name)
    return Build(b.id, current.version + 1, b.name, b.parts, b.subs, b.provenance)


def from_result(result: dict, name: str) -> Build:
    """A finished run -> Build. Deterministic: the parts come from rebuilding the saved brief."""
    brief = json.loads(Path(result["brief"]).read_text())
    ldr = Path(result["ldr"]).read_text()
    parts, subs = [], {}
    for i, p in enumerate(_ldr_order(resolve(assemble(brief)))):
        m = p.M
        # nearest grid cell and quarter turn, for the parts list and inventory
        # screens; the real placement is the LDraw text
        pos = (round(m[0, 3] / STUD), round(-m[1, 3] / PLATE), round(m[2, 3] / STUD))
        rot = (round(float(_yaw(m)) / 90) % 4) * 90
        parts.append(Part(f"p{i}", p.pid, int(p.colour), pos, rot, p.body))
        subs.setdefault(p.body, SubAssembly(p.body, None, "brief", (), None, ()))
    run = Path(result["run"])
    prov = {
        "backend": BACKEND, "run": str(run), "ldr": ldr, "round": result["round"], "label": result.get("label"),
        "score": result.get("score"), "stands": result.get("stands"), "collisions": result.get("collisions", 0),
        "concept": result.get("concept"),
        "idea": result.get("idea"), "issues": result.get("issues", []),
    }
    return Build(f"c-{run.name}-r{result['round']}", 1, name, tuple(parts), tuple(subs.values()), prov)


def _yaw(m) -> float:
    import math
    return math.degrees(math.atan2(-m[2, 0], m[0, 0]))


def library() -> list[dict]:
    """Every model this machine has designed, newest first. Runs write
    themselves to disk as they go, so the library is just what is there."""
    out = []
    for d in sorted(c.RUNS.glob("*/"), reverse=True):
        f = d / "result.json"
        if not f.exists():
            continue
        try:
            r = json.loads(f.read_text())
        except ValueError:
            continue
        if not r.get("ldr") or not Path(r["ldr"]).exists():
            continue
        out.append({"id": d.name, "name": _title(r.get("idea") or d.name),
                    "idea": r.get("idea"), "parts": r.get("parts"), "score": r.get("score"),
                    "stands": r.get("stands"), "made": d.name[:13], "thumb": bool(_thumb_path(d, r))})
    return out


def _title(idea: str) -> str:
    """A short name from the idea it was designed from."""
    return (idea.split(".")[0].strip()[:40] or "Model").title()


def _thumb_path(d: Path, result: dict) -> Path | None:
    """The front render of the model that won, or any render this run made."""
    label = result.get("label") or f"r{result.get('round', 0)}"
    first = d / f"views-{label}" / "front.png"
    if first.exists():
        return first
    others = sorted(d.glob("views-*/front.png"))
    return others[-1] if others else None


def thumb(run_id: str) -> Path | None:
    d = c.RUNS / run_id
    f = d / "result.json"
    if not f.exists():
        return None
    return _thumb_path(d, json.loads(f.read_text()))


def open_run(run_id: str) -> Build:
    """A saved run, rebuilt into a Build so every build screen works on it."""
    d = c.RUNS / run_id
    result = json.loads((d / "result.json").read_text())
    result["run"] = str(d)  # runs move between machines; trust where it is now
    for key in ("ldr", "brief"):
        result[key] = str(d / Path(result[key]).name)
    return from_result(result, _title(result.get("idea") or run_id))


def recipe(build: Build) -> dict:
    """What replay needs to rebuild this version without calling any model."""
    return {"backend": BACKEND, "run": build.provenance["run"], "round": build.provenance["round"],
            "label": build.provenance.get("label") or f"r{build.provenance['round']}", "name": build.name}


def from_recipe(rec: dict) -> Build:
    run = Path(rec["run"])
    result = json.loads((run / "result.json").read_text())
    label = rec.get("label") or f"r{rec['round']}"
    result.update(round=rec["round"], label=label, ldr=str(run / f"{label}.ldr"), brief=str(run / f"brief-{label}.json"))
    return from_result(result, rec["name"])


def steps(build: Build) -> dict:
    """The booklet's steps, straight from the LDraw text's 0 STEP markers."""
    out, cur, idx = [], [], 0
    parts = build.parts

    def flush():
        if cur:
            elements: dict[str, int] = {}
            for p in cur:
                key = f"{p.part}:{p.color}"
                elements[key] = elements.get(key, 0) + 1
            out.append({"n": len(out) + 1, "sub": cur[0].sub, "layer": cur[0].pos[1], "parts": [p.id for p in cur], "elements": elements})
            cur.clear()

    # parts are stored in the LDraw text's line order (see from_result)
    for line in build.provenance["ldr"].splitlines():
        if line.startswith("1 ") and idx < len(parts):
            cur.append(parts[idx])
            idx += 1
        elif line.strip() == "0 STEP":
            flush()
    flush()
    return {"build_id": build.id, "n_steps": len(out), "steps": out}


def _ldr_order(parts):
    """The order to_ldr writes parts in: body by body, bottom-up (stable sort)."""
    by_body: dict[str, list] = {}
    for p in parts:
        by_body.setdefault(p.body, []).append(p)
    return [p for ps in by_body.values() for p in sorted(ps, key=lambda p: -p.M[1, 3])]


def report(build: Build):
    """Lane B's Report for a C build: valid if it has parts; tipping is a warning."""
    from validate import Report

    warnings = []
    if build.provenance.get("stands") is False:
        warnings.append({"code": "UNSTABLE", "sub": None, "human": "it would tip over on its own"})
    if build.provenance.get("collisions"):
        warnings.append({"code": "OVERLAP", "sub": None, "human": "a few pieces still overlap, so it can't be built exactly as shown"})
    return Report(
        ok=len(build.parts) > 0,
        errors=[] if build.parts else [{"code": "EMPTY", "parts": [], "human": "no bricks were produced"}],
        warnings=warnings,
        stats={"parts": len(build.parts), "studs_used": 0, "subs": len(build.subs)},
    )


def physics(build: Build) -> dict:
    return {"stable": build.provenance.get("stands") is not False, "studs": 0, "broken": [], "backend": BACKEND, "com": None, "base": [], "failures": []}
