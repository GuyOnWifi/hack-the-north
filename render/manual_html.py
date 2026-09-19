"""The manual as one self-contained HTML document: cover, a page per step, a parts list.

WHY HTML and not a PDF library directly
---------------------------------------
Two consumers, one source. The frontend can iframe this exact document, and WeasyPrint turns
the same bytes into the PDF a judge can hold. Writing the layout twice is how the two drift.

WHY images are inlined as data URIs by default
----------------------------------------------
A manual that only renders when a sibling directory happens to be next to it is a manual that
breaks the moment anyone moves or emails it. One file, no assets, no base-url argument.

Page geometry is A4 landscape because a step render is wider than it is tall and the parts
panel wants to sit beside it, not above it.
"""

from __future__ import annotations

import base64
import html
import mimetypes
import pathlib
from dataclasses import dataclass

from core.model import Build, Placed

from .steps_png import MANUAL_BLUE, ldraw_color_name, ldraw_rgb, part_name

TRADEMARK = ("LEGO® is a trademark of the LEGO Group, which does not sponsor, "
             "authorize or endorse this project.")


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#%02X%02X%02X" % rgb


PAGE_BG = _hex(MANUAL_BLUE)


# ---------------------------------------------------------------- data prep

@dataclass(frozen=True, slots=True)
class Callout:
    """One row of a parts panel: a distinct (part, colour) and how many of it."""

    part: str
    color: int
    qty: int

    @property
    def name(self) -> str:
        return part_name(self.part)

    @property
    def color_name(self) -> str:
        return ldraw_color_name(self.color)


def callouts(parts) -> list[Callout]:
    """Distinct (part, colour) with counts, ordered biggest group first then by part id."""
    counts: dict[tuple[str, int], int] = {}
    for p in parts:
        counts[(p.part, p.color)] = counts.get((p.part, p.color), 0) + 1
    rows = [Callout(part, color, n) for (part, color), n in counts.items()]
    rows.sort(key=lambda c: (-c.qty, c.part, c.color))
    return rows


def _data_uri(path) -> str:
    p = pathlib.Path(path)
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode('ascii')}"


def _src(path, embed: bool) -> str:
    return _data_uri(path) if embed else pathlib.Path(path).name


# ---------------------------------------------------------------- CSS

# Deliberately NO flexbox and NO grid: this stylesheet has to lay out identically in a
# browser and in WeasyPrint, whose flex/grid support varies by version and by the cairo it
# was built against. Absolute positioning and inline-block are the boring subset that both
# have implemented correctly for a decade.
CSS = f"""
@page {{ size: A4 landscape; margin: 0; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; }}
body {{
  font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
  color: #12222E; background: {PAGE_BG};
}}
.page {{
  position: relative; width: 297mm; height: 210mm; overflow: hidden;
  background: {PAGE_BG}; page-break-after: always; break-after: page;
  padding: 14mm 16mm;
}}
.page:last-child {{ page-break-after: auto; break-after: auto; }}
.folio {{ position: absolute; right: 16mm; bottom: 8mm; font-size: 9pt; color: #3B6A8C; }}
.mark {{ position: absolute; left: 16mm; bottom: 8mm; font-size: 6.5pt; color: #6B93AF;
         width: 170mm; }}

/* --- cover ------------------------------------------------------------ */
.cover h1 {{ font-size: 50pt; line-height: 1.04; margin: 0; letter-spacing: -0.02em; }}
.kicker {{ font-size: 11pt; letter-spacing: 0.30em; text-transform: uppercase;
           margin: 0 0 5mm; color: #3B6A8C; }}
.hero {{ height: 96mm; margin: 6mm 0 8mm; text-align: center; }}
.hero img {{ max-width: 240mm; max-height: 96mm; }}
.fact {{ display: inline-block; vertical-align: top; margin-right: 14mm; }}
.fact .n {{ font-size: 30pt; font-weight: 700; line-height: 1; }}
.fact .l {{ font-size: 9pt; text-transform: uppercase; letter-spacing: 0.16em; color: #3B6A8C; }}

/* --- step page -------------------------------------------------------- */
.col {{ position: absolute; left: 16mm; top: 14mm; width: 74mm; }}
.stepno {{
  display: inline-block; min-width: 26mm; height: 22mm; padding: 0 5mm;
  line-height: 22mm; text-align: center;
  background: #12222E; color: {PAGE_BG};
  font-size: 32pt; font-weight: 700; border-radius: 3mm;
}}
.sub {{ margin-top: 3mm; font-size: 8.5pt; letter-spacing: 0.16em;
        text-transform: uppercase; color: #3B6A8C; }}
.panel {{
  margin-top: 6mm; padding: 4mm; border-radius: 4mm;
  background: #E4F0FA; border: 0.6mm solid #A9C8DF;
}}
.panel h2 {{ margin: 0 0 2mm; font-size: 8pt; letter-spacing: 0.18em;
             text-transform: uppercase; color: #3B6A8C; font-weight: 600; }}
.row {{ padding: 1.4mm 0; }}
.row + .row {{ border-top: 0.3mm solid #C3DAEB; }}
.thumb {{ width: 13mm; height: 13mm; vertical-align: middle; margin-right: 2mm; }}
.swatch {{ display: inline-block; width: 13mm; height: 13mm; vertical-align: middle;
           margin-right: 2mm; border-radius: 1mm; border: 0.3mm solid #12222E; }}
.qty {{ display: inline-block; width: 11mm; vertical-align: middle;
        font-size: 14pt; font-weight: 700; }}
.ptext {{ display: inline-block; width: 38mm; vertical-align: middle; }}
.pname {{ font-size: 9pt; line-height: 1.2; }}
.pmeta {{ font-size: 7pt; color: #3B6A8C; }}
.shot {{ margin-left: 82mm; padding-top: 14mm; text-align: center; }}
.shot img {{ max-width: 100%; max-height: 152mm; }}

/* --- parts list ------------------------------------------------------- */
.list h1 {{ font-size: 24pt; margin: 0 0 5mm; }}
.cell {{
  display: inline-block; vertical-align: top; width: 84mm; margin: 0 2mm 2mm 0;
  background: #E4F0FA; border: 0.4mm solid #A9C8DF; border-radius: 2.5mm; padding: 1mm 3mm;
}}
"""


