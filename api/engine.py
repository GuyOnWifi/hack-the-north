"""The build engine the routes call: prompt -> composition -> validated Build -> steps.

WHY this module exists at all: the routes must not know whether a composition came from an LLM,
from the offline planner, or from `fixtures/`. It is one seam with three sources, ordered by
preference and degrading downward without a single `if` in a route handler:

    1. `api.llm` (another lane owns it) -- imported LAZILY, inside the call, never at module
       scope, so this file keeps working while that package does not exist.
    2. the offline planner below -- keyword -> generator tree. Deterministic, no network.
    3. `fixtures/` -- DEMO_SAFE=1. Zero compute, zero network, zero LLM.

Every path ends in `compose()` -> `validate()` -> `sequence()`, so invariant 2 holds no matter
which one ran. The LLM (when it exists) picks generators and arguments; it never sees a
coordinate. Invariant 4 is structural here: there is nowhere in this file to put one.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import pathlib
import time
from dataclasses import dataclass

from core.compose import Composition, compose
from core.generators import GENERATORS          # registers the built-ins on import
from core.generators.registry import catalog_text
from core.ldraw import to_ldraw
from core import meta as meta_mod
from core.model import Build, Inventory, Placed, SubAssembly
from core.sequence import sequence
from core.validate import Issue, Report

from .store import BuildRecord, Cost, Op, Session, Version

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"

# Below this the result is embarrassing rather than wrong, and saying so is product behaviour
# (Contract 1, `sufficient` / `guidance`). Refusing with an actionable sentence beats shipping
# a four-brick "rover".
MIN_PIECES = 40

# Hard wall-clock budget per request (docs/04-loop.md §1.4). Past it we degrade, never wait.
MAX_WALL_MS = int(os.getenv("BRICOLAGE_MAX_WALL_MS", "25000"))


def demo_safe() -> bool:
    """Read the env var per call, not at import: tests flip it, and so does a panicking human."""
    return os.getenv("DEMO_SAFE", "").strip() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------- the offline planner

COLOR_WORDS = {
    "black": 0, "blue": 1, "green": 2, "red": 4, "yellow": 14, "white": 15,
    "tan": 19, "orange": 25, "brown": 70, "reddish brown": 70,
    "grey": 71, "gray": 71, "light grey": 71, "light gray": 71,
    "dark grey": 72, "dark gray": 72,
}

# prompt keyword -> the shape of the model. Deliberately small: five shapes that the seven
# generators can actually build well beat twenty that mostly fail validation.
SHAPES = {
    "tower": ("tower", "castle", "skyscraper", "lighthouse", "tall"),
    "wall": ("wall", "fence", "barrier"),
    "house": ("house", "building", "hut", "cabin", "shed", "garage"),
    "plane": ("plane", "jet", "rocket", "spaceship", "ship", "shuttle"),
    "vehicle": ("rover", "car", "truck", "vehicle", "buggy", "tank", "train", "robot"),
}


def _shape_of(prompt: str) -> str:
    low = prompt.lower()
    for shape, words in SHAPES.items():
        if any(w in low for w in words):
            return shape
    return "vehicle"        # the demo default, and the best-tested generator pair


def _palette(inv: Inventory) -> tuple[int, int]:
    """The two colours the bin actually has most of. Deterministic tie-break on the colour code."""
    per: dict[int, int] = {}
    for (_part, color), qty in inv.items.items():
        per[color] = per.get(color, 0) + qty
    if not per:
        return 4, 15
    ranked = sorted(per, key=lambda c: (-per[c], c))
    return ranked[0], (ranked[1] if len(ranked) > 1 else ranked[0])


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def offline_plan(prompt: str, inv: Inventory, seed: int = 0) -> Composition:
    """Keyword -> generator tree. No network, no model, same seed = same tree.

    This is not a stand-in for the designer agent; it is the floor underneath it. When the LLM
    lane is up it proposes something better, and when the wifi dies this still ships a model.
    """
    shape = _shape_of(prompt)
    main, accent = _palette(inv)
    for word, code in COLOR_WORDS.items():
        if word in prompt.lower():
            main = code
            break
    # Scale with the bin, not with optimism: a 200-piece bin should not be asked for a 20-stud
    # chassis. `jitter` is how "try another" produces a visibly different model from a new seed.
    #
    # The ranges below are MEASURED against fixtures/inventory.json, not guessed: a 4-wide
    # chassis validates clean from length 6 to 14, a 2-wide one never does (two 1-wide courses
    # cannot bond), and a wall stays connected up to length 8. Picking arguments a generator is
    # known to survive is the cheapest repair rung there is -- the one that never runs.
    budget = inv.total
    jitter = (seed % 3) - 1
    size = _clamp(budget // 30, 3, 10)

    if shape == "tower":
        return Composition("tower", [
            {"id": "tower", "gen": "tower", "color": main,
             "args": {"height": _clamp(size + 3 + jitter * 2, 6, 15),
                      "size": _clamp(size // 3 + 1, 2, 3)}},
        ])
    if shape == "wall":
        return Composition("wall", [
            {"id": "wall", "gen": "wall", "color": main,
             "args": {"length": _clamp(size + jitter, 3, 8),
                      "height": _clamp(size // 2 + 3, 3, 9)}},
        ])
    if shape == "house":
        return Composition("base", [
            {"id": "base", "gen": "chassis", "color": main,
             "args": {"length": _clamp(size + 2 + jitter, 6, 12), "width": 4}},
            {"id": "walls", "gen": "cabin", "attach_to": "base", "at": "top_centre",
             "color": accent, "args": {"length": 4, "width": 4, "height": 9, "style": "open"}},
        ])
    if shape == "plane":
        return Composition("chassis", [
            {"id": "chassis", "gen": "chassis", "color": main,
             "args": {"length": _clamp(size + 4 + jitter, 6, 14), "width": 4}},
            {"id": "cabin", "gen": "cabin", "attach_to": "chassis", "at": "top_front",
             "color": accent, "args": {"length": 4, "width": 4, "height": 6, "style": "open"}},
            {"id": "tail", "gen": "fin", "attach_to": "chassis", "at": "top_rear",
             "color": accent, "args": {"length": 4, "height": 3}},
        ])
    return Composition("chassis", [
        {"id": "chassis", "gen": "chassis", "color": main,
         "args": {"length": _clamp(size + 4 + jitter, 6, 14), "width": 4}},
        {"id": "cabin", "gen": "cabin", "attach_to": "chassis", "at": "top_rear",
         "color": accent, "args": {"length": 4, "width": 4, "height": 6, "style": "open"}},
    ])


def comp_text(comp: Composition) -> str:
    """One line describing a composition, for the tape. No coordinates -- there are none to print."""
    bits = []
    for n in comp.nodes:
        args = ", ".join(f"{k}={v}" for k, v in (n.get("args") or {}).items())
        bits.append(f"{n.get('gen', n['id'])}({args})")
    return " + ".join(bits)


def comp_to_dict(comp: Composition) -> dict:
    return {"root": comp.root, "nodes": [dict(n) for n in comp.nodes]}


def comp_from_dict(d: dict) -> Composition:
    return Composition(d["root"], [dict(n) for n in d["nodes"]])


# The composition that produced `fixtures/build.json` (see scripts/make_fixtures.py). Recorded
# here so that an edit to a DEMO_SAFE build has a real tree to re-generate from instead of a
# dead end -- the fixture is a build, not a recipe, and an edit needs the recipe.
DEMO_COMPOSITION = {
    "root": "chassis",
    "nodes": [
        {"id": "chassis", "gen": "chassis", "args": {"length": 10, "width": 4}, "color": 4},
        {"id": "cabin", "gen": "cabin", "attach_to": "chassis", "at": "top_rear",
         "args": {"length": 4, "width": 4, "height": 6}, "color": 15},
    ],
}


# ---------------------------------------------------------------- the LLM seam


@dataclass(frozen=True, slots=True)
class Planned:
    composition: Composition
    source: str              # llm | offline | fixtures
    cost: Cost = Cost()
    note: str = ""


def _llm_module():
    """Import `api.llm` lazily, or return None. Never raises, never imported at module scope.

    Another lane is writing that package in parallel; this file must run before, during and
    after that. DEMO_SAFE forbids it outright -- that mode means zero LLM calls, not few.
    """
    if demo_safe() or os.getenv("BRICOLAGE_NO_LLM", "").strip() in ("1", "true", "yes"):
        return None
    try:
        from api import llm                     # noqa: PLC0415 -- lazy on purpose
    except Exception:
        return None
    return llm


def _as_composition(obj) -> Composition | None:
    """Accept whatever the LLM lane hands back: a Composition, a dict, or an object holding one."""
    if obj is None:
        return None
    if isinstance(obj, Composition):
        return obj
    if isinstance(obj, dict) and "nodes" in obj:
        return comp_from_dict(obj)
    inner = getattr(obj, "composition", None)
    return _as_composition(inner) if inner is not None else None


def _cost_of(obj) -> Cost:
    c = getattr(obj, "cost", None)
    if isinstance(c, Cost):
        return c
    if isinstance(c, dict):
        return Cost(int(c.get("tokens_in", 0)), int(c.get("tokens_out", 0)),
                    int(c.get("ms", 0)), int(c.get("llm_calls", 1)))
    return Cost(llm_calls=1)


def plan(prompt: str, inv: Inventory, seed: int, *, mode: str = "compose") -> Planned:
    """Get a composition. LLM if the lane is up and answers; offline planner otherwise."""
    llm = _llm_module()
    if llm is not None:
        fn = getattr(llm, "propose", None) or getattr(llm, "plan", None) \
            or getattr(llm, "propose_build", None)
        if callable(fn):
            try:
                out = fn(prompt=prompt, inventory=inv, catalog=catalog_text(), seed=seed,
                         mode=mode)
                comp = _as_composition(out)
                if comp is not None and comp.nodes:
                    return Planned(comp, "llm", _cost_of(out))
            except Exception as exc:                 # a dead model is a degradation, not a 500
                return Planned(offline_plan(prompt, inv, seed), "offline",
                               note=f"designer unavailable ({type(exc).__name__}); "
                                    f"used the offline planner")
    return Planned(offline_plan(prompt, inv, seed), "offline")


@dataclass(frozen=True, slots=True)
class LoopOutcome:
    """What `api.llm.build_with_fixes` gave back, flattened into what the store needs."""

    build: Build
    report: Report
    steps: list
    composition: dict
    notes: tuple[str, ...]
    events: list[dict]
    cost: Cost
    message: str


def via_llm_loop(prompt: str, inv: Inventory, seed: int, name: str, build_id: str,
                 composition: dict | None = None) -> LoopOutcome | None:
    """Hand the whole fix loop to the build-system lane when it is there. Returns None if not.

    That package owns the escalation ladder, the repair rungs and its own tape; duplicating any
    of it here would give the demo two answers to "how does it repair?". So this is a delegation,
    not a reimplementation -- and its absence costs us only the ladder, not the build.
    """
    llm = _llm_module()
    runner = getattr(llm, "build_with_fixes", None) if llm is not None else None
    if not callable(runner):
        return None
    try:
        budget = llm.Budget(seed=seed) if hasattr(llm, "Budget") else None
        res = runner(prompt, inv, budget=budget, name=name, composition=composition)
        build = getattr(res, "build", None)
        if build is None or not build.parts:
            return None
        build = dataclasses.replace(build, id=build_id)
        report = res.report
        steps: list = []
        try:
            steps = sequence(build)
        except Exception as exc:
            res.notes = tuple(res.notes) + (f"steps unavailable: {exc}",)
        events = [e.to_dict() if hasattr(e, "to_dict") else dict(e)
                  for e in getattr(res, "events", [])]
        return LoopOutcome(
            build, report, steps,
            dict(getattr(res, "composition", {}) or {}),
            tuple(getattr(res, "notes", ())),
            events,
            Cost(tokens_out=getattr(res, "tokens", 0), ms=getattr(res, "ms", 0),
                 llm_calls=getattr(res, "llm_calls", 0)),
            getattr(res, "message", "") or "",
        )
    except Exception:
        return None                                  # degrade to the offline path, never 500


# ---------------------------------------------------------------- fixtures (DEMO_SAFE)


def load_fixture_build() -> tuple[Build, Report, list[list[Placed]]]:
    """Rebuild the core objects from fixtures/. The demo's floor: disk only, nothing else."""
    bj = json.loads((FIXTURES / "build.json").read_text())
    rj = json.loads((FIXTURES / "report.json").read_text())
    sj = json.loads((FIXTURES / "steps.json").read_text())

    def placed(d: dict) -> Placed | None:
        # Ids cross the lane boundary in BrickLink convention ("3023" for LDraw's "3023b"), so
        # translate before use. A part we genuinely have no geometry for is skipped with a note
        # rather than raising -- demo-safe mode must not be able to die on one unknown brick.
        part = meta_mod.resolve_id(d["part"])
        if part is None:
            return None
        return Placed(d["id"], part, int(d["color"]), tuple(d["pos"]),
                      int(d.get("rot", 0)), d.get("sub", "root"))

    build = Build(
        id=bj["id"], name=bj["name"],
        parts=tuple(q for q in (placed(p) for p in bj["parts"]) if q is not None),
        subassemblies=tuple(SubAssembly(k, v.get("parent")) for k, v in
                            bj.get("subassemblies", {}).items()),
        version=int(bj.get("version", 1)),
        provenance=dict(bj.get("provenance", {}), source="fixtures"),
    )
    report = Report(
        ok=bool(rj["ok"]),
        errors=tuple(Issue(i["code"], i["human"], tuple(i.get("parts", ())), i.get("sub"))
                     for i in rj.get("errors", [])),
        warnings=tuple(Issue(i["code"], i["human"], tuple(i.get("parts", ())), i.get("sub"))
                       for i in rj.get("warnings", [])),
        stats=dict(rj.get("stats", {})),
    )
    # The build lane's steps reference parts by id ("parts": ["p33", "p34"]); our earlier
    # fixtures embedded whole part objects. Accept both so demo-safe mode works with whichever
    # fixture files happen to be checked in -- this is the seam between two lanes and it should
    # not be able to break the offline demo.
    by_id = {p.id: p for p in build.parts}
    steps: list[list[Placed]] = []
    for step in sj.get("steps", []):
        group = [placed(item) if isinstance(item, dict) else by_id.get(item)
                 for item in step.get("parts", [])]
        steps.append([g for g in group if g is not None])
    return build, report, steps


