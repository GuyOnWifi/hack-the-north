"""Geometry, studs, a name and a kind for *any* LDraw part — never a KeyError.

`kit.G` knows 50 parts. Real models (the bundled `.mpd`s, anything a user
loads) reference hundreds more, and they embed their own part files. This
module resolves a part four ways, first hit wins:

    kit        -> the hand-verified Geom in kit.py
    derived    -> real geometry walked out of an embedded/packed part file
    described  -> no geometry, but the header says "Brick 2 x 4"
    fallback   -> treat it as a 1x1 brick and say so on the tape

Everything here is pure: no network, no model calls, numpy only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import kit

STUD = kit.STUD
PLATE = kit.PLATE

_STUD_FILES = {"stud.dat", "stud2.dat", "stud2a.dat", "studp01.dat", "studel.dat",
               "stud3.dat", "stud4.dat", "stud4a.dat", "stud10.dat", "stud6.dat"}
# the studs we count as "a stud on top" when deriving; anything under a ref whose
# basename starts with "stud" is excluded from the body box either way.


@dataclass(frozen=True)
class PartInfo:
    pid: str
    name: str
    kind: str
    size: tuple           # studs X, plates Y, studs Z (ceil of the body box)
    source: str           # "kit" | "derived" | "described" | "fallback"
    box: tuple            # x0, x1, y0, y1, z0, z1  (LDU, part-local, studs excluded)
    studs: tuple = ()     # ((x,y,z),(ax,ay,az)) stud base + outward axis
    antistuds: tuple = () # ((x,y,z),(ax,ay,az)) receptor point + required stud axis


# ---------------------------------------------------------------- libraries
def norm_ref(ref: str) -> str:
    return ref.strip().replace("\\", "/").lower()


def pid_of(ref: str) -> str:
    """'parts/3024.DAT' -> '3024'."""
    r = norm_ref(ref)
    r = r.rsplit("/", 1)[-1]
    return r[:-4] if r.endswith(".dat") else r


def load_library(*texts: str) -> dict:
    """'0 FILE name' blocks -> {normalised name: [lines]}."""
    lib: dict[str, list[str]] = {}
    for text in texts:
        if not text:
            continue
        name = None
        buf: list[str] = []
        for line in text.splitlines():
            if line.startswith("0 FILE "):
                if name is not None:
                    lib.setdefault(name, buf)
                name = norm_ref(line[7:])
                buf = []
            elif name is not None:
                buf.append(line)
        if name is not None:
            lib.setdefault(name, buf)
    return lib


_PACK: dict | None = None
PACK_PATH = Path(__file__).resolve().parents[2] / "web" / "public" / "ldraw" / "parts.pack.ldr"


def pack() -> dict:
    """The app's packed LDraw library, cached. {} when it isn't there."""
    global _PACK
    if _PACK is None:
        try:
            _PACK = load_library(PACK_PATH.read_text())
        except OSError:
            _PACK = {}
    return _PACK


def pack_text() -> str:
    try:
        return PACK_PATH.read_text()
    except OSError:
        return ""


_COLOURS: dict | None = None


def colours() -> dict:
    """{code: {"code","name","hex","trans"}} from the pack's 0 !COLOUR lines."""
    global _COLOURS
    if _COLOURS is None:
        out: dict[int, dict] = {}
        for line in pack_text().splitlines():
            if not line.startswith("0 !COLOUR"):
                continue
            tok = line.split()
            try:
                code = int(tok[tok.index("CODE") + 1])
                val = tok[tok.index("VALUE") + 1]
            except (ValueError, IndexError):
                continue
            out.setdefault(code, {"code": code, "name": tok[2].replace("_", " "),
                                  "hex": val, "trans": "ALPHA" in tok})
        _COLOURS = out
    return _COLOURS


def colour_name(code: int) -> str:
    c = colours().get(int(code))
    return c["name"] if c else f"Colour {code}"


def is_trans(code: int) -> bool:
    c = colours().get(int(code))
    return bool(c and c["trans"])


# ------------------------------------------------------------------- lookup
_CACHE: dict = {}


def _lookup(pid: str, lib: dict | None):
    """The part file's lines, from the model's own library first, then the pack."""
    for src in (lib, pack()):
        if not src:
            continue
        for key in (f"{pid}.dat", f"parts/{pid}.dat", f"p/{pid}.dat"):
            if key in src:
                return src[key]
    return None


def _find(ref: str, lib: dict | None):
    r = norm_ref(ref)
    for src in (lib, pack()):
        if not src:
            continue
        if r in src:
            return src[r]
        tail = r.rsplit("/", 1)[-1]
        for key in (tail, f"parts/{tail}", f"p/{tail}", f"p/48/{tail}", f"s/{tail}"):
            if key in src:
                return src[key]
    return None


