"""The multi-agent, layer-by-layer LEGO builder — the Huawei openJiuwen play.

Three collaborating agents build bottom-up, one horizontal band at a time:

  PLANNER   decomposes the object into a stack of layer-bands (region + budget).
  BUILDER   (looped per band) emits only that band's bricks, given the plan AND
            the bricks already placed below it.
  INSPECTOR (deterministic) lint + connectivity + force/torque checks each band
            against the accumulated build; a bad band goes BACK to the builder
            with the specific errors (recursive repair).

After each band we stream the accumulated model to the UI (a `geometry` tape
event), so the user watches it build brick-by-brick instead of waiting for a
single 2-minute one-shot. Instability is reported (red), never silently fixed.
"""
from __future__ import annotations
import re
import subprocess
import time

import bricks
import physics
import harness                       # reuse available/_color_for/_normalize/_log/HarnessError/_emit_geometry
from harness import _log, HarnessError

# Per-agent models: a strong model plans (few tokens, high leverage); a fast
# model fills each band (small output, latency-critical). Overridable by env.
import os
PLANNER_MODEL = os.environ.get("PLANNER_MODEL", "sonnet")
BUILDER_MODEL = os.environ.get("BUILDER_MODEL", "haiku")


def _claude(prompt, model=None, timeout=120):
    cmd = ["claude", "-p", prompt]
    if model:
        cmd += ["--model", model]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return out.stdout


# ---------------------------------------------------------------- PLANNER -----
PLANNER_PROMPT = """You are the PLANNER for a bottom-up 3D LEGO builder. Break an \
object into a stack of horizontal LAYER-BANDS on a 20x20x20 grid (z=0 is the ground, \
build upward; each band is a contiguous range of integer z-layers).

Object: "{prompt}"

Think about the object's real 3D silhouette from the side, then slice it bottom-to-top \
into 3-6 bands. Rules for a good plan:
- Bands stack with NO z-gaps: the first band starts at z=0, and each band's z_from equals \
the previous band's z_to+1. Total height 6-14 layers.
- Every band must physically REST on the one below: its footprint region must OVERLAP the \
region below it, so nothing floats. A narrow feature (stem, neck, leg) sits centered on the base.
- Pick regions that make the silhouette READ as the object: wide where the object is wide \
(base, bloom, body), narrow where it's narrow (stem, neck). Use the grid generously — a good \
model spans ~8-16 studs, centered near x=6..12, y=6..12.
- Region = center (cx,cy) and size (sx,sy) in studs. Keep sx,sy within 2..16 and inside 0..20.
- Brick count per band scales with area (a thin stem ~2-6, a wide base ~10-25).

Output ONLY the plan, one band per line, bottom band FIRST, in EXACTLY this format:
BAND z<z_from>-<z_to> | <cx>,<cy> | <sx>x<sy> | n=<brick_count> | <short_name>: <what it represents>

Example for a flower:
BAND z0-1 | 10,10 | 8x8 | n=18 | pot: wide round-ish base the flower sits in
BAND z2-6 | 10,10 | 2x2 | n=6 | stem: thin vertical stalk, centered
BAND z5-6 | 10,10 | 10x2 | n=6 | leaves: two leaves off the stem
BAND z7-11 | 10,10 | 12x12 | n=22 | bloom: wide flat flower head

Output 3-6 BAND lines and NOTHING else."""