def load_fixture_tape() -> list[dict]:
    path = FIXTURES / "tape.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_fixture_inventory() -> list[dict]:
    return json.loads((FIXTURES / "inventory.json").read_text()).get("items", [])


# ---------------------------------------------------------------- running a build


def guidance_for(session: Session) -> str | None:
    """The honest refusal. Returns a user-facing sentence, or None when the bin is enough."""
    totals = session.totals()
    usable = totals["pieces"] - totals["unknown"]
    if usable >= MIN_PIECES:
        return None
    return (f"Only {usable} usable bricks in this bin. Below about {MIN_PIECES} the result is a "
            f"lump, not a model. Photograph more of the pile (spread flat, one layer, gaps "
            f"between bricks) or type a few more rows, then ask again.")


def _compose_now(comp: Composition, inv: Inventory, name: str, build_id: str):
    """compose -> validate -> sequence, all synchronous. Runs in a worker thread."""
    build, report, notes = compose(comp, inv, name=name, build_id=build_id)
    steps: list[list[Placed]] = []
    if build.parts:
        try:
            steps = sequence(build)
        except Exception as exc:                     # a model we cannot order is still a model
            notes.append(f"steps unavailable: {exc}")
    return build, report, notes, steps


# Rung 1 of the escalation ladder (docs/04-loop.md §1.2), and only rung 1: re-run the generators
# with smaller arguments when the bin could not afford the first proposal. The deterministic
# local repairs (rung 0) and the LLM repair (rung 2) belong to the build-system lane; this is the
# minimum an HTTP layer needs so that "your bin is smaller than the designer thought" degrades
# into a smaller model instead of an empty one.
MAX_ARG_ROUNDS = 2
_SHRINKABLE = ("length", "height", "size")      # never `width`: a 2-wide course cannot bond


