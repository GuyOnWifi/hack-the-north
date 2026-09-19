"""One PNG per build step, in the flat-colour / black-outline look of a printed manual.

WHY a hand-written renderer when LeoCAD exists
----------------------------------------------
LeoCAD is the better tool and we shell out to it when it is on PATH. But it is a desktop GUI
app that is not installed on a borrowed conference laptop and cannot be installed over dead
conference wifi, so it can never be the thing the demo depends on. The manual look is not
photorealism -- it is flat colour, black outlines, an orthographic three-quarter camera. That
is reachable from the integer grid with Pillow and school trigonometry. So the "fallback" is
the default path, and LeoCAD is the upgrade.

WHY the camera is fitted to the whole build, not to each step
-------------------------------------------------------------
A manual whose model jumps around between pages is unreadable. One camera, fitted once to the
finished model, means the model grows in place across the pages, which is what real manuals do
and what makes the page flip legible.

Projection: true isometric. x/z are studs, y is plates (0.4 stud each), +y is up.
    sx = (x - z) * cos30
    sy = (x + z) * sin30 - y * 0.4
The view direction is (1,1,1) in (x, y_in_studs, z), which is what makes the painter sort
below a simple sum of the box's near-corner coordinates.
"""

from __future__ import annotations

import functools
import math
import pathlib
import shutil
import subprocess
from dataclasses import dataclass

from PIL import Image, ImageDraw

from core import meta as meta_mod
from core.geom import rotated_footprint
from core.model import Build, Placed

# ---------------------------------------------------------------- constants

COS30 = math.cos(math.radians(30))
SIN30 = 0.5
PLATE_IN_STUDS = 0.4          # 8 LDU / 20 LDU
STUD_RADIUS = 0.305           # studs; real is 6/20 = 0.3
STUD_HEIGHT = 0.5             # plates; real is 4/8 = 0.5

MANUAL_BLUE = (0xCF, 0xE3, 0xF4)   # #CFE3F4 -- the pale blue of a modern manual page
OUTLINE = (17, 17, 17)

# Face shading. Flat, not lit: three constants is the entire material model.
F_TOP, F_RIGHT, F_LEFT = 1.0, 0.80, 0.62

# Enough colours to keep working if data/LDConfig.ldr is missing. Not a substitute for it.
_FALLBACK_RGB: dict[int, tuple[int, int, int]] = {
    0: (27, 42, 52), 1: (0, 85, 191), 2: (37, 122, 54), 4: (201, 26, 9),
    6: (88, 57, 39), 14: (245, 205, 47), 15: (255, 255, 255), 19: (228, 205, 158),
    25: (254, 138, 24), 70: (88, 57, 39), 71: (163, 162, 164), 72: (99, 95, 97),
}


@functools.cache
def _ldraw_table() -> dict[int, tuple[str, tuple[int, int, int]]]:
    """code -> (name, rgb), from the real LDraw palette when we have it."""
    try:
        from vision.color import palette
        return {code: (name, rgb) for code, name, rgb, _lab in palette(common_only=False)}
    except Exception:  # missing LDConfig.ldr, missing numpy -- render anyway, in fallback colours
        return {c: (f"Colour {c}", rgb) for c, rgb in _FALLBACK_RGB.items()}


def ldraw_rgb(code: int) -> tuple[int, int, int]:
    entry = _ldraw_table().get(code)
    if entry is not None:
        return entry[1]
    return _FALLBACK_RGB.get(code, (150, 150, 150))


def ldraw_color_name(code: int) -> str:
    entry = _ldraw_table().get(code)
    return entry[0] if entry else f"Colour {code}"


def part_name(part: str) -> str:
    try:
        return meta_mod.get(part).name
    except KeyError:
        return part


# ---------------------------------------------------------------- options

