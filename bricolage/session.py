"""The version tree + session orchestration (decision D11). Every operation is
an immutable, validated snapshot in a tree: undo, redo, "try another" and
replay are one mechanism. An *op* is recorded (not the LLM's reasoning), so
re-running the op list from the root reproduces any version — and re-running an
op with a new seed produces a sibling ("try another").

  op kinds:
    build  {prompt}                 -> full pipeline (router/designer/repair)
    edit   {sub, arg, delta}        -> re-run one generator, children reattach
"""
from __future__ import annotations
from dataclasses import dataclass, field

from pipeline import build_from_prompt
import engine_c
from edit import apply_edit, parse_edit, describe as _describe_edit
from validate import validate
from repair import Budget, fix
from tape import Tape


@dataclass
class Version:
    id: str
    parent: str | None
    op: dict                 # {kind, ...params, seed}
    build: object
    report: object
    tape: object = None
    model: object = None     # the editable brickify.edits.Model, for C builds


class Session:
    def __init__(self, inventory):
        self.inv = inventory
        self.versions: dict[str, Version] = {}
        self.head: str | None = None
        self._n = 0
        self._redo_stack: list[str] = []
        self.lock = __import__("threading").Lock()

    def _vid(self):
        self._n += 1
        return f"v{self._n}"

    def _commit(self, parent, op, build, report, tape=None, model=None):
        vid = self._vid()
        v = Version(vid, parent, op, build, report, tape, model)
        self.versions[vid] = v
        self.head = vid
        self._redo_stack.clear()
        return v

    # ---- part-level editing (docs/EDITING.md D.0) ----------------------
    def load_ldr(self, name, text, source=None):
        """A finished LDraw model becomes a new ROOT version. No model call."""
        build, model = engine_c.from_ldr(name, text, source)
        tape = Tape()
        n_steps = len({p.step for p in model.parts})
        warn = sorted({p.pid for p in model.parts
                       if engine_c.partlib.info(p.pid, model.lib).source == "fallback"})
        tape.emit("scribe", "edit.load", f"Read {len(model.parts)} pieces in {n_steps} steps")
        for pid in warn[:4]:
            tape.emit("scribe", "edit.load",
                      f"I don't know the shape of part {pid}, so I'm treating it as a 1x1 brick.",
                      status="warn")
        st = build.provenance["stability"]
        clash = build.provenance["collisions"]
        tape.emit("inspector", "edit.gate",
                  ("It stands. " if st["stable"] else "It already leans a little. ")
                  + (f"{clash} pieces already overlap a little; I'll leave those alone"
                     if clash else "Nothing overlaps"),
                  status="ok" if st["stable"] and not clash else "warn")
        return self._commit(None, {"kind": "load_ldr", "name": name, "source": source, "ldr": text},
                            build, engine_c.report(build), tape, model)

    def model_at(self, vid=None):
        v = self.versions.get(vid or self.head)
        if not v or not engine_c.is_c(v.build):
            return None
        if v.model is None and v.build.provenance.get("ldr"):
            v.model = engine_c.to_model(v.build)
        return v.model

    def edit_parts(self, ops, dry_run=False, base=None, text=None, path="direct", seed=0):
        """The one part-level edit path. Returns (Version | None, edits.Result)."""
        from brickify import edits as E
        cur = self.versions.get(self.head)
        if not cur or not engine_c.is_c(cur.build):
            return None, E.Result(False, "NO_MODEL", E.HUMAN["NO_MODEL"])
        if base is not None and base != self.head:
            return None, E.Result(False, "STALE", E.HUMAN["STALE"])
        model = self.model_at(self.head)
        if model is None:
            return None, E.Result(False, "NO_MODEL", E.HUMAN["NO_MODEL"])
        res = E.apply(model, ops, seed=seed)
        if not res.accepted or dry_run:
            return None, res
        prov = cur.build.provenance
        build = engine_c.build_from_model(
            res.model, cur.build.name, bid=cur.build.id, version=cur.build.version + 1,
            source=prov.get("source"), lib_text=prov.get("lib", ""), run=prov.get("run"),
            round_=prov.get("round"), edited=True)
        tape = Tape()
        for actor, kind, txt, status in res.events:
            tape.emit(actor, kind, txt, status=status)
        op = {"kind": "edit_direct_c", "seed": seed, "path": path, "text": text,
              "ops": [dict(o) for o in res.ops], "new_ids": list(res.added),
              "human": res.human}
        v = self._commit(self.head, op, build, engine_c.report(build), tape, res.model)
        return v, res

    # ---- operations ----------------------------------------------------
    def build(self, prompt, seed=0, tape=None, recipe=None):
        res = build_from_prompt(prompt, self.inv, seed, tape=tape, recipe=recipe)
        # record the resolved LLM proposal so replay reproduces it without the model
        return self._commit(None, {"kind": "build", "prompt": prompt, "seed": seed,
                                   "recipe": res["recipe"]},
                            res["build"], res["report"], res["tape"])

    def _run_edit(self, base_build, ops, seed):
        """Apply the edit ops and run through the same FIX loop as a build, so it
        streams a tape and self-heals inventory/physics issues."""
        tape = Tape()
        tape.emit("designer", "edit",
                  f"{_describe_edit(ops)} — keeping everything else fixed", ms=200)
        nb = apply_edit(base_build, ops, seed=seed)
        if nb.parts == base_build.parts:
            tape.emit("inspector", "edit", "that edit doesn't apply to this "
                      "build — nothing changed", status="warn", ms=8)
        result = fix(nb, self.inv, Budget(seed=seed), tape)
        return result.build, result.report, tape

    def edit(self, text, seed=0, tape=None):
        cur = self.versions[self.head]
        if engine_c.is_c(cur.build):
            # pipeline C edits in plain language: it revises the model's brief
            tape = tape or Tape()
            chain = self.direct_chain()
            nb = engine_c.edit(cur.build, text, tape)
            model = engine_c.to_model(nb)
            reapplied, dropped = [], []
            if chain:
                model, reapplied, dropped = reapply_direct(model, chain)
                tape.emit("repair", "edit.reapply",
                          f"Kept {len(reapplied)} of your {len(chain)} earlier changes",
                          status="ok" if not dropped else "warn")
                for d in dropped:
                    tape.emit("repair", "edit.reapply", d["human"], status="warn")
                prov = nb.provenance
                nb = engine_c.build_from_model(model, nb.name, bid=nb.id, version=nb.version,
                                               source=prov.get("source"), lib_text=prov.get("lib", ""),
                                               run=prov.get("run"), round_=prov.get("round"),
                                               edited=True)
            op = {"kind": "edit_c", "text": text, "recipe": engine_c.recipe(nb),
                  "reapplied": reapplied, "dropped": dropped}
            return self._commit(self.head, op, nb, engine_c.report(nb), tape, model)
        op = parse_edit(text, cur.build)
        if not op:
            return cur
        nb, rep, tape = self._run_edit(cur.build, op, seed)
        return self._commit(self.head, {"kind": "edit", "edit": op, "seed": seed},
                            nb, rep, tape)

    def try_another(self):
        """Re-run the head's op with a new seed as a SIBLING (same parent)."""
        cur = self.versions[self.head]
        op = dict(cur.op)
        op["seed"] = op.get("seed", 0) + 1
        if op["kind"] == "build":
            res = build_from_prompt(op["prompt"], self.inv, op["seed"])  # fresh sample
            op["recipe"] = res["recipe"]                                 # its own recipe
            return self._commit(cur.parent, op, res["build"], res["report"], res["tape"])
        elif op["kind"] == "edit_c":  # ask for the same change again on the parent
            base = self.versions[cur.parent].build
            tape = Tape()
            nb = engine_c.edit(base, op["text"], tape)
            op["recipe"] = engine_c.recipe(nb)
            return self._commit(cur.parent, op, nb, engine_c.report(nb), tape)
        else:  # edit — re-apply against the parent's build
            base = self.versions[cur.parent].build
            nb, rep, tape = self._run_edit(base, op["edit"], op["seed"])
            return self._commit(cur.parent, op, nb, rep, tape)

    # ---- navigation ----------------------------------------------------
    def undo(self):
        cur = self.versions[self.head]
        if cur.parent:
            self._redo_stack.append(self.head)
            self.head = cur.parent
        return self.versions[self.head]

    def redo(self):
        if self._redo_stack:
            self.head = self._redo_stack.pop()
        return self.versions[self.head]

    # ---- replay (determinism proof) ------------------------------------
    def direct_chain(self):
        """The part-level edits made since the last brief build / file load,
        oldest first, each with the model it was applied to."""
        out, node = [], self.versions.get(self.head)
        while node is not None and node.op.get("kind") == "edit_direct_c":
            out.append({"ops": node.op["ops"], "new_ids": node.op.get("new_ids", []),
                        "base": self.versions[node.parent].model if node.parent else None,
                        "label": node.op.get("text") or _direct_label(node.op)})
            node = self.versions.get(node.parent) if node.parent else None
        out.reverse()
        return [s for s in out if s["base"] is not None]

    def replay(self):
        """Re-execute the op chain from root to head on a fresh session; the
        resulting build must be byte-identical (invariant #9 / DoD #2)."""
        chain, node = [], self.versions[self.head]
        while node:
            chain.append(node.op)
            node = self.versions[node.parent] if node.parent else None
        chain.reverse()
        fresh = Session(self.inv)
        for op in chain:
            kind = op["kind"]
            if kind == "build":
                fresh.build(op["prompt"], op["seed"], recipe=op.get("recipe"))
            elif kind == "load_ldr":
                fresh.load_ldr(op["name"], op["ldr"], op.get("source"))
            elif kind == "edit_direct_c":
                v, res = fresh.edit_parts(op["ops"], base=None, text=op.get("text"),
                                          path=op.get("path", "direct"), seed=op.get("seed", 0))
                if v is None:
                    raise RuntimeError(f"replay diverged: {res.code} — {res.human}")
            elif kind == "edit_c":
                nb = engine_c.from_recipe(op["recipe"])
                model = engine_c.to_model(nb)
                fresh._commit(fresh.head, op, nb, engine_c.report(nb), None, model)
                for ops in op.get("reapplied", []):
                    fresh.edit_parts(ops, base=None)
            else:
                fresh.edit_direct(op)
        return fresh.versions[fresh.head].build

    def edit_direct(self, op):
        cur = self.versions[self.head]
        nb, rep, tape = self._run_edit(cur.build, op["edit"], op["seed"])
        return self._commit(self.head, op, nb, rep, tape)

    def tree_ascii(self):
        """Render the version tree for the UI/tape."""
        children = {}
        for v in self.versions.values():
            children.setdefault(v.parent, []).append(v.id)
        lines = []

        def walk(vid, depth):
            v = self.versions[vid]
            mark = " <- HEAD" if vid == self.head else ""
            ok = "ok" if v.report.ok else "DEGRADED"
            kind = v.op.get("kind")
            if kind == "build":
                op = "build " + v.op.get("prompt", "")
            elif kind == "load_ldr":
                op = "load " + str(v.op.get("name", ""))
            elif kind == "edit_c":
                op = f'edit_c "{v.op.get("text", "")}"'
            elif kind == "edit_direct_c":
                op = _direct_label(v.op)
            elif "edit" in v.op:
                op = _describe_edit(v.op["edit"])
            else:
                op = str(kind)
            lines.append(f"    {'  '*depth}{vid} [{op}] {ok}{mark}")
            for c in children.get(vid, []):
                walk(c, depth + 1)

        for root in children.get(None, []):
            walk(root, 0)
        return "\n".join(lines)


