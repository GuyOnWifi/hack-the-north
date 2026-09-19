"""Generators emit VALID subassemblies from semantic knobs. Every generator
declares typed + sized sockets. The LLM picks a generator, args, and a socket
NAME — never a coordinate (invariant #4). expand() resolves names to grid
positions deterministically (invariant #9: same seed => identical output).
"""
from __future__ import annotations
from dataclasses import dataclass

from model import Part, SubAssembly, Build


# ------------------------------------------------------------------- sockets
@dataclass(frozen=True)
class Socket:
    name: str
    face: str            # 'stud_up' | 'antistud_down'
    footprint: tuple     # (w, d) in studs
    pos: tuple           # (x, y, z) local, min-corner of the connecting region


COMPLEMENT = {"stud_up": "antistud_down", "antistud_down": "stud_up"}


@dataclass
class SubResult:
    parts: list          # Part in LOCAL coords (sub name filled by expand)
    sockets: dict        # name -> Socket, what this node offers to children
    mount: Socket        # how THIS node plugs into a parent (None for root)


# ---------------------------------------------------------- deterministic tiler
# Only EVEN-length bricks so every tiling is realisable from common parts and
# needs no rotation. Leftover length-1 slices become a pair of 1x1s.
_STRIP2 = {4: "3001", 2: "3003"}          # dx=2 bricks by z-length
_STRIP1 = {6: "3009", 4: "3010", 2: "3004", 1: "3005"}  # dx=1 bricks
_PLATE2 = {4: "3020", 2: "3022"}
_PLATE1 = {2: "3023", 1: "3024"}


def _partition(length, sizes, stagger):
    """Cover [0, length) with the given sizes (desc). `stagger` shifts the
    first cut so adjacent strips don't share a seam (bond). Size 1 is always
    allowed as a fallback."""
    sizes = sorted(sizes, reverse=True)
    out, pos = [], 0
    if stagger and len(sizes) > 1 and length >= sizes[0] + 2:
        out.append((sizes[1], pos)); pos += sizes[1]
    while pos < length:
        for s in sizes:
            if s <= length - pos:
                out.append((s, pos)); pos += s
                break
        else:
            out.append((1, pos)); pos += 1
    return out


def tile_box(w, d, y, color, seed, plates, sub, phase):
    """Fill a w(x) x d(z) footprint at layer y. `phase` shifts the x-seams by
    one stud (a 1-wide column at x=0) so that a course laid at phase p and the
    course above it at phase p+1 straddle each other's seams — real masonry
    bond, which is what actually holds a wide area together."""
    parts, n, x = [], [0], 0
    strip2 = _PLATE2 if plates else _STRIP2
    strip1 = _PLATE1 if plates else _STRIP1
    one = "3024" if plates else "3005"

    def strip(px, sw, sd):
        table = strip2 if sw == 2 else strip1
        for size, oz in _partition(sd, list(table), (px + seed) % 2 == 1):
            if size in table:
                parts.append(Part(f"{sub}.{n[0]}", table[size], color, (px, y, oz), 0, sub)); n[0] += 1
            else:
                for xi in range(sw):
                    parts.append(Part(f"{sub}.{n[0]}", one, color, (px + xi, y, oz), 0, sub)); n[0] += 1

    if phase % 2 == 1 and w >= 3:
        strip(0, 1, d)          # offset column shifts every seam to the right
        x = 1
    while x < w:
        sw = 2 if (w - x) >= 2 else 1
        strip(x, sw, d)
        x += sw
    return parts


def bonded(w, d, y0, color, seed, plates=False, courses=2, sub="root"):
    """Stack `courses` tiled layers with alternating phase. >=2 courses with
    offset seams => every part straddles a seam below it => one connected mass
    (passes the validator's connectivity law). One course is deliberately NOT
    self-connected, because real loose bricks in a single layer aren't."""
    ch = 1 if plates else 3
    parts = []
    for c in range(courses):
        parts += tile_box(w, d, y0 + c * ch, color, seed + c, plates, sub, phase=c)
    return parts


# kept name for sculpt.py: a single course (organic hulls are thin by design)
def tile_rect(w, d, y, color, seed, plates=False, sub="root"):
    return tile_box(w, d, y, color, seed, plates, sub, phase=0)