def _shrink(comp: Composition) -> Composition | None:
    out = comp_from_dict(comp_to_dict(comp))
    changed = False
    for node in out.nodes:
        args = dict(node.get("args") or {})
        for key in _SHRINKABLE:
            v = args.get(key)
            if isinstance(v, int) and v > 3:
                args[key] = max(3, v - 2)
                changed = True
        node["args"] = args
    return out if changed else None


def _score(build: Build, report: Report) -> tuple:
    """Best-effort ranking: something beats nothing, valid beats flagged, fewer errors beats more."""
    return (bool(build.parts), report.ok, -len(report.errors), len(build.parts))


def generate_best(comp: Composition, inv: Inventory, name: str, build_id: str,
                  emit=None) -> tuple[Composition, Build, Report, list[str], list]:
    """Compose, and if that came out empty or invalid, try up to two smaller variants."""
    best = None
    cur: Composition | None = comp
    for round_no in range(MAX_ARG_ROUNDS + 1):
        build, report, notes, steps = _compose_now(cur, inv, name, build_id)
        cand = (cur, build, report, notes, steps)
        if best is None or _score(build, report) > _score(best[1], best[2]):
            best = cand
        if build.parts and report.ok:
            break
        nxt = _shrink(cur)
        if nxt is None or round_no == MAX_ARG_ROUNDS:
            break
        cur = nxt
        if emit is not None:
            emit("repair", "rung1", f"retrying smaller: {comp_text(cur)}", status="warn")
    return best


