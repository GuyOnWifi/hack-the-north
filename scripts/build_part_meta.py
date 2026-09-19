"""Auto-generate + verify the part metadata table from real LDraw .dat files
(build plan T+0->T+4; risk #1: "a wrong metadata row is a 3-hour 2am bug").

The LDraw *writer* stays hand-rolled (invariant #1) — this is the one place an
LDraw *reader* earns its keep. Every official part .dat starts with a
description line like `0 Brick  2 x  4`, which gives dimensions directly; no
need to bounding-box the geometry.

Usage:
    python scripts/build_part_meta.py [/path/to/ldraw]     # verify vs meta.py
    LDRAW_DIR=~/ldraw python scripts/build_part_meta.py

Without a library on disk it prints the hand table for eyeballing and exits 0.
The parsing functions are importable (and unit-tested) so this is verifiable
before the 80MB library is downloaded.
"""
from __future__ import annotations
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "bricolage"))

_DIM = re.compile(r"(\d+)\s*x\s*(\d+)")


def parse_description(desc):
    """`0 Brick 2 x 4` (already stripped of the leading '0 ') -> metadata dict,
    or None if it isn't a whitelist-shaped part."""
    d = desc.strip()
    low = d.lower()
    m = _DIM.search(d)
    if not m:
        return None
    dx, dz = int(m.group(1)), int(m.group(2))
    if "plate" in low:
        h, studs = 1, True
    elif "tile" in low:
        h, studs = 1, False
    elif "slope" in low:
        h, studs = 3, False
    elif "brick" in low:
        h, studs = 3, True
    else:
        return None
    return {"name": d, "dx": dx, "dz": dz, "h": h, "studs": studs}


_MOVED = re.compile(r"~Moved to (\w+)", re.I)


def redirect_target(dat_text):
    """Official parts that were renamed start with `0 ~Moved to <part>`."""
    for line in dat_text.splitlines():
        line = line.strip()
        if line.startswith("0 "):
            m = _MOVED.search(line)
            return m.group(1) if m else None
    return None


def derive_meta(dat_text):
    """First non-empty `0 ...` comment line is the part description."""
    for line in dat_text.splitlines():
        line = line.strip()
        if line.startswith("0 ") and not line.startswith("0 !") and \
           not line.startswith("0 //"):
            return parse_description(line[2:])
    return None


def resolve(ldraw_dir, part, depth=0):
    """Read a part's metadata, following `~Moved to` redirects (max depth 4).
    Returns (meta, resolved_part) or (None, part)."""
    path = _find_dat(ldraw_dir, part)
    if not path or depth > 4:
        return None, part
    with open(path, encoding="latin-1") as f:
        text = f.read()
    tgt = redirect_target(text)
    if tgt:
        return resolve(ldraw_dir, tgt, depth + 1)
    return derive_meta(text), part


def _find_dat(ldraw_dir, part):
    for sub in ("parts", "p", "."):
        path = os.path.join(ldraw_dir, sub, f"{part}.dat")
        if os.path.exists(path):
            return path
    return None


def main():
    from meta import PART_META
    ldraw_dir = (sys.argv[1] if len(sys.argv) > 1
                 else os.environ.get("LDRAW_DIR", os.path.expanduser("~/ldraw")))
    if not os.path.isdir(ldraw_dir):
        print(f"LDraw library not found at {ldraw_dir!r}.")
        print("Nothing to verify against — current hand table:")
        for part, m in PART_META.items():
            print(f"  {part:6} {m['name']:18} {m['dx']}x{m['dz']} h{m['h']} "
                  f"{'studs' if m['studs'] else 'no-studs'}")
        return 0

    ok, warn, missing = 0, 0, 0
    for part, hand in PART_META.items():
        got, resolved = resolve(ldraw_dir, part)
        via = f" (via {resolved})" if resolved != part else ""
        if not got:
            print(f"  ?  {part}: no .dat / couldn't parse{via}"); missing += 1; continue
        diffs = [k for k in ("dx", "dz", "h", "studs") if got[k] != hand[k]]
        if diffs:
            print(f"  ✗  {part} {hand['name']}{via}: "
                  f"hand={ {k:hand[k] for k in diffs} } "
                  f"dat={ {k:got[k] for k in diffs} }"); warn += 1
        else:
            print(f"  ✓  {part} {hand['name']}{via}"); ok += 1
    print(f"\n{ok} verified, {warn} mismatched, {missing} missing "
          f"(of {len(PART_META)}).")
    return 1 if warn else 0


if __name__ == "__main__":
    sys.exit(main())