def info(pid: str, lib: dict | None = None) -> PartInfo:
    pid = str(pid)
    key = (pid, id(lib) if lib else 0)
    hit = _CACHE.get(key)
    if hit is None:
        hit = _CACHE[key] = _resolve(pid, lib)
    return hit


def _resolve(pid: str, lib: dict | None) -> PartInfo:
    if pid in kit.G:
        return _from_kit(pid)
    lines = _lookup(pid, lib)
    if lines is not None:
        moved = _moved_to(lines)
        seen = {pid}
        while moved and moved not in seen:
            seen.add(moved)
            nxt = _lookup(moved, lib)
            if nxt is None:
                break
            if moved in kit.G:
                k = _from_kit(moved)
                return PartInfo(pid, k.name, k.kind, k.size, k.source, k.box, k.studs, k.antistuds)
            lines, moved = nxt, _moved_to(nxt)
        got = _derive(pid, lines, lib)
        if got is not None:
            return got
        described = _describe(pid, _first_text(lines))
        if described is not None:
            return described
    return _fallback(pid, _first_text(lines) if lines else "")


def _moved_to(lines) -> str | None:
    for line in lines[:6]:
        m = re.match(r"\s*0\s+~Moved to\s+(\S+)", line)
        if m:
            return pid_of(m.group(1))
    return None


def _first_text(lines) -> str:
    for line in lines[:4]:
        s = line.strip()
        if s.startswith("0 ") and not s.startswith("0 !") and not s.startswith("0 //"):
            body = s[2:].strip()
            if body and not body.lower().startswith(("name:", "author:", "bfc")):
                return re.sub(r"\s+", " ", body).lstrip("~=_").strip()
    return ""


def _lattice(a: float, b: float) -> list[float]:
    """Stud centres on [a, b]: a+10, a+30, ..."""
    n = int(round((b - a) / STUD))
    if n < 1:
        return [(a + b) / 2]
    return [a + 10.0 + 20.0 * i for i in range(n)]


def _from_kit(pid: str) -> PartInfo:
    g = kit.G[pid]
    h = max(g.plates, 1) * PLATE
    y0, y1 = (-h, 0.0) if g.origin == "bottom" else (0.0, h)
    if pid == "30374":
        y0, y1 = 0.0, 80.0
    box = (g.x0, g.x1, y0, y1, g.z0, g.z1)
    up = (0.0, -1.0, 0.0)
    studs: list = []
    if g.studs_on_top:
        studs += [((x, y0, z), up) for x in _lattice(g.x0, g.x1) for z in _lattice(g.z0, g.z1)]
    for s in kit.SIDE_STUDS.get(pid, ()):
        studs.append((tuple(float(v) for v in s), (0.0, 0.0, -1.0)))
    anti: list = []
    if pid not in ("3938", "30374"):
        anti = [((x, y1, z), up) for x in _lattice(g.x0, g.x1) for z in _lattice(g.z0, g.z1)]
    return PartInfo(pid, g.name or f"Part {pid}", _kind(g.name or ""), _size(box), "kit",
                    box, tuple(studs), tuple(anti))


MAX_VERTS = 20000


def _derive(pid: str, lines, lib) -> PartInfo | None:
    verts: list[tuple[float, float, float]] = []
    studs: list = []
    budget = [MAX_VERTS]

    def walk(ls, M, depth, in_stud):
        for line in ls:
            if budget[0] <= 0:
                return
            t = line.split(None, 14)
            if not t:
                continue
            if t[0] == "1" and len(t) >= 15:
                try:
                    nums = [float(v) for v in t[2:14]]
                except ValueError:
                    continue
                ref = norm_ref(t[14].strip())
                base = ref.rsplit("/", 1)[-1]
                S = np.eye(4)
                S[:3, 3] = nums[0:3]
                S[:3, :3] = np.array(nums[3:12], float).reshape(3, 3)
                W = M @ S
                stud_here = in_stud or base.startswith("stud")
                if base in _STUD_FILES and not in_stud:
                    ax = W[:3, :3] @ np.array([0.0, -1.0, 0.0])
                    n = float(np.linalg.norm(ax))
                    if n > 1e-9:
                        studs.append((tuple(float(v) for v in W[:3, 3]), tuple(float(v) for v in ax / n)))
                if depth < 8:
                    sub = _find(ref, lib)
                    if sub is not None:
                        walk(sub, W, depth + 1, stud_here)
            elif t[0] in ("3", "4") and not in_stud:
                k = 3 if t[0] == "3" else 4
                try:
                    nums = [float(v) for v in t[2:2 + 3 * k]]
                except ValueError:
                    continue
                for i in range(k):
                    p = M @ np.array([nums[3 * i], nums[3 * i + 1], nums[3 * i + 2], 1.0])
                    verts.append((float(p[0]), float(p[1]), float(p[2])))
                budget[0] -= k

    walk(lines, np.eye(4), 0, False)
    if len(verts) < 4:
        return None
    a = np.array(verts, float)
    lo, hi = a.min(axis=0), a.max(axis=0)
    box = (float(lo[0]), float(hi[0]), float(lo[1]), float(hi[1]), float(lo[2]), float(hi[2]))
    if hi[0] - lo[0] < 1e-6 or hi[2] - lo[2] < 1e-6:
        return None
    anti: list = []
    if _whole_studs(box[0], box[1]) and _whole_studs(box[4], box[5]):
        up = (0.0, -1.0, 0.0)
        anti = [((x, box[3], z), up) for x in _lattice(box[0], box[1]) for z in _lattice(box[4], box[5])]
    name = _first_text(lines) or f"Part {pid}"
    return PartInfo(pid, name, _kind(name), _size(box), "derived", box, tuple(studs), tuple(anti))