def _name_for(prompt: str) -> str:
    words = [w for w in prompt.strip().split() if w.isalpha()][:4]
    return " ".join(w.capitalize() for w in words) or "Build"


async def run_build(rec: BuildRecord, session: Session) -> None:
    """Fill a BuildRecord's version tree. Emits Contract 4 events as it goes. Never raises."""
    try:
        if demo_safe():
            # The canned tape has its own cataloguer line; emitting ours first would make the
            # fixture tape and the served tape disagree, and the frontend tests against both.
            await _run_demo_safe(rec)
            return

        totals = session.totals()
        rec.emit("cataloguer", "ingest",
                 f"{totals['distinct']} distinct parts, {totals['pieces']} pieces"
                 + (f", {totals['unknown']} unknown" if totals["unknown"] else ""))

        refusal = guidance_for(session)
        if refusal:
            rec.emit("designer", "refuse", refusal, status="fail")
            rec.finish("failed", refusal)
            return

        inv = session.inventory()
        if rec.mode not in ("compose", "auto", ""):
            rec.emit("designer", "backend",
                     f"'{rec.mode}' backend is not built; using compose", status="warn")

        # Preferred path: the build-system lane's fix loop, which brings the repair ladder and
        # its own tape. It is delegated to, not wrapped -- if it is missing or throws, the
        # offline planner below still produces a model.
        outcome = await _budgeted(asyncio.to_thread(
            via_llm_loop, rec.prompt, inv, rec.seed, _name_for(rec.prompt), rec.id))
        if outcome is not None:
            rec.replay(outcome.events)
            if not outcome.events:
                _emit_report(rec, outcome.report, outcome.cost.ms)
            rec.tree.commit(
                outcome.build, outcome.report,
                Op("generate", {"prompt": rec.prompt, "mode": rec.mode,
                                "composition": outcome.composition, "source": "llm_loop"},
                   seed=rec.seed),
                steps=outcome.steps, cost=outcome.cost, notes=outcome.notes)
            rec.finish("ok", outcome.message or None)
            return

        t0 = time.monotonic()
        planned = await _budgeted(asyncio.to_thread(plan, rec.prompt, inv, rec.seed,
                                                    mode=rec.mode))
        if planned is None:                          # budget blew before we had anything
            planned = Planned(offline_plan(rec.prompt, inv, rec.seed), "offline",
                              note="designer exceeded its time budget; used the offline planner")
        if planned.note:
            rec.emit("designer", "degrade", planned.note, status="warn")
        rec.emit("designer", "propose", comp_text(planned.composition),
                 ms=int((time.monotonic() - t0) * 1000),
                 tokens=(planned.cost.tokens_in + planned.cost.tokens_out) or None)

        t1 = time.monotonic()
        # The generator work happens in a worker thread, so it cannot touch the SSE waiters
        # (an asyncio.Event is not thread-safe). It buffers its tape lines and we emit them here.
        pending: list[tuple] = []
        used, build, report, notes, steps = await asyncio.to_thread(
            generate_best, planned.composition, inv, _name_for(rec.prompt), rec.id,
            lambda *a, **k: pending.append((a, k)))
        for args, kwargs in pending:
            rec.emit(*args, **kwargs)
        _emit_report(rec, report, int((time.monotonic() - t1) * 1000))
        for n in notes:
            rec.emit("repair", "note", n, status="warn")
        if steps:
            rec.emit("scribe", "sequence", f"{len(steps)} steps", ms=1)

        rec.tree.commit(
            build, report,
            Op("generate", {"prompt": rec.prompt, "mode": rec.mode,
                            "composition": comp_to_dict(used),
                            "source": planned.source}, seed=rec.seed),
            steps=steps, cost=planned.cost, notes=notes)
        rec.finish("ok" if build.parts else "failed",
                   None if build.parts else "Nothing in this bin could build that. "
                                             "Try a simpler shape, or add bricks.")
    except Exception as exc:                          # never a stack trace at the demo table
        rec.emit("inspector", "error", f"{type(exc).__name__}: {exc}", status="fail")
        rec.finish("failed", f"The build engine failed: {type(exc).__name__}: {exc}")