# ---------------------------------------------------------------- fragments

def _callout_row(c: Callout, thumbs: dict[tuple[str, int], object], embed: bool) -> str:
    thumb = thumbs.get((c.part, c.color))
    img = (f'<img class="thumb" src="{_src(thumb, embed)}" alt="">' if thumb
           else f'<span class="thumb swatch" style="background:{_hex(ldraw_rgb(c.color))}"></span>')
    return (
        '<div class="row">'
        f'{img}'
        f'<span class="qty">{c.qty}&#215;</span>'
        '<span class="ptext">'
        f'<span class="pname">{html.escape(c.name)}</span><br>'
        f'<span class="pmeta">{html.escape(c.color_name)} &middot; {html.escape(c.part)}</span>'
        '</span>'
        '</div>'
    )


def _step_page(index: int, total: int, page: int, pages: int, group: list[Placed],
               image, thumbs, embed: bool) -> str:
    subs = sorted({p.sub for p in group})
    rows = "".join(_callout_row(c, thumbs, embed) for c in callouts(group))
    return f"""
<section class="page step">
  <div class="col">
    <div class="stepno">{index}</div>
    <div class="sub">{html.escape(", ".join(subs))} &middot; step {index} of {total}</div>
    <div class="panel">
      <h2>Parts for this step</h2>
      {rows}
    </div>
  </div>
  <div class="shot"><img src="{_src(image, embed)}" alt="Step {index}"></div>
  <div class="mark">{html.escape(TRADEMARK)}</div>
  <div class="folio">page {page} of {pages}</div>
</section>"""


def _cover_page(build: Build, total_steps: int, hero, pages: int, embed: bool) -> str:
    hero_html = (f'<div class="hero"><img src="{_src(hero, embed)}" alt=""></div>'
                 if hero else '<div class="hero"></div>')
    distinct = len(build.counts)
    return f"""
<section class="page cover">
  <p class="kicker">Built from your bricks</p>
  <h1>{html.escape(build.name)}</h1>
  {hero_html}
  <div class="facts">
    <div class="fact"><div class="n">{len(build.parts)}</div><div class="l">pieces</div></div>
    <div class="fact"><div class="n">{distinct}</div><div class="l">elements</div></div>
    <div class="fact"><div class="n">{total_steps}</div><div class="l">steps</div></div>
  </div>
  <div class="mark">{html.escape(TRADEMARK)}</div>
  <div class="folio">page 1 of {pages}</div>
</section>"""


def _parts_page(build: Build, page: int, pages: int, thumbs, embed: bool) -> str:
    cells = "".join(
        f'<div class="cell">{_callout_row(c, thumbs, embed)}</div>'
        for c in sorted(callouts(build.parts), key=lambda c: (c.part, c.color))
    )
    return f"""
<section class="page list">
  <h1>Parts list &mdash; {len(build.parts)} pieces</h1>
  <div>{cells}</div>
  <div class="mark">{html.escape(TRADEMARK)}</div>
  <div class="folio">page {page} of {pages}</div>
</section>"""


# ---------------------------------------------------------------- entry point

def manual_html(build: Build, steps: list[list[Placed]], images,
                hero=None, thumbs: dict[tuple[str, int], object] | None = None,
                embed: bool = True) -> str:
    """Cover + one page per step + a parts list, as one standalone HTML document.

    `images` is one path per step (from render_steps); `thumbs` maps (part, colour) to a
    part thumbnail path and may be empty -- the panel degrades to a colour swatch.
    """
    images = list(images)
    if len(images) != len(steps):
        raise ValueError(f"{len(images)} images for {len(steps)} steps")
    thumbs = thumbs or {}
    pages = len(steps) + 2

    body = [_cover_page(build, len(steps), hero, pages, embed)]
    for i, group in enumerate(steps, 1):
        body.append(_step_page(i, len(steps), i + 1, pages, list(group),
                               images[i - 1], thumbs, embed))
    body.append(_parts_page(build, pages, pages, thumbs, embed))

    return (
        "<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(build.name)} &mdash; building instructions</title>"
        f"<style>{CSS}</style></head><body>"
        + "".join(body)
        + "</body></html>\n"
    )
