"""The validator. Ordinary deterministic code -- NOT a model. This is the law.

Every mutation from every source (generators, LLM edits, substitutions, manual UI edits) goes
through `validate()`. If this is right, nothing downstream can produce a model that could not
physically exist.

The `human` string on every error is user-facing copy AND the text fed back to the repair loop,
so it is written once, well.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import meta as meta_mod
from .model import Build, Inventory, Placed


@dataclass(frozen=True, slots=True)
class Issue:
    code: str
    human: str
    parts: tuple[str, ...] = ()
    sub: str | None = None
    cell: tuple[int, int, int] | None = None

    def to_dict(self) -> dict:
        d = {"code": self.code, "human": self.human}
        if self.parts: d["parts"] = list(self.parts)
        if self.sub: d["sub"] = self.sub
        if self.cell: d["cell"] = list(self.cell)
        return d


@dataclass(frozen=True, slots=True)
class Report:
    ok: bool
    errors: tuple[Issue, ...] = ()
    warnings: tuple[Issue, ...] = ()
    stats: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": [i.to_dict() for i in self.errors],
            "warnings": [i.to_dict() for i in self.warnings],
            "stats": self.stats,
        }


def occupancy(build: Build) -> tuple[dict[tuple[int, int, int], str], list[Issue]]:
    """Map every filled grid cell to the part occupying it. Reports overlaps."""
    cells: dict[tuple[int, int, int], str] = {}
    errors: list[Issue] = []
    for p in build.parts:
        m = meta_mod.get(p.part)
        for cx, cz in m.cells(p.rot):
            for k in range(m.h):
                key = (p.x + cx, p.y + k, p.z + cz)
                other = cells.get(key)
                if other is not None:
                    errors.append(Issue(
                        "OVERLAP",
                        f"{m.name} '{p.id}' overlaps '{other}' at stud ({key[0]}, {key[2]}), "
                        f"plate layer {key[1]}",
                        parts=(p.id, other), cell=key,
                    ))
                else:
                    cells[key] = p.id
    return cells, errors


def _top_studs(p: Placed, m) -> set[tuple[int, int]]:
    return {(p.x + cx, p.z + cz) for cx, cz in m.stud_cells(p.rot)}


def _bottom_antistuds(p: Placed, m) -> set[tuple[int, int]]:
    return {(p.x + cx, p.z + cz) for cx, cz in m.antistud_cells(p.rot)}


def connections(build: Build) -> list[tuple[str, str, int]]:
    """Stud<->anti-stud contacts as (lower_id, upper_id, n_studs).

    A contact exists when the lower part's top plane is the upper part's bottom plane AND a
    stud cell coincides with an anti-stud cell. Overlapping footprints alone are NOT a
    connection -- a tile has no studs, so nothing attaches on top of it.
    """
    by_top: dict[int, list[tuple[Placed, object]]] = {}
    by_bottom: dict[int, list[tuple[Placed, object]]] = {}
    for p in build.parts:
        m = meta_mod.get(p.part)
        by_top.setdefault(p.y + m.h, []).append((p, m))
        by_bottom.setdefault(p.y, []).append((p, m))

    out: list[tuple[str, str, int]] = []
    for level, lowers in by_top.items():
        uppers = by_bottom.get(level, [])
        if not uppers:
            continue
        for lp, lm in lowers:
            studs = _top_studs(lp, lm)
            if not studs:
                continue
            for up, um in uppers:
                shared = studs & _bottom_antistuds(up, um)
                if shared:
                    out.append((lp.id, up.id, len(shared)))
    return out


def validate(build: Build, inventory: Inventory | None = None) -> Report:
    errors: list[Issue] = []
    warnings: list[Issue] = []

    if not build.parts:
        return Report(False, (Issue("EMPTY", "The build has no parts in it."),), (), {"parts": 0})

    missing = sorted({p.part for p in build.parts if not meta_mod.has(p.part)})
    if missing:
        return Report(False, (Issue(
            "UNKNOWN_PART",
            f"No grid metadata for {', '.join(missing)} -- these parts cannot be placed. "
            f"Remember bricknet keys are exact LDraw filenames (e.g. '3023b', not '3023').",
            parts=tuple(missing),
        ),), (), {"parts": len(build.parts)})

    cells, overlap_errors = occupancy(build)
    errors.extend(overlap_errors)

    conns = connections(build)
    by_id = {p.id: p for p in build.parts}

    # --- support: everything is on the ground or attached to something below it
    supported = {upper for _, upper, _ in conns}
    for p in build.parts:
        if p.y == 0 or p.id in supported:
            continue
        m = meta_mod.get(p.part)
        errors.append(Issue(
            "UNSUPPORTED",
            f"{m.name} '{p.id}' floats at plate layer {p.y} with nothing under it. "
            f"Lower it to the ground or put a part beneath it with studs at ({p.x}, {p.z}).",
            parts=(p.id,), sub=p.sub, cell=p.pos,
        ))

    # --- connectivity: one single component
    adj: dict[str, set[str]] = {p.id: set() for p in build.parts}
    for a, b, _ in conns:
        adj[a].add(b); adj[b].add(a)
    seen: set[str] = set()
    components: list[set[str]] = []
    for start in adj:
        if start in seen:
            continue
        stack, comp = [start], set()
        while stack:
            n = stack.pop()
            if n in comp:
                continue
            comp.add(n); seen.add(n)
            stack.extend(adj[n] - comp)
        components.append(comp)
    if len(components) > 1:
        components.sort(key=len, reverse=True)
        for comp in components[1:]:
            subs = sorted({by_id[i].sub for i in comp})
            errors.append(Issue(
                "DISCONNECTED",
                f"{len(comp)} part(s) in {', '.join(subs)} form a separate piece that does not "
                f"attach to the main model. They would fall off.",
                parts=tuple(sorted(comp)), sub=subs[0] if len(subs) == 1 else None,
            ))

    # --- inventory budget
    if inventory is not None:
        for (part, color), need in sorted(build.counts.items()):
            have = inventory.qty(part, color)
            if need > have:
                m = meta_mod.get(part)
                elsewhere = inventory.qty_any_color(part) - have
                extra = (f" You have {elsewhere} in other colours."
                         if elsewhere > 0 else " You have none in any other colour either.")
                errors.append(Issue(
                    "OUT_OF_BUDGET",
                    f"Needs {need}x {m.name} in colour {color}; you have {have}.{extra}",
                    parts=(part,),
                ))

    # --- bond: warn when vertical seams stack (the model builds, then snaps in half)
    seam_score = _seam_score(build)
    if seam_score > 0.4:
        warnings.append(Issue(
            "WEAK_BOND",
            f"{round(seam_score * 100)}% of joins sit directly above another join. The model "
            f"will build, but it will split along that line when you pick it up. Stagger the "
            f"parts like brickwork.",
        ))

    used = sum(build.counts.values())
    stats = {
        "parts": used,
        "cells": len(cells),
        "connections": len(conns),
        "seam_score": round(seam_score, 3),
        "layers": max(p.y for p in build.parts) + 1,
    }
    if inventory is not None:
        stats["inventory_remaining"] = inventory.total - used

    return Report(not errors, tuple(errors), tuple(warnings), stats)


def _seam_score(build: Build) -> float:
    """Fraction of vertical joins that sit directly above another join.

    Seams are collected per COURSE -- the level where parts start -- not per plate level. A
    3-plate brick occupies three levels but introduces one seam, and comparing its own levels
    against each other would score every wall as perfectly aligned.
    """
    seams_by_course: dict[int, set[tuple[int, int]]] = {}
    spans_by_course: dict[int, dict[int, tuple[int, int]]] = {}
    for p in build.parts:
        m = meta_mod.get(p.part)
        w, d = m.footprint(p.rot)
        s = seams_by_course.setdefault(p.y, set())
        rows = spans_by_course.setdefault(p.y, {})
        for cz in range(d):
            z = p.z + cz
            s.add((p.x, z))
            s.add((p.x + w, z))
            lo, hi = rows.get(z, (p.x, p.x + w))
            rows[z] = (min(lo, p.x), max(hi, p.x + w))

    # The outer boundary of the model is not a seam -- it is the edge of the model, and it
    # aligns trivially on anything rectangular. Only interior joins can split.
    for y, rows in spans_by_course.items():
        seams_by_course[y] = {
            (x, z) for (x, z) in seams_by_course[y]
            if z in rows and rows[z][0] < x < rows[z][1]
        }

    courses = sorted(seams_by_course)
    if len(courses) < 2:
        return 0.0
    total = aligned = 0
    for lo, hi in zip(courses, courses[1:]):
        a, b = seams_by_course[lo], seams_by_course[hi]
        if not a:
            continue
        total += len(a)
        aligned += len(a & b)
    return aligned / total if total else 0.0