async def _run_demo_safe(rec: BuildRecord) -> None:
    build, report, steps = await asyncio.to_thread(load_fixture_build)
    tape = load_fixture_tape()
    if tape:
        rec.replay(tape)
    else:
        _emit_report(rec, report, 1)
    rec.tree.commit(build, report,
                    Op("generate", {"prompt": rec.prompt, "source": "fixtures",
                                    "composition": DEMO_COMPOSITION}, seed=rec.seed),
                    steps=steps)
    rec.finish("ok")


def _emit_report(rec: BuildRecord, report: Report, ms: int) -> None:
    """The inspector speaks in the validator's own `human` strings -- Contract 3, verbatim."""
    if report.errors:
        for e in report.errors[:3]:
            rec.emit("inspector", "validate", f"{e.code}: {e.human}", status="fail", ms=ms)
    for w in report.warnings[:3]:
        rec.emit("inspector", "validate", f"{w.code}: {w.human}", status="warn", ms=ms)
    if report.ok:
        s = report.stats
        rec.emit("inspector", "validate",
                 f"valid - {s.get('parts', 0)} parts, {s.get('connections', 0)} joins, "
                 f"{s.get('inventory_remaining', 0)} bricks left", ms=ms)


async def _budgeted(coro):
    """Wall-clock budget, invariant 8. Past it we take the degradation path, we do not wait."""
    try:
        return await asyncio.wait_for(coro, MAX_WALL_MS / 1000)
    except (TimeoutError, asyncio.TimeoutError):
        return None


