"""Connectivity-first layout by merging (after Testuz, Schwartzburg & Pauly,
"Automatic generation of constructable brick sculptures", Eurographics 2013).

Start with every cell as a 1x1 (a 1x1 brick where a column fills a whole
3-plate band, else a 1x1 plate). Then repeatedly merge two side-by-side parts
of the same height and colour into one bigger real part. A merged part keeps
every connection both halves had, so merging can only join groups, never split
them. Phase 1 only takes merges that join two separate groups (that's what
fixes loose pieces); phase 2 then merges for size, alternating the preferred
direction per layer so seams cross and the model is strong.
"""
from __future__ import annotations

import random

import numpy as np

from .layout import Layout, Placed
from .parts import BRICKS, PLATES

SIZES = {1: {(p.length, p.width): p for p in PLATES}, 3: {(p.length, p.width): p for p in BRICKS}}


def _part_for(h, sx, sz):
    table = SIZES[h]
    if (sx, sz) in table:
        return table[(sx, sz)], True
    if (sz, sx) in table:
        return table[(sz, sx)], False
    return None, None


class _State:
    def __init__(self, grid, colours):
        self.grid = grid
        X, Y, Z = grid.shape
        self.owner = np.full(grid.shape, -1, dtype=np.int64)
        self.parts: dict[int, list] = {}  # id -> [x, y, z, sx, sz, h, colour]
        self.uf: dict[int, int] = {}
        nid = 0
        claimed = np.zeros_like(grid)
        for band in range(0, Y - 2, 3):
            full = grid[:, band : band + 3, :].all(axis=1)
            same = (colours[:, band, :] == colours[:, band + 1, :]) & (colours[:, band + 1, :] == colours[:, band + 2, :])
            for x, z in np.argwhere(full & same):
                self._add(nid, [int(x), band, int(z), 1, 1, 3, int(colours[x, band + 1, z])])
                claimed[x, band : band + 3, z] = True
                nid += 1
        for x, y, z in np.argwhere(grid & ~claimed):
            self._add(nid, [int(x), int(y), int(z), 1, 1, 1, int(colours[x, y, z])])
            nid += 1
        self.next_id = nid
        for pid in list(self.parts):
            for other in self._vertical(pid):
                self._union(pid, other)

    def _add(self, pid, rec):
        x, y, z, sx, sz, h, _ = rec
        self.parts[pid] = rec
        self.uf[pid] = pid
        self.owner[x : x + sx, y : y + h, z : z + sz] = pid

    def find(self, a):
        uf = self.uf
        while uf[a] != a:
            uf[a] = uf[uf[a]]
            a = uf[a]
        return a

    def _union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.uf[ra] = rb

    def _vertical(self, pid):
        x, y, z, sx, sz, h, _ = self.parts[pid]
        out = set()
        Y = self.grid.shape[1]
        if y + h < Y:
            out.update(int(v) for v in np.unique(self.owner[x : x + sx, y + h, z : z + sz]) if v >= 0)
        if y > 0:
            out.update(int(v) for v in np.unique(self.owner[x : x + sx, y - 1, z : z + sz]) if v >= 0)
        return out

    def candidates(self, pid):
        """Side neighbours that form an exact rectangle of a real part."""
        x, y, z, sx, sz, h, c = self.parts[pid]
        X, _, Z = self.grid.shape
        seen = set()
        probes = []
        if x + sx < X:
            probes += [(x + sx, z + k) for k in range(sz)]
        if x > 0:
            probes += [(x - 1, z + k) for k in range(sz)]
        if z + sz < Z:
            probes += [(x + k, z + sz) for k in range(sx)]
        if z > 0:
            probes += [(x + k, z - 1) for k in range(sx)]
        for px, pz in probes:
            o = int(self.owner[px, y, pz])
            if o < 0 or o == pid or o in seen:
                continue
            seen.add(o)
            ox, oy, oz, osx, osz, oh, oc = self.parts[o]
            if oy != y or oh != h or oc != c:
                continue
            if ox == x and osx == sx and (oz == z + sz or oz + osz == z):
                nx, nz, nsx, nsz = x, min(z, oz), sx, sz + osz
            elif oz == z and osz == sz and (ox == x + sx or ox + osx == x):
                nx, nz, nsx, nsz = min(x, ox), z, sx + osx, sz
            else:
                continue
            part, _ = _part_for(h, nsx, nsz)
            if part is not None:
                yield o, (nx, nz, nsx, nsz)

    def rebuild_groups(self):
        """Recompute connectivity from scratch (splits can disconnect)."""
        self.uf = {pid: pid for pid in self.parts}
        for pid in self.parts:
            for other in self._vertical(pid):
                self._union(pid, other)

    def loose(self):
        """Parts outside the largest connected group."""
        counts: dict[int, int] = {}
        for pid in self.parts:
            r = self.find(pid)
            counts[r] = counts.get(r, 0) + 1
        if not counts:
            return []
        main = max(counts, key=counts.get)
        return [pid for pid in self.parts if self.find(pid) != main]

    def neighbours(self, pid):
        """Parts touching pid sideways or vertically."""
        x, y, z, sx, sz, h, _ = self.parts[pid]
        X, Y, Z = self.grid.shape
        lo = (max(0, x - 1), max(0, y - 1), max(0, z - 1))
        hi = (min(X, x + sx + 1), min(Y, y + h + 1), min(Z, z + sz + 1))
        block = self.owner[lo[0] : hi[0], lo[1] : hi[1], lo[2] : hi[2]]
        return {int(v) for v in np.unique(block) if v >= 0 and v != pid}

    def split(self, pid):
        """Break a part back into 1x1 plates, one per cell per layer."""
        x, y, z, sx, sz, h, c = self.parts.pop(pid)
        self.uf.pop(pid, None)
        self.owner[x : x + sx, y : y + h, z : z + sz] = -1
        for dx in range(sx):
            for dz in range(sz):
                for dy in range(h):
                    nid = self.next_id
                    self.next_id += 1
                    self._add(nid, [x + dx, y + dy, z + dz, 1, 1, 1, c])

    def merge(self, a, b, rect):
        nx, nz, nsx, nsz = rect
        y, h, c = self.parts[a][1], self.parts[a][5], self.parts[a][6]
        ra, rb = self.find(a), self.find(b)
        del self.parts[a], self.parts[b]
        nid = self.next_id
        self.next_id += 1
        self._add(nid, [nx, y, nz, nsx, nsz, h, c])
        self.uf[ra] = nid
        self.uf[rb] = nid
        return nid