_BAND = re.compile(
    r"BAND\s+z(\d+)-(\d+)\s*\|\s*(\d+)\s*,\s*(\d+)\s*\|\s*"
    r"(\d+)\s*x\s*(\d+)\s*\|\s*n=(\d+)\s*\|\s*([^:]+?)\s*:\s*(.+)", re.I)


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def parse_plan(text):
    """Planner text -> ordered, sanitised band dicts with explicit x/y boxes."""
    bands = []
    for m in _BAND.finditer(text):
        zf, zt, cx, cy, sx, sy, n = (int(v) for v in m.groups()[:7])
        bands.append({"z_from": zf, "z_to": zt, "cx": cx, "cy": cy,
                      "sx": sx, "sy": sy, "n": n,
                      "name": m.group(8).strip(), "desc": m.group(9).strip()})
    bands.sort(key=lambda b: b["z_from"])
    # sanitise: no z-gaps, ground starts at 0, region boxes clamped in-bounds
    z = 0
    for b in bands:
        span = max(0, b["z_to"] - b["z_from"])
        b["z_from"] = z
        b["z_to"] = min(bricks.GRID - 1, z + span)
        z = b["z_to"] + 1
        sx, sy = _clamp(b["sx"], 2, 16), _clamp(b["sy"], 2, 16)
        b["x0"] = _clamp(b["cx"] - sx // 2, 0, bricks.GRID - 1)
        b["y0"] = _clamp(b["cy"] - sy // 2, 0, bricks.GRID - 1)
        b["x1"] = _clamp(b["x0"] + sx - 1, 0, bricks.GRID - 1)
        b["y1"] = _clamp(b["y0"] + sy - 1, 0, bricks.GRID - 1)
    return bands


def plan(prompt):
    txt = _claude(PLANNER_PROMPT.format(prompt=prompt), model=PLANNER_MODEL, timeout=150)
    bands = parse_plan(txt)
    _log(f"planner: {len(bands)} bands -> {[b['name'] for b in bands]}")
    if not bands:
        _log(f"planner produced no bands. head: {txt[:200]!r}")
    return bands


# ---------------------------------------------------------------- BUILDER -----
LAYER_BUILDER_PROMPT = """You build ONE horizontal band of a 3D LEGO model, in the \
BrickGPT grammar. Output ONLY brick lines, one per line, nothing else. Each line:
  hxw (x,y,z)
= a brick with footprint h by w studs, corner at (x,y,z); x,y horizontal, z the integer \
height LAYER. Allowed footprints (either orientation): 1x1 1x2 1x3 1x4 1x6 1x8 2x2 2x3 2x4 2x6 2x8.

Object being built: "{prompt}"

Full plan, bottom to top (context — do NOT rebuild these):
{plan}

YOUR band ONLY — emit bricks for THIS band and no other:
  z-layers {z_from} to {z_to} | region x {x0}..{x1}, y {y0}..{y1} (stay inside this box) | ~{n} bricks
  represents: {name} — {desc}

Cells directly BENEATH your band (layer z={z_below}) in your region — '#' = filled \
(you can stack on it), '.' = empty (x {x0}..{x1} across, y {y0}..{y1} down):
{support_grid}
Put each brick at z={z_from} so at least one of its studs sits over a '#'.

Bricks ALREADY PLACED below you ({placed_count} bricks, hxw (x,y,z)):
{placed}

Hard rules:
- Every brick's z must be in [{z_from}, {z_to}].
- SUPPORT: every brick at z sits on a brick at z-1 (from the placed list or from THIS band), \
except z=0 bricks which sit on the ground. Do not float.
- NO COLLISIONS: never reuse an (x,y,z) cell already filled below or by your own bricks.
- Stay inside the region box and the 20x20 grid (0..19).
- Match the {name} shape: solid where it reads solid, outline for thin features. Prefer bigger \
footprints (2x4, 2x6) for solid areas, 1x1/1x2 for detail and edges.{fixup}

Output only the brick lines for z {z_from}..{z_to}."""


def _plan_text(bands):
    return "\n".join(f"BAND z{b['z_from']}-{b['z_to']} | {b['name']}: {b['desc']}" for b in bands)


def _support_grid(occ, z, x0, y0, x1, y1):
    """Top-down ASCII of layer z's filled cells over the region — the builder's
    map of where it can legally stack (tactic S1 from the research)."""
    if z < 0:
        return "(ground — lay this first band flat on the plate at z=0)"
    rows = ["".join("#" if (x, y, z) in occ else "." for x in range(x0, x1 + 1))
            for y in range(y0, y1 + 1)]
    return "\n".join(rows) if rows else "(empty)"


def build_layer(prompt, bands, band, placed, occ, fixup=""):
    placed_txt = "\n".join(f"{h}x{w} ({x},{y},{z})" for (h, w, x, y, z) in placed[-60:]) \
        if placed else "(none — this is the ground band; build on the plate at z=0)"
    z_below = band["z_from"] - 1
    p = LAYER_BUILDER_PROMPT.format(
        prompt=prompt, plan=_plan_text(bands),
        z_from=band["z_from"], z_to=band["z_to"], z_below=z_below,
        x0=band["x0"], x1=band["x1"], y0=band["y0"], y1=band["y1"],
        support_grid=_support_grid(occ, z_below, band["x0"], band["y0"], band["x1"], band["y1"]),
        n=band["n"], name=band["name"], desc=band["desc"],
        placed_count=len(placed), placed=placed_txt, fixup=fixup)
    return bricks.parse(_claude(p, model=BUILDER_MODEL, timeout=180))


# -------------------------------------------------------------- INSPECTOR -----
def inspect(new, occ, band):
    """Deterministic gate for one band's bricks against the accumulated cells
    `occ`. Returns (kept, issues). Mutates occ with kept bricks."""
    kept, issues = [], []
    for (h, w, x, y, z) in new:
        if not bricks.part_for(h, w):
            issues.append(("UNKNOWN_PART", (h, w, x, y, z))); continue
        if not (0 <= x and x + h <= bricks.GRID and 0 <= y and y + w <= bricks.GRID
                and band["z_from"] <= z <= band["z_to"]):
            issues.append(("OUT_OF_BAND", (h, w, x, y, z))); continue
        cs = bricks.cells(h, w, x, y, z)
        if cs & occ.keys():
            issues.append(("COLLISION", (h, w, x, y, z))); continue
        if not (z == 0 or any((cx, cy, z - 1) in occ for (cx, cy, _) in cs)):
            issues.append(("FLOATING", (h, w, x, y, z))); continue
        for c in cs:
            occ[c] = True
        kept.append((h, w, x, y, z))
    return kept, issues


def _fixup_note(issues):
    kinds = {}
    for code, _ in issues:
        kinds[code] = kinds.get(code, 0) + 1
    bad = ", ".join(f"{n} {c.lower().replace('_', ' ')}" for c, n in kinds.items())
    return (f"\n\nYour previous attempt had {bad}. Fix them: keep every brick supported by "
            f"a brick directly below (or ground at z=0), inside the region box, no overlaps.")


# --------------------------------------------------------------- ASSEMBLE -----
def build(prompt, name=None, tape=None, seed=0):
    """Plan -> build each band (with per-band inspect + one repair) -> stream ->
    assemble. Returns a Lane-B Build. Loud errors, no canned fallback."""
    from tape import Tape
    tape = tape or Tape()

    if not harness.available():                 # PROVIDER=mock: dev scaffold only
        items = harness._normalize(harness._propose_mock(prompt))
        return bricks.to_build(items, name=name or prompt.title(),
                               color=harness._color_for(prompt))

    tape.emit("planner", "plan", f"planning the layer-by-layer build for '{prompt}'…",
              status="running", ms=1200, tokens=700)
    bands = plan(prompt)
    if not bands:
        tape.emit("planner", "plan", "planner returned no plan — no fallback", status="fail", ms=5)
        raise HarnessError(f"the planner produced no plan for “{prompt}”. Try again.")
    tape.emit("planner", "plan",
              f"plan: {len(bands)} bands — {', '.join(b['name'] for b in bands)}",
              status="ok", ms=100)

    placed, occ = [], {}
    for band in bands:
        tape.emit("builder", "build",
                  f"building {band['name']} (z{band['z_from']}–{band['z_to']})…",
                  status="running", ms=900, tokens=400)
        t0 = time.time()
        new = build_layer(prompt, bands, band, placed, occ)
        kept, issues = inspect(new, occ, band)
        _log(f"band {band['name']}: builder gave {len(new)}, kept {len(kept)}, "
             f"{len(issues)} issues, {time.time()-t0:.0f}s")
        # one recursive repair if the band came back mostly broken
        if issues and len(kept) < max(2, band["n"] // 2):
            tape.emit("inspector", "reject",
                      f"{band['name']}: {len(issues)} bad bricks — sending back to the builder",
                      status="warn", ms=30)
            new = build_layer(prompt, bands, band, placed, occ, fixup=_fixup_note(issues))
            k2, _ = inspect(new, occ, band)
            kept += k2
        placed += kept
        tape.emit("inspector", "check",
                  f"{band['name']}: {len(kept)} bricks held (total {len(placed)})",
                  status="ok", ms=40)
        harness._emit_geometry(tape, placed, f"placed {band['name']} — {len(placed)} bricks", draft=False)

    placed = harness._normalize(placed)
    if len(placed) < 6:
        tape.emit("inspector", "reject",
                  f"only {len(placed)} bricks survived — too sparse", status="fail", ms=5)
        raise HarnessError(f"only {len(placed)} bricks held up for “{prompt}”. Try again.")
    res = physics.analyze(placed)
    tape.emit("inspector", "physics",
              f"force + torque check: {'stands up' if res['stable'] else 'top-heavy, may not stand'} "
              f"({res.get('studs', 0)} stud joints)",
              status="ok" if res["stable"] else "warn", ms=45)
    build = bricks.to_build(placed, name=name or prompt.title(), color=harness._color_for(prompt))
    _log(f"assemble '{prompt}': DONE — {len(build.parts)} parts, stable={res['stable']}")
    return build