# ---------------------------------------------------------------- the edit loop (L2)


class EditNotUnderstood(Exception):
    """Raised with a sentence naming what the system CAN do. Bounded and honest beats a no-op."""

    def __init__(self, human: str, nodes: list[str]) -> None:
        super().__init__(human)
        self.human = human
        self.nodes = nodes


# Which argument a size word moves, per generator. Read off the generator signatures rather
# than guessed, so adding a generator does not silently break editing.
_SIZE_WORDS = {
    "longer": ("length", +2), "shorter": ("length", -2),
    "wider": ("width", +2), "narrower": ("width", -2),
    "taller": ("height", +3), "lower": ("height", -3), "shallower": ("height", -3),
    "bigger": ("*", +2), "larger": ("*", +2), "smaller": ("*", -2),
}
_BIG_ARG_ORDER = ("length", "height", "size", "width")


def _node_of(comp: Composition, node_id: str | None, text: str) -> dict:
    by_id = {n["id"]: n for n in comp.nodes}
    if node_id and node_id in by_id:
        return by_id[node_id]
    low = text.lower()
    for nid, node in by_id.items():
        if nid.lower() in low or str(node.get("gen", "")).lower() in low:
            return node
    root = by_id.get(comp.root)
    if root is None:
        raise EditNotUnderstood("That build has no nodes to edit.", list(by_id))
    return root