# ------------------------------------------------------------------ generators
# Convention: x = width, z = length. Each returns a SubResult in local coords.

def chassis(length=8, width=4, color=72, seed=0):
    parts = bonded(width, length, 0, color, seed, courses=2)   # 2 bonded courses
    top = 6
    sock = {
        "deck_front":  Socket("deck_front", "stud_up", (width, 2), (0, top, 0)),
        "deck_rear":   Socket("deck_rear", "stud_up", (width, 2), (0, top, length - 2)),
        "deck_center": Socket("deck_center", "stud_up", (width, 2), (0, top, max(0, length // 2 - 1))),
        "nose":        Socket("nose", "stud_up", (width, 1), (0, top, 0)),
        "tail":        Socket("tail", "stud_up", (width, 1), (0, top, length - 1)),
        "underside_front": Socket("underside_front", "antistud_down", (width, 2), (0, 0, 0)),
        "underside_rear":  Socket("underside_rear", "antistud_down", (width, 2), (0, 0, length - 2)),
    }
    return SubResult(parts, sock, mount=None)


def _seg(length, stagger):
    """1D run of 1x2 bricks (+1x1 filler), seams shifted when `stagger`."""
    out, pos = [], 0
    if stagger and length >= 3:
        out.append((1, 0)); pos = 1              # offset the first seam
    while pos < length:
        if length - pos >= 2:
            out.append((2, pos)); pos += 2
        else:
            out.append((1, pos)); pos += 1
    return out


def cabin(style="closed", width=4, depth=3, height=2, color=15, seed=0):
    """A box that sits on a deck. style: open (walls, no roof) | closed | cab.
    Walls are 1x2 bricks (staggered per course) so they bond and don't burn a
    huge pile of 1x1s."""
    parts, n = [], [0]

    def run_x(z, y, stag):                        # wall along x (1x2 laid flat)
        for size, ox in _seg(width, stag):
            part, rot = ("3004", 90) if size == 2 else ("3005", 0)
            parts.append(Part(f"c.{n[0]}", part, color, (ox, y, z), rot, "root")); n[0] += 1

    def run_z(x, y, stag):                        # wall along z (1x2 upright)
        for size, oz in _seg(depth - 2, stag):
            part = "3004" if size == 2 else "3005"
            parts.append(Part(f"c.{n[0]}", part, color, (x, y, 1 + oz), 0, "root")); n[0] += 1

    for b in range(height):
        y, stag = b * 3, (b + seed) % 2 == 1
        run_x(0, y, stag); run_x(depth - 1, y, stag)
        if depth > 2:
            run_z(0, y, stag); run_z(width - 1, y, stag)
    top = height * 3
    if style in ("closed", "cab"):
        # a spanning plate top bridges the wall columns into one connected mass
        parts += tile_box(width, depth, top, color, seed, True, "root", phase=1)
        top += 1
    mount = Socket("base", "antistud_down", (width, min(2, depth)), (0, 0, 0))
    sock = {"roof": Socket("roof", "stud_up", (width, depth), (0, top, 0))}
    return SubResult(parts, sock, mount)


def axle_pair(width=4, color=72, seed=0):
    """Two wheels at the ends, each plugging its stud UP into the chassis
    underside. No Technic (anti-goal) — round plates, insertion straight down.
    Each wheel connects independently, so there is no orphan bar."""
    parts = [Part("a.0", "4073", color, (0, 0, 0)),
             Part("a.1", "4073", color, (width - 1, 0, 0))]
    mount = Socket("top", "stud_up", (width, 1), (0, 1, 0))
    return SubResult(parts, {}, mount)


def wall(length=8, height=3, width=2, color=70, seed=0):
    parts = bonded(width, length, 0, color, seed, courses=height)
    top = height * 3
    sock = {"top": Socket("top", "stud_up", (width, length), (0, top, 0))}
    mount = Socket("base", "antistud_down", (width, length), (0, 0, 0))
    return SubResult(parts, sock, mount)


def tower(height=4, footprint=2, color=71, seed=0):
    parts = bonded(footprint, footprint, 0, color, seed, courses=height)
    top = height * 3
    sock = {"top": Socket("top", "stud_up", (footprint, footprint), (0, top, 0))}
    mount = Socket("base", "antistud_down", (footprint, footprint), (0, 0, 0))
    return SubResult(parts, sock, mount)


def roof(width=4, depth=4, pitch="flat", color=4, seed=0):
    parts = bonded(width, depth, 0, color, seed, plates=True, courses=2)
    mount = Socket("base", "antistud_down", (width, depth), (0, 0, 0))
    return SubResult(parts, {}, mount)


def slab(width=6, depth=6, color=19, seed=0):
    parts = bonded(width, depth, 0, color, seed, plates=True, courses=2)
    top = 2
    sock = {"top": Socket("top", "stud_up", (width, depth), (0, top, 0))}
    return SubResult(parts, sock, mount=None)


def wing(span=4, sweep="flat", color=71, seed=0):
    # a 2-wide plate fin so it binds to the deck it sits on
    parts = bonded(2, span, 0, color, seed, plates=True, courses=2)
    mount = Socket("base", "antistud_down", (2, min(2, span)), (0, 0, 0))
    return SubResult(parts, {}, mount)


GENERATORS = {
    "chassis": chassis, "cabin": cabin, "axle_pair": axle_pair, "wall": wall,
    "tower": tower, "roof": roof, "slab": slab, "wing": wing,
}


# ------------------------------------------------------------------- expansion
class AttachError(Exception):
    pass


def _run_gen(node, seed):
    name = node["gen"]
    if name not in GENERATORS:
        raise AttachError(f"unknown generator {name!r}")
    args = dict(node.get("args", {}))
    args["seed"] = args.get("seed", seed)
    return GENERATORS[name](**args)


def expand(composition, build_id="bld_demo", name="model", seed=0):
    """Composition tree -> validated-shape Build. Resolves socket NAMES to grid
    positions. Raises AttachError on socket type/size mismatch BEFORE geometry —
    bad compositions die cheap (no bricks placed)."""
    parts, subs = [], []
    counter = [0]

    def uid(prefix):
        counter[0] += 1
        return f"{prefix}{counter[0]}"

    def place(node, parent_res, parent_sub, attach_name):
        gen_name = node["gen"]
        sub_name = node.get("as", gen_name if parent_sub is None else uid(gen_name + "_"))
        res = _run_gen(node, seed)

        if parent_res is None:                       # root
            tx = ty = tz = 0
        else:
            if attach_name not in parent_res.sockets:
                raise AttachError(
                    f"{sub_name} wants socket {attach_name!r}; "
                    f"{parent_sub} offers {list(parent_res.sockets)}")
            sock = parent_res.sockets[attach_name]
            if res.mount is None:
                raise AttachError(f"{sub_name} ({gen_name}) has no mount to attach")
            if res.mount.face != COMPLEMENT[sock.face]:
                raise AttachError(
                    f"{sub_name}.{res.mount.face} incompatible with "
                    f"{parent_sub}.{attach_name} ({sock.face})")
            mw, md = res.mount.footprint
            sw, sd = sock.footprint
            if mw > sw or md > sd:
                raise AttachError(
                    f"{sub_name} mount {res.mount.footprint} too big for "
                    f"socket {sock.footprint} on {parent_sub}.{attach_name}")
            tx = sock.pos[0] - res.mount.pos[0]
            ty = sock.pos[1] - res.mount.pos[1]
            tz = sock.pos[2] - res.mount.pos[2]

        for p in res.parts:
            parts.append(Part(uid("p"), p.part, p.color,
                              (p.pos[0] + tx, p.pos[1] + ty, p.pos[2] + tz),
                              p.rot, sub_name))

        subs.append(SubAssembly(sub_name,
                                None if parent_sub is None else parent_sub,
                                gen_name, tuple(sorted(node.get("args", {}).items())),
                                attach_name, tuple(res.sockets)))

        for child in node.get("children", []):
            place(child, res, sub_name, child["attach"])

    place(composition["root"] if "root" in composition else composition,
          None, None, None)
    return Build(id=build_id, version=0, name=name, parts=tuple(parts),
                 subs=tuple(subs),
                 provenance={"backend": "compose", "seed": seed,
                             "composition": composition})