@dataclass(frozen=True, slots=True)
class RenderOpts:
    width: int = 1200
    height: int = 900
    margin: int = 48
    background: tuple[int, int, int] | None = MANUAL_BLUE   # None = transparent
    fade: float = 0.42        # how far already-built parts wash out toward the background
    supersample: int = 2      # render big, downsample -- our only antialiasing
    draw_studs: bool = True
    highlight: bool = True    # heavier outline on the parts added this step


@dataclass(frozen=True, slots=True)
class Camera:
    """Isometric projection with a fitted scale (pixels per stud) and origin."""

    scale: float
    ox: float
    oy: float

    def project(self, x: float, y: float, z: float) -> tuple[float, float]:
        sx = (x - z) * COS30
        sy = (x + z) * SIN30 - y * PLATE_IN_STUDS
        return (self.ox + sx * self.scale, self.oy + sy * self.scale)

    def scaled(self, k: float) -> "Camera":
        return Camera(self.scale * k, self.ox * k, self.oy * k)


@dataclass(frozen=True, slots=True)
class _Box:
    """A placed part reduced to the axis-aligned grid box we actually draw."""

    x0: int; x1: int
    y0: int; y1: int
    z0: int; z1: int
    color: int
    studs: tuple[tuple[int, int], ...]      # world (x, z) cells carrying an upward stud

    @property
    def depth(self) -> float:
        """Distance of the far corner along the view direction. Ascending = back to front."""
        return self.x0 + self.z0 + self.y0 * PLATE_IN_STUDS


def _box_of(p: Placed) -> _Box:
    try:
        m = meta_mod.get(p.part)
    except KeyError:
        # An off-whitelist part should still draw as *something*; a 1x1 brick-shaped
        # placeholder is honest about "we don't know this mould" without a blank page.
        return _Box(p.x, p.x + 1, p.y, p.y + 3, p.z, p.z + 1, p.color, ((p.x, p.z),))
    w, d = rotated_footprint(m.w, m.d, p.rot)
    studs = tuple((p.x + cx, p.z + cz) for cx, cz in m.stud_cells(p.rot))
    return _Box(p.x, p.x + w, p.y, p.y + m.h, p.z, p.z + d, p.color, studs)


# ---------------------------------------------------------------- camera fitting

def fit_camera(boxes: list[_Box], opts: RenderOpts) -> Camera:
    """One camera for the whole model, so the page flip doesn't move the subject."""
    if not boxes:
        return Camera(20.0, opts.width / 2, opts.height / 2)
    unit = Camera(1.0, 0.0, 0.0)
    xs: list[float] = []
    ys: list[float] = []
    for b in boxes:
        for x in (b.x0, b.x1):
            for z in (b.z0, b.z1):
                for y in (b.y0, b.y1 + STUD_HEIGHT):   # stud tops count toward the frame
                    px, py = unit.project(x, y, z)
                    xs.append(px); ys.append(py)
    w = max(max(xs) - min(xs), 1e-6)
    h = max(max(ys) - min(ys), 1e-6)
    scale = min((opts.width - 2 * opts.margin) / w, (opts.height - 2 * opts.margin) / h)
    ox = (opts.width - w * scale) / 2 - min(xs) * scale
    oy = (opts.height - h * scale) / 2 - min(ys) * scale
    return Camera(scale, ox, oy)


# ---------------------------------------------------------------- drawing

def _shade(rgb: tuple[int, int, int], f: float) -> tuple[int, int, int]:
    # Very dark colours go to mush against black outlines, so lift them before shading.
    lift = 40 if sum(rgb) < 170 else 0
    return tuple(max(0, min(255, int(c * f + lift * f))) for c in rgb)  # type: ignore[return-value]


def _fade(rgb: tuple[int, int, int], bg: tuple[int, int, int], a: float) -> tuple[int, int, int]:
    return tuple(int(c * (1 - a) + b * a) for c, b in zip(rgb, bg))  # type: ignore[return-value]


