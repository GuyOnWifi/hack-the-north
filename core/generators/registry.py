from __future__ import annotations

import inspect
from dataclasses import dataclass, field

from ..model import AttachPoint, Placed

GENERATORS: dict[str, "GenSpec"] = {}


@dataclass
class SubResult:
    parts: list[Placed]
    attach: list[AttachPoint] = field(default_factory=list)
    note: str = ""

    def offset(self, dx: int, dy: int, dz: int, sub: str) -> "SubResult":
        moved = [
            Placed(p.id, p.part, p.color, (p.x + dx, p.y + dy, p.z + dz), p.rot, sub)
            for p in self.parts
        ]
        att = [AttachPoint((a.at[0] + dx, a.at[1] + dy, a.at[2] + dz), a.face,
                           tuple((sx + dx, sz + dz) for sx, sz in a.studs))
               for a in self.attach]
        return SubResult(moved, att, self.note)


@dataclass
class GenSpec:
    name: str
    fn: callable
    tags: tuple[str, ...]
    doc: str
    params: dict


def generator(*tags: str):
    def deco(fn):
        sig = inspect.signature(fn)
        params = {
            n: (p.annotation.__name__ if hasattr(p.annotation, "__name__") else str(p.annotation),
                None if p.default is inspect.Parameter.empty else p.default)
            for n, p in sig.parameters.items()
            if n not in ("alloc", "color", "sub")
        }
        GENERATORS[fn.__name__] = GenSpec(fn.__name__, fn, tags, (fn.__doc__ or "").strip(), params)
        return fn
    return deco


def generate(name: str, alloc, color: int, sub: str = "root", **kwargs) -> SubResult | None:
    spec = GENERATORS.get(name)
    if spec is None:
        raise KeyError(f"unknown generator {name!r}; known: {sorted(GENERATORS)}")
    res = spec.fn(alloc=alloc, color=color, sub=sub, **kwargs)
    # Generators degrade rather than refuse, so "degraded all the way to nothing" is now a real
    # outcome. Normalise it to None here so no caller has to handle an empty SubResult.
    return res if res is not None and res.parts else None


def catalog_text() -> str:
    """The generator catalogue, as the LLM sees it in the system prompt."""
    lines = []
    for g in GENERATORS.values():
        args = ", ".join(
            f"{n}: {t}" + (f" = {d}" if d is not None else "") for n, (t, d) in g.params.items()
        )
        lines.append(f"- {g.name}({args}) [{', '.join(g.tags)}] -- {g.doc.splitlines()[0]}")
    return "\n".join(lines)