def _merge_all(st: "_State", rng: random.Random):
    # Phase 1: only merges that join two separate groups.
    # Phase 2: merges for size, preferring each layer's direction so seams cross.
    for phase in (1, 2):
        changed = True
        while changed:
            changed = False
            ids = list(st.parts)
            rng.shuffle(ids)
            for pid in ids:
                if pid not in st.parts:
                    continue
                best = None
                for other, rect in st.candidates(pid):
                    joins = st.find(pid) != st.find(other)
                    if phase == 1 and not joins:
                        continue
                    nx, nz, nsx, nsz = rect
                    y = st.parts[pid][1]
                    along_x = nsx >= nsz
                    prefer = (y // st.parts[pid][5]) % 2 == 0
                    score = (joins, nsx * nsz, along_x == prefer, rng.random())
                    if best is None or score > best[0]:
                        best = (score, other, rect)
                if best:
                    st.merge(pid, best[1], best[2])
                    changed = True


def build(grid: np.ndarray, colour_codes: np.ndarray | None = None, default_colour: int = 71, seed: int = 0, rounds: int = 12) -> Layout:
    rng = random.Random(seed)
    colours = colour_codes if colour_codes is not None else np.full(grid.shape, default_colour, dtype=int)
    st = _State(grid, colours)
    _merge_all(st, rng)

    # Repair rounds: split every loose part and everything touching it back
    # into 1x1 plates (plates can bridge where bricks can't), re-merge with a
    # fresh random order, and stop when nothing is loose or it stops helping.
    best_loose = len(st.loose())
    stale = 0
    for _ in range(rounds):
        loose = st.loose()
        if not loose:
            break
        region = set(loose)
        for pid in loose:
            region |= st.neighbours(pid)
        for pid in region:
            if pid in st.parts:
                st.split(pid)
        st.rebuild_groups()
        _merge_all(st, rng)
        now = len(st.loose())
        if now < best_loose:
            best_loose, stale = now, 0
        else:
            stale += 1
            if stale >= 3:
                break

    lay = Layout(shape=grid.shape)
    for x, y, z, sx, sz, h, c in st.parts.values():
        part, along_x = _part_for(h, sx, sz)
        lay.parts.append(Placed(part, x, y, z, along_x, c))
    return lay