def _poly(draw: ImageDraw.ImageDraw, pts, fill, lw: int) -> None:
    draw.polygon(pts, fill=fill)
    draw.line(list(pts) + [pts[0]], fill=OUTLINE, width=lw, joint="curve")


def _draw_box(draw: ImageDraw.ImageDraw, cam: Camera, b: _Box,
              rgb: tuple[int, int, int], lw: int, occupied: set[tuple[int, int, int]],
              draw_studs: bool) -> None:
    P = cam.project
    x0, x1, y0, y1, z0, z1 = b.x0, b.x1, b.y0, b.y1, b.z0, b.z1

    # Only three faces can face this camera: the top, the +x face and the +z face.
    top = (P(x0, y1, z0), P(x1, y1, z0), P(x1, y1, z1), P(x0, y1, z1))
    right = (P(x1, y1, z0), P(x1, y1, z1), P(x1, y0, z1), P(x1, y0, z0))
    left = (P(x0, y1, z1), P(x1, y1, z1), P(x1, y0, z1), P(x0, y0, z1))

    _poly(draw, left, _shade(rgb, F_LEFT), lw)
    _poly(draw, right, _shade(rgb, F_RIGHT), lw)
    _poly(draw, top, _shade(rgb, F_TOP), lw)

    if draw_studs and cam.scale >= 11:
        for sx, sz in b.studs:
            if (sx, sz, y1) in occupied:      # something is plugged into it; don't draw it
                continue
            _draw_stud(draw, cam, sx + 0.5, y1, sz + 0.5, rgb, lw)


def _draw_stud(draw: ImageDraw.ImageDraw, cam: Camera, cx: float, y: float, cz: float,
               rgb: tuple[int, int, int], lw: int, n: int = 18) -> None:
    ring = [(cx + STUD_RADIUS * math.cos(t), cz + STUD_RADIUS * math.sin(t))
            for t in (2 * math.pi * i / n for i in range(n))]
    bottom = [cam.project(px, y, pz) for px, pz in ring]
    top = [cam.project(px, y + STUD_HEIGHT, pz) for px, pz in ring]
    # The bottom disc peeks out below the top one; that sliver is the stud's side wall.
    draw.polygon(bottom, fill=_shade(rgb, F_RIGHT), outline=OUTLINE)
    _poly(draw, top, _shade(rgb, F_TOP), max(1, lw - 1))