# ---- part-level edits across a brief-level rebuild (EDITING.md F.3) -------
def _direct_label(op) -> str:
    """The first segment of what the user was told, for the version tree."""
    if op.get("human"):
        return op["human"].split(" \u00b7 ")[0]
    ops = op.get("ops") or []
    if not ops:
        return "edit"
    o = ops[0]
    n = len(o.get("ids", [])) or 1
    kind = o["op"]
    if kind == "recolour":
        return f"{n} pieces recoloured"
    if kind == "move":
        return f"moved {n} piece{'s' if n != 1 else ''}"
    if kind == "rotate":
        return f"turned {n} piece{'s' if n != 1 else ''}"
    if kind == "delete":
        return f"removed {n} piece{'s' if n != 1 else ''}"
    if kind == "duplicate":
        return f"copied {n} piece{'s' if n != 1 else ''}"
    return f"added {o.get('part', 'a piece')}"


def _sig(p):
    """What identifies a part across a rebuild: what it is, where it sits, how
    it is turned. Colour is deliberately not part of it."""
    return (p.pid, p.body,
            tuple(round(float(v), 0) + 0.0 for v in p.M[:3, 3]),
            tuple(round(float(v), 2) + 0.0 for v in p.M[:3, :3].ravel()))


def reapply_direct(model, steps):
    """Replay recorded direct edits onto a freshly rebuilt model.

    `steps` = [{"ops", "new_ids", "base" (the Model the op ran against), "label"}].
    Returns (model, reapplied_ops, dropped) — a step whose pieces no longer
    exist, or that the gate refuses, is dropped and named, never lost quietly."""
    from brickify import edits as E

    mapping: dict = {}
    reapplied: list = []
    dropped: list = []
    for step in steps:
        live = {_sig(p): p.id for p in model.parts}
        old = {p.id: p for p in step["base"].parts}
        def translate(i):
            if i in mapping:
                return mapping[i]
            p = old.get(i)
            return live.get(_sig(p)) if p is not None else None

        translated, ok = [], True
        for raw in step["ops"]:
            o = dict(raw)
            if "ids" in o:
                ids = [translate(i) for i in o["ids"]]
                if any(t is None for t in ids):
                    ok = False
                    break
                o["ids"] = ids
            if o.get("on"):
                t = translate(o["on"])
                if t is None:
                    ok = False
                    break
                o["on"] = t
            o["settle"] = False
            translated.append(o)
        if not ok:
            dropped.append({"op": step["ops"], "human": f"Couldn't keep “{step['label']}”: those pieces were rebuilt"})
            continue
        try:
            res = E.apply(model, translated)
        except E.OpError as e:
            dropped.append({"op": step["ops"], "human": f"Couldn't keep “{step['label']}”: {e.human}"})
            continue
        if not res.accepted:
            dropped.append({"op": step["ops"], "human": f"Couldn't keep “{step['label']}”: {res.human}"})
            continue
        for old_id, new_id in zip(step.get("new_ids", []), res.added):
            mapping[old_id] = new_id
        model = res.model
        reapplied.append([dict(o) for o in res.ops])
    return model, reapplied, dropped
