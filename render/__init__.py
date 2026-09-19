"""Build + steps -> step PNGs -> an HTML manual -> a PDF.

One call, `make_manual`, and four degradation steps built into it, because every external
thing this path could want is a thing that will not be installed at the demo:

    LeoCAD present?      -> LeoCAD renders.   else -> the built-in isometric renderer.
    WeasyPrint present?  -> PDF.              else -> headless Chrome, which every laptop
                                                      already has.  else -> the HTML, and
                                                      one sentence saying why.

Everything here is pure local computation: no network, no API key, no system binaries
required. That is the point of the module.

    from render import make_manual, load_build, load_steps
    build = load_build("fixtures/build.json")
    steps = load_steps("fixtures/steps.json")
    result = make_manual(build, steps, "out/manual")
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass

from core.model import Build, Placed, SubAssembly

from .manual_html import callouts, manual_html
from .pdf import PdfResult, chrome_path, html_to_pdf, weasyprint_available
from .steps_png import (Camera, RenderOpts, StepRender, ldraw_color_name, ldraw_rgb,
                        leocad_path, part_name, render_hero, render_part, render_steps)

__all__ = [
    "make_manual", "ManualResult", "load_build", "load_steps",
    "RenderOpts", "StepRender", "Camera", "PdfResult",
    "render_steps", "render_part", "render_hero", "manual_html", "html_to_pdf",
    "callouts", "leocad_path", "weasyprint_available", "chrome_path",
    "ldraw_rgb", "ldraw_color_name", "part_name",
]


# ---------------------------------------------------------------- fixtures -> model

def _placed(d: dict) -> Placed:
    # Translate BrickLink-style ids to LDraw filenames -- see core.meta.resolve_id.
    from core import meta as _meta
    part = _meta.resolve_id(d["part"]) or d["part"]
    return Placed(id=d["id"], part=part, color=int(d["color"]),
                  pos=tuple(int(v) for v in d["pos"]), rot=int(d.get("rot", 0)),
                  sub=d.get("sub", "root"))


def load_build(path) -> Build:
    """Parse a contract-2 build.json. Kept here so the render lane needs no other lane."""
    d = json.loads(pathlib.Path(path).read_text())
    subs = tuple(SubAssembly(id=k, parent=v.get("parent"))
                 for k, v in (d.get("subassemblies") or {}).items())
    return Build(id=d["id"], name=d.get("name", d["id"]),
                 parts=tuple(_placed(p) for p in d["parts"]),
                 subassemblies=subs, version=int(d.get("version", 0)),
                 provenance=d.get("provenance", {}))


def load_steps(path, build: Build | None = None) -> list[list[Placed]]:
    """Parse a steps file. Accepts BOTH lane formats.

    The build lane emits steps that reference parts by id -- `"parts": ["p33", "p34"]` -- which is
    the normalised form and the one on main, so it is what we resolve against the Build. Our own
    earlier fixtures embedded whole part objects instead. Reading both means the render lane keeps
    working whichever fixture it is handed, and nobody has to regenerate files to see a manual.

    Pass `build` when the steps use ids; without it an id-based file cannot be resolved and we say
    so, rather than silently returning empty steps and rendering a blank manual.
    """
    d = json.loads(pathlib.Path(path).read_text())
    by_id = {p.id: p for p in build.parts} if build is not None else {}
    out: list[list[Placed]] = []
    for step in d["steps"]:
        parts: list[Placed] = []
        for item in step["parts"]:
            if isinstance(item, dict):
                parts.append(_placed(item))
                continue
            placed = by_id.get(item)
            if placed is None:
                raise ValueError(
                    f"step references part {item!r} by id, but it is not in the build. "
                    f"Pass the Build: load_steps(path, build=load_build(...))."
                )
            parts.append(placed)
        out.append(parts)
    return out


# ---------------------------------------------------------------- the pipeline

@dataclass(frozen=True, slots=True)
class ManualResult:
    html_path: pathlib.Path
    pdf: PdfResult
    steps: StepRender
    thumbs: dict[tuple[str, int], pathlib.Path]
    hero: pathlib.Path | None
    notes: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """True if there is a manual to show. A missing PDF is not a failure."""
        return self.html_path.exists() and len(self.steps.images) > 0


def make_manual(build: Build, steps: list[list[Placed]], out_dir,
                opts: RenderOpts = RenderOpts(), backend: str = "auto",
                thumbnails: bool = True, embed: bool = True,
                pdf: bool = True, pdf_backend: str = "auto") -> ManualResult:
    """Render every step, write the HTML manual, and make a PDF if anything can.

    `backend` picks the step renderer ("auto" | "leocad" | "iso"); `pdf_backend` picks the
    PDF writer ("auto" | "weasyprint" | "chrome" | "html-only"). Both default to taking the
    best thing that is actually installed, which is usually neither of the fancy ones.
    """
    out = pathlib.Path(out_dir)
    (out / "steps").mkdir(parents=True, exist_ok=True)
    notes: list[str] = []

    sr = render_steps(build, steps, out / "steps", opts, backend=backend)
    notes.extend(sr.notes)

    hero = render_hero(build, out / "steps" / "hero.png", opts)

    thumbs: dict[tuple[str, int], pathlib.Path] = {}
    if thumbnails:
        (out / "parts").mkdir(parents=True, exist_ok=True)
        for c in callouts(build.parts):
            p = out / "parts" / f"{c.part}_{c.color}.png"
            render_part(c.part, c.color).save(p)
            thumbs[(c.part, c.color)] = p

    doc = manual_html(build, steps, sr.images, hero=hero, thumbs=thumbs, embed=embed)
    res = html_to_pdf(doc, out / "manual.pdf", backend=pdf_backend) if pdf else None
    if res is None:
        html_path = out / "manual.html"
        html_path.write_text(doc, encoding="utf-8")
        res = PdfResult(False, html_path, html_path, "html-only", "PDF generation was skipped.")
    if not res.ok:
        notes.append(res.note)

    return ManualResult(res.html_path, res, sr, thumbs, hero, tuple(notes))