def render_scene(new: list[Placed], old: list[Placed], cam: Camera,
                 opts: RenderOpts = RenderOpts()) -> Image.Image:
    """Draw `old` washed out and `new` at full strength, painter-sorted together.

    They must sort together, not in two passes: a part added this step can sit *behind*
    one built earlier, and drawing all the new parts last would put it in front of its
    own occluder.
    """
    ss = max(1, opts.supersample)
    size = (opts.width * ss, opts.height * ss)
    bg = opts.background
    img = Image.new("RGBA", size, (*bg, 255) if bg else (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cam = cam.scaled(ss)

    items = [(_box_of(p), True) for p in new] + [(_box_of(p), False) for p in old]
    occupied = {
        (x, z, y)
        for b, _ in items
        for x in range(b.x0, b.x1) for z in range(b.z0, b.z1) for y in range(b.y0, b.y1)
    }
    items.sort(key=lambda it: (it[0].depth, it[0].y0, it[0].x0, it[0].z0))

    base_lw = max(1, round(cam.scale * 0.055))
    wash = bg or MANUAL_BLUE
    for box, is_new in items:
        rgb = ldraw_rgb(box.color)
        if not is_new:
            rgb = _fade(rgb, wash, opts.fade)
        lw = base_lw + 1 if (is_new and opts.highlight) else base_lw
        _draw_box(draw, cam, box, rgb, lw, occupied, opts.draw_studs)

    if ss > 1:
        img = img.resize((opts.width, opts.height), Image.LANCZOS)
    return img


def render_part(part: str, color: int, size: int = 128) -> Image.Image:
    """A transparent thumbnail of one part, for the parts-callout panel."""
    opts = RenderOpts(width=size, height=size, margin=max(4, size // 12),
                      background=None, supersample=3, highlight=False)
    p = Placed(id="thumb", part=part, color=color, pos=(0, 0, 0), rot=0)
    cam = fit_camera([_box_of(p)], opts)
    return render_scene([p], [], cam, opts)


# ---------------------------------------------------------------- LeoCAD

def leocad_path() -> str | None:
    """Path to a LeoCAD binary, or None. Checked once per call -- it is cheap."""
    found = shutil.which("leocad")
    if found:
        return found
    for candidate in ("/Applications/LeoCAD.app/Contents/MacOS/LeoCAD",
                      "/usr/local/bin/leocad", "/opt/homebrew/bin/leocad"):
        if pathlib.Path(candidate).is_file():
            return candidate
    return None


def _leocad_step(exe: str, ldr: pathlib.Path, out: pathlib.Path, step: int,
                 opts: RenderOpts, timeout: float = 30.0) -> bool:
    """Render one step with LeoCAD. Returns False on any failure -- the caller falls back.

    UNVERIFIED: no LeoCAD on the dev machine, so this path has never actually run. It is
    written to the documented CLI and it fails closed.
    """
    cmd = [exe, "-i", str(out), "-f", str(step), "-t", str(step),
           "--highlight", "--orthographic", "--camera-angles", "30", "45",
           "-w", str(opts.width), "-h", str(opts.height), str(ldr)]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and out.exists() and out.stat().st_size > 0


# ---------------------------------------------------------------- the entry point

@dataclass(frozen=True, slots=True)
class StepRender:
    images: tuple[pathlib.Path, ...]
    backend: str                       # "leocad" | "iso"
    camera: Camera
    notes: tuple[str, ...] = ()


def render_steps(build: Build, steps: list[list[Placed]], out_dir,
                 opts: RenderOpts = RenderOpts(), backend: str = "auto") -> StepRender:
    """PNG per step, cumulative: everything built so far, with this step's parts highlighted.

    `backend`: "auto" (LeoCAD if present, else iso), "leocad", or "iso".
    """
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    paths: list[pathlib.Path] = []

    exe = leocad_path() if backend in ("auto", "leocad") else None
    if backend == "leocad" and exe is None:
        raise RuntimeError("backend='leocad' but no leocad binary found")
    if backend == "auto" and exe is None:
        notes.append("LeoCAD not installed; rendered with the built-in isometric renderer.")

    cam = fit_camera([_box_of(p) for p in build.parts], opts)

    if exe is not None:
        from core.ldraw import to_ldraw
        ldr = out / "model.ldr"
        ldr.write_text(to_ldraw(build, steps))
        ok = True
        for i in range(1, len(steps) + 1):
            png = out / f"step_{i:03d}.png"
            if not _leocad_step(exe, ldr, png, i, opts):
                ok = False
                notes.append(f"LeoCAD failed on step {i}; falling back to the isometric renderer.")
                break
            paths.append(png)
        if ok:
            return StepRender(tuple(paths), "leocad", cam, tuple(notes))
        paths.clear()

    done: list[Placed] = []
    for i, group in enumerate(steps, 1):
        img = render_scene(list(group), list(done), cam, opts)
        png = out / f"step_{i:03d}.png"
        (img.convert("RGB") if opts.background else img).save(png)
        paths.append(png)
        done.extend(group)
    return StepRender(tuple(paths), "iso", cam, tuple(notes))


def render_hero(build: Build, path, opts: RenderOpts = RenderOpts()) -> pathlib.Path:
    """The finished model, for the cover page."""
    cam = fit_camera([_box_of(p) for p in build.parts], opts)
    img = render_scene(list(build.parts), [], cam, opts)
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    (img.convert("RGB") if opts.background else img).save(p)
    return p
