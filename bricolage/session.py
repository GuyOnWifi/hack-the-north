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


class Session:
    def __init__(self, inventory):
        self.inv = inventory
        self.versions: dict[str, Version] = {}
        self.head: str | None = None
        self._n = 0
        self._redo_stack: list[str] = []

    def _vid(self):
        self._n += 1
        return f"v{self._n}"

    def _commit(self, parent, op, build, report, tape=None):
        vid = self._vid()
        v = Version(vid, parent, op, build, report, tape)
        self.versions[vid] = v
        self.head = vid
        self._redo_stack.clear()
        return v

    # ---- operations ----------------------------------------------------
    def build(self, prompt, seed=0, tape=None, recipe=None, sketch=None):
        res = build_from_prompt(prompt, self.inv, seed, tape=tape, recipe=recipe, sketch=sketch)
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
            nb = engine_c.edit(cur.build, text, tape)
            return self._commit(self.head, {"kind": "edit_c", "text": text, "recipe": engine_c.recipe(nb)},
                                nb, engine_c.report(nb), tape)
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
            if op["kind"] == "build":
                fresh.build(op["prompt"], op["seed"], recipe=op.get("recipe"))
            elif op["kind"] == "edit_c":
                nb = engine_c.from_recipe(op["recipe"])
                fresh._commit(fresh.head, op, nb, engine_c.report(nb))
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
            if v.op["kind"] == "build":
                op = "build " + v.op.get("prompt", "")
            else:
                op = _describe_edit(v.op["edit"])
            lines.append(f"    {'  '*depth}{vid} [{op}] {ok}{mark}")
            for c in children.get(vid, []):
                walk(c, depth + 1)

        for root in children.get(None, []):
            walk(root, 0)
        return "\n".join(lines)
