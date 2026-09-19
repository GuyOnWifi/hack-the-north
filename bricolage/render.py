"""Server-side isometric render of a Build to a PNG. Used by the vision loop:
the agent renders what it imagined, LOOKS at it, and corrects it. Pure Pillow.

Grid: x,z in studs, y in plates (+y up). Isometric painter's projection.
"""
from __future__ import annotations
from PIL import Image, ImageDraw

from meta import COLOR_RGB

A, B, C = 16, 8, 7          # iso: stud half-width, stud quarter-depth, plate height


def _shade(rgb, f):
    return tuple(max(0, min(255, int(c * f))) for c in rgb)


def _render_top(build, d, img, path, w, h):
    """Straight-down plan view — reads a flat silhouette (a heart, a letter)
    clearly, which the skewed isometric view can't. Ignores the baseplate so the
    shape itself is what's judged."""
    parts = [p for p in build.parts if p.sub != "base"]
    if not parts:
        parts = list(build.parts)
    xs = [p.pos[0] for p in parts] + [p.pos[0] + p.footprint()[0] for p in parts]
    zs = [p.pos[2] for p in parts] + [p.pos[2] + p.footprint()[1] for p in parts]
    ext = max(max(xs) - min(xs), max(zs) - min(zs), 1)
    s = (min(w, h) * 0.7) / ext
    ox = w / 2 - (min(xs) + max(xs)) / 2 * s
    oy = h / 2 - (min(zs) + max(zs)) / 2 * s
    for p in sorted(parts, key=lambda p: p.pos[1]):    # bottom first
        x, _, z = p.pos
        dx, dz = p.footprint()
        base = COLOR_RGB.get(p.color, (150, 150, 150))
        d.rectangle([x * s + ox, z * s + oy, (x + dx) * s + ox, (z + dz) * s + oy],
                    fill=base, outline=_shade(base, 0.4))
        if p.has_studs():
            for i in range(dx):
                for j in range(dz):
                    cx, cy = (x + i + 0.5) * s + ox, (z + j + 0.5) * s + oy
                    r = s * 0.22
                    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=_shade(base, 0.55))
    img.save(path)
    return path


def render_build(build, path, w=720, h=720, bg=(180, 184, 188), view="iso"):
    parts = list(build.parts)
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img, "RGBA")
    if not parts:
        img.save(path)
        return path
    if view == "top":
        return _render_top(build, d, img, path, w, h)

    # auto-fit: project at unit scale, then scale to fill ~62% of the frame
    def proj0(px, py, pz):
        return ((px - pz) * A, (px + pz) * B - py * C)
    corners = []
    for p in parts:
        dx, dz = p.footprint()
        corners.append(proj0(p.pos[0], p.pos[1], p.pos[2]))
        corners.append(proj0(p.pos[0] + dx, p.pos[1] + p.height(), p.pos[2] + dz))
        corners.append(proj0(p.pos[0] + dx, p.pos[1], p.pos[2]))
        corners.append(proj0(p.pos[0], p.pos[1] + p.height(), p.pos[2] + dz))
    xs = [c[0] for c in corners]; ys = [c[1] for c in corners]
    ext = max(max(xs) - min(xs), max(ys) - min(ys), 1)
    s = (min(w, h) * 0.62) / ext
    ox = w / 2 - (min(xs) + max(xs)) / 2 * s
    oy = h / 2 - (min(ys) + max(ys)) / 2 * s

    def sp(px, py, pz):
        x, y = proj0(px, py, pz)
        return (x * s + ox, y * s + oy)

    # painter's order: back-bottom-left first, front-top-right last
    parts.sort(key=lambda p: (p.pos[0] + p.pos[2] + p.pos[1] * 0.34))

    for p in parts:
        x, y, z = p.pos
        dx, dz = p.footprint()
        ht = p.height()
        x2, y2, z2 = x + dx, y + ht, z + dz
        base = COLOR_RGB.get(p.color, (150, 150, 150))
        top = [sp(x, y2, z), sp(x2, y2, z), sp(x2, y2, z2), sp(x, y2, z2)]
        right = [sp(x2, y, z), sp(x2, y, z2), sp(x2, y2, z2), sp(x2, y2, z)]
        front = [sp(x, y, z2), sp(x2, y, z2), sp(x2, y2, z2), sp(x, y2, z2)]
        edge = _shade(base, 0.35)
        d.polygon(right, fill=_shade(base, 0.72), outline=edge)
        d.polygon(front, fill=_shade(base, 0.58), outline=edge)
        d.polygon(top, fill=_shade(base, 1.0), outline=edge)
        # studs on the top face
        if p.has_studs():
            for i in range(dx):
                for j in range(dz):
                    cx, cy = sp(x + i + 0.5, y2, z + j + 0.5)
                    r = A * 0.26 * s
                    d.ellipse([cx - r, cy - r * 0.6, cx + r, cy + r * 0.6],
                              fill=_shade(base, 0.9), outline=edge)
    img.save(path)
    return path
