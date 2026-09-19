"""`python -m render` -- make a manual from fixtures (or any build/steps pair) in one command.

Exists because at hour 34 nobody wants to write three lines of Python to get the PDF.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from render import RenderOpts, load_build, load_steps, make_manual  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m render", description=__doc__)
    ap.add_argument("--build", default=str(ROOT / "fixtures" / "build.json"))
    ap.add_argument("--steps", default=str(ROOT / "fixtures" / "steps.json"))
    ap.add_argument("--out", default=str(ROOT / "out" / "manual"))
    ap.add_argument("--width", type=int, default=1200)
    ap.add_argument("--height", type=int, default=900)
    ap.add_argument("--backend", choices=("auto", "leocad", "iso"), default="auto")
    ap.add_argument("--pdf-backend", choices=("auto", "weasyprint", "chrome", "html-only"),
                    default="auto")
    ap.add_argument("--no-thumbs", action="store_true")
    a = ap.parse_args(argv)

    build = load_build(a.build)
    steps = load_steps(a.steps)
    r = make_manual(build, steps, a.out,
                    RenderOpts(width=a.width, height=a.height),
                    backend=a.backend, pdf_backend=a.pdf_backend,
                    thumbnails=not a.no_thumbs)

    print(f"{build.name}: {len(build.parts)} parts, {len(steps)} steps, "
          f"renderer={r.steps.backend}, pdf={r.pdf.backend}")
    print(f"  html: {r.html_path}")
    print(f"  pdf : {r.pdf.path if r.pdf.ok else '(none)'}")
    for n in r.notes:
        print(f"  note: {n}")
    return 0 if r.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
