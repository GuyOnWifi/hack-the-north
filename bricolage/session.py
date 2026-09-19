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
from edit import apply_edit, parse_edit
from validate import validate


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
    def build(self, prompt, seed=0):
        res = build_from_prompt(prompt, self.inv, seed)
        return self._commit(None, {"kind": "build", "prompt": prompt, "seed": seed},
                            res["build"], res["report"], res["tape"])

    def edit(self, text, seed=0):
        cur = self.versions[self.head]
        parsed = parse_edit(text, cur.build)
        if not parsed:
            return cur
        sub, arg, delta = parsed
        nb = apply_edit(cur.build, sub, arg, delta, seed=seed)
        rep = validate(nb, self.inv)
        return self._commit(self.head,
                            {"kind": "edit", "sub": sub, "arg": arg,
                             "delta": delta, "seed": seed}, nb, rep)

    def try_another(self):
        """Re-run the head's op with a new seed as a SIBLING (same parent)."""
        cur = self.versions[self.head]
        op = dict(cur.op)
        op["seed"] = op.get("seed", 0) + 1
        if op["kind"] == "build":
            res = build_from_prompt(op["prompt"], self.inv, op["seed"])
            return self._commit(cur.parent, op, res["build"], res["report"], res["tape"])
        else:  # edit — re-apply against the parent's build
            base = self.versions[cur.parent].build
            nb = apply_edit(base, op["sub"], op["arg"], op["delta"], seed=op["seed"])
            return self._commit(cur.parent, op, nb, validate(nb, self.inv))

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
                fresh.build(op["prompt"], op["seed"])
            else:
                fresh.edit_direct(op)
        return fresh.versions[fresh.head].build

    def edit_direct(self, op):
        cur = self.versions[self.head]
        nb = apply_edit(cur.build, op["sub"], op["arg"], op["delta"], seed=op["seed"])
        return self._commit(self.head, op, nb, validate(nb, self.inv))

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
            op = v.op["kind"] + (f" {v.op.get('prompt','')}" if v.op["kind"] == "build"
                                 else f" {v.op['sub']}.{v.op['arg']}{v.op['delta']:+d}")
            lines.append(f"    {'  '*depth}{vid} [{op}] {ok}{mark}")
            for c in children.get(vid, []):
                walk(c, depth + 1)

        for root in children.get(None, []):
            walk(root, 0)
        return "\n".join(lines)