def _whole_studs(a: float, b: float) -> bool:
    w = b - a
    return w >= STUD - 2 and abs(w - round(w / STUD) * STUD) <= 2.0


_DESC = re.compile(r"(\d+)\s*x\s*(\d+)", re.I)


def _describe(pid: str, name: str) -> PartInfo | None:
    m = _DESC.search(name)
    if not m:
        return None
    nz, nx = int(m.group(1)), int(m.group(2))
    if not (1 <= nz <= 32 and 1 <= nx <= 32):
        return None
    plates = 3 if name.lower().startswith("brick") else 1
    box = (-nx * 10.0, nx * 10.0, 0.0, plates * PLATE, -nz * 10.0, nz * 10.0)
    up = (0.0, -1.0, 0.0)
    studs = [((x, box[2], z), up) for x in _lattice(box[0], box[1]) for z in _lattice(box[4], box[5])]
    anti = [((x, box[3], z), up) for x in _lattice(box[0], box[1]) for z in _lattice(box[4], box[5])]
    return PartInfo(pid, name, _kind(name), _size(box), "described", box, tuple(studs), tuple(anti))


def _fallback(pid: str, name: str) -> PartInfo:
    box = (-10.0, 10.0, 0.0, 24.0, -10.0, 10.0)
    return PartInfo(pid, name or f"Part {pid}", _kind(name), (1, 3, 1), "fallback", box, (), ())


_KINDS = [("tyre", "tyre"), ("tire", "tyre"), ("wheel", "wheel"), ("windscreen", "window"),
          ("window", "window"), ("glass", "window"), ("minifig", "minifig"), ("hinge", "hinge"),
          ("bar ", "bar"), ("wedge", "wedge"), ("wing", "wedge"), ("slope", "slope"),
          ("round", "round"), ("tile", "tile"), ("plate", "plate"), ("brick", "brick")]


def _kind(name: str) -> str:
    low = " " + name.lower() + " "
    for needle, k in _KINDS:
        if needle in low:
            return k
    return "other"


def _size(box) -> tuple:
    x0, x1, y0, y1, z0, z1 = box
    import math
    return (max(1, math.ceil((x1 - x0) / STUD - 1e-6)),
            max(1, math.ceil((y1 - y0) / PLATE - 1e-6)),
            max(1, math.ceil((z1 - z0) / STUD - 1e-6)))


# ------------------------------------------------------------------ samples
_SAMPLES: dict = {}
STEP = 4.0
SHRINK = 1.5


def samples(pid: str, lib: dict | None = None) -> np.ndarray:
    """The part's body box on a 4-LDU lattice, homogeneous (N, 4)."""
    key = (pid, id(lib) if lib else 0)
    hit = _SAMPLES.get(key)
    if hit is None:
        g = info(pid, lib)
        x0, x1, y0, y1, z0, z1 = g.box
        spans = ((x0, x1), (y0, y1), (z0, z1))
        axes = [np.arange(a + SHRINK, b - SHRINK + 1e-6, STEP) for a, b in spans]
        axes = [a if len(a) else np.array([(lo + hi) / 2]) for a, (lo, hi) in zip(axes, spans)]
        X, Y, Z = np.meshgrid(*axes, indexing="ij")
        hit = _SAMPLES[key] = np.stack([X.ravel(), Y.ravel(), Z.ravel(), np.ones(X.size)], axis=1)
    return hit