def _bump(node: dict, arg: str, delta: int) -> str:
    gen = node.get("gen", node["id"])
    spec = GENERATORS.get(gen)
    params = spec.params if spec else {}
    args = dict(node.get("args") or {})
    if arg == "*":
        arg = next((a for a in _BIG_ARG_ORDER if a in params), "")
    if not arg or arg not in params:
        avail = ", ".join(a for a in params if a in _BIG_ARG_ORDER) or "nothing"
        raise EditNotUnderstood(
            f"'{node['id']}' has no size to change that way. It takes: {avail}.",
            [node["id"]])
    current = int(args.get(arg, params[arg][1] or 4))
    args[arg] = max(1, current + delta)
    node["args"] = args
    return f"{node['id']}.{arg} {current} -> {args[arg]}"


def offline_edit(comp: Composition, node_id: str | None, instruction: str,
                 seed: int) -> tuple[Composition, str, str]:
    """Utterance -> a changed composition. Returns (composition, op_kind, human summary).

    The five utterance shapes from docs/04-loop.md §2.1 and nothing else. Anything outside them
    raises `EditNotUnderstood` carrying the node names, because a bounded "here is what I can
    change" beats a text box that silently does nothing.
    """
    low = instruction.lower().strip()
    nodes = [n["id"] for n in comp.nodes]
    comp = comp_from_dict(comp_to_dict(comp))        # never mutate the caller's tree

    # "make it red" / "make the wings white"
    for word, code in sorted(COLOR_WORDS.items(), key=lambda kv: -len(kv[0])):
        if word in low:
            node = _node_of(comp, node_id, low)
            node["color"] = code
            return comp, "recolor", f"{node['id']} is now colour {code} ({word})"

    # "remove the X"
    if any(w in low for w in ("remove", "delete", "drop ", "get rid")):
        node = _node_of(comp, node_id, low)
        if node["id"] == comp.root:
            raise EditNotUnderstood(
                f"'{node['id']}' is the base of the model; removing it removes everything. "
                f"You can change it, or remove one of: {', '.join(n for n in nodes if n != comp.root)}.",
                nodes)
        doomed = {node["id"]}
        changed = True
        while changed:                                # drop orphaned children too
            changed = False
            for n in comp.nodes:
                if n.get("attach_to") in doomed and n["id"] not in doomed:
                    doomed.add(n["id"])
                    changed = True
        comp.nodes = [n for n in comp.nodes if n["id"] not in doomed]
        return comp, "delete_node", f"removed {', '.join(sorted(doomed))}"

    # "add a Y"
    if low.startswith("add") or " add " in low:
        gen = next((g for g in GENERATORS if g in low), None)
        if gen is None:
            raise EditNotUnderstood(
                f"I can add one of: {', '.join(sorted(GENERATORS))}.", nodes)
        nid = gen if gen not in nodes else f"{gen}_{len(nodes) + 1}"
        comp.nodes.append({"id": nid, "gen": gen, "attach_to": comp.root, "at": "top_centre",
                           "color": comp.nodes[0].get("color", 4)})
        return comp, "add_node", f"added {nid} on {comp.root}"

    # "make the X longer / bigger / taller"
    for word, (arg, delta) in _SIZE_WORDS.items():
        if word in low:
            node = _node_of(comp, node_id, low)
            return comp, "edit_subassembly", _bump(node, arg, delta)

    # "I don't like the X" / "different X" / "try another"
    if any(w in low for w in ("different", "another", "don't like", "dont like", "again",
                              "variation", "vary")):
        node = _node_of(comp, node_id, low)
        # Core generators are pure functions of their arguments, so a new seed can only show up
        # as a different argument. Say so rather than pretending there is hidden randomness.
        delta = 2 if (seed % 2 == 0) else -1
        return comp, "edit_subassembly", _bump(node, "*", delta)

    raise EditNotUnderstood(
        "I can make a part bigger or smaller, recolour it, remove it, add another, or try a "
        f"different version of it. The parts of this model are: {', '.join(nodes)}.", nodes)


def _llm_edit(comp: Composition, node_id: str | None, instruction: str, inv: Inventory,
              seed: int) -> tuple[Composition, str] | None:
    llm = _llm_module()
    fn = getattr(llm, "edit", None) if llm is not None else None
    if not callable(fn):
        return None
    try:
        out = fn(instruction=instruction, node_id=node_id, composition=comp_to_dict(comp),
                 inventory=inv, catalog=catalog_text(), seed=seed)
        new = _as_composition(out)
        if new is not None and new.nodes:
            return new, getattr(out, "summary", "") or "edited by the designer"
    except Exception:
        return None
    return None


def composition_of(version: Version) -> Composition:
    """The recipe behind a version. Fixture builds carry `DEMO_COMPOSITION` so edits still work."""
    raw = (version.op.args or {}).get("composition") or DEMO_COMPOSITION
    return comp_from_dict(raw)


def apply_edit(rec: BuildRecord, session: Session, node_id: str | None,
               instruction: str) -> Version:
    """L2: edit the head version's composition, re-compose, re-validate, commit a child version."""
    head = rec.tree.current()
    if head is None:
        raise EditNotUnderstood("This build has no version to edit yet.", [])
    comp = composition_of(head)
    inv = session.inventory()
    seed = rec.seed + head.version

    via = _llm_edit(comp, node_id, instruction, inv, seed)
    if via is not None:
        new_comp, summary = via
        kind, source = "edit_subassembly", "llm"
    else:
        new_comp, kind, summary = offline_edit(comp, node_id, instruction, seed)
        source = "offline"

    rec.emit("designer", "edit", f"{instruction} -> {summary}")

    # An edited tree gets the same fix loop a fresh one does, when that lane is present: a longer
    # chassis can clip the cabin, and that is exactly the failure the ladder exists for.
    outcome = via_llm_loop(rec.prompt, inv, seed, head.build.name, rec.id,
                           composition=comp_to_dict(new_comp))
    if outcome is not None:
        rec.replay(outcome.events)
        build, report, notes, steps = (outcome.build, outcome.report, list(outcome.notes),
                                       outcome.steps)
        used = outcome.composition or comp_to_dict(new_comp)
    else:
        build, report, notes, steps = _compose_now(new_comp, inv, head.build.name, rec.id)
        used = comp_to_dict(new_comp)
        _emit_report(rec, report, 1)
        for n in notes:
            rec.emit("repair", "note", n, status="warn")
        if steps:
            rec.emit("scribe", "sequence", f"{len(steps)} steps", ms=1)

    return rec.tree.commit(
        build, report,
        Op(kind, {"instruction": instruction, "node_id": node_id, "summary": summary,
                  "composition": used, "source": source}, seed=seed),
        steps=steps, notes=notes)


# ---------------------------------------------------------------- export


def ldr_of(version: Version) -> str:
    return to_ldraw(version.build, [list(g) for g in version.steps] or None)
