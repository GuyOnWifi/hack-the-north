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
# sonnet plans + builds (fast & reliable from a clean cwd, ~3-8s/call); OPUS is
# the vision critic that actually looks at the render and judges it. (haiku
# intermittently hangs on the per-band prompt; opus builders are 10x slower.)
PLANNER_MODEL = os.environ.get("PLANNER_MODEL", "sonnet")
BUILDER_MODEL = os.environ.get("BUILDER_MODEL", "sonnet")
CRITIC_MODEL = os.environ.get("CRITIC_MODEL", "opus")


def _claude(prompt, model=None, timeout=120):
    # CRITICAL for speed: run from a clean cwd. In the project dir, `claude -p`
    # loads the repo CLAUDE.md + every MCP server + skills on EACH call (~40-70s
    # of pure overhead). From /tmp it skips all that — auth is user-level, so it
    # still works — dropping a per-call cost of ~60s to ~3-11s. That's what makes
    # a multi-agent loop of many small calls viable.
    cmd = ["claude", "-p", prompt]
    if model:
        cmd += ["--model", model]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd="/tmp")
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
- CORBEL wide-on-narrow transitions: a wide feature can NOT sit directly on a thin one (a \
bloom on a 2-wide stem would float). If a band is much wider than the band below, either give it \
enough z-layers to widen GRADUALLY (about +3 studs of width per layer), OR insert a medium \
transition band (a "calyx"/"crown"/"shoulders") between them. Each band's width should be at \
most ~2x the width of the band directly below it.
- STABILITY — the model must STAND on its own, not tip over: make the BOTTOM band a WIDE, solid \
base, at least as wide as the widest band above it (a heavy low base keeps the centre of mass low \
and inside the footprint). For a top-heavy shape (flower bloom, tree canopy), keep the top's size \
modest AND run a solid vertical SPINE (a 2x2 armature column) straight up the centre from the base \
to directly under the top, so the top's weight drops onto the base — name that band 'spine' or fold \
it into the stem. Prefer a stable, grounded silhouette over an extreme cantilever.

Output ONLY the plan, one band per line, bottom band FIRST, in EXACTLY this format:
BAND z<z_from>-<z_to> | <cx>,<cy> | <sx>x<sy> | n=<brick_count> | <short_name>: <what it represents>

Example for a flower (note the calyx corbel between the thin stem and the wide bloom):
BAND z0-1 | 10,10 | 8x8 | n=16 | pot: wide round-ish base the flower sits in
BAND z2-6 | 10,10 | 2x2 | n=6 | stem: thin vertical stalk, centered
BAND z7-8 | 10,10 | 6x6 | n=10 | calyx: cupped base of the bloom, widening out from the stem
BAND z9-11 | 10,10 | 12x12 | n=22 | bloom: wide flower head corbelling out over the calyx

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
- CORBEL, don't float: a brick may hang over the '#' support below by at most HALF its length. \
To spread a wide shape (a bloom) over a narrow base, build your LOWEST z-layer only slightly \
wider than the '#' cells, then each higher z-layer a bit wider, resting on the bricks you just \
placed — a stepped bowl/dome. Emit lower-z bricks BEFORE higher-z bricks so each rests on the last.
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
        # Deliberately DON'T reject "floating" here: a corbelled bloom fans out
        # and only its centre rests on z-1. The final connectivity flood-fill in
        # build() keeps the whole ground-connected component and drops only
        # genuinely detached clusters — so organic overhangs survive.
        for c in cs:
            occ[c] = True
        kept.append((h, w, x, y, z))
    return kept, issues


# Colour bricks by the ROLE of the band they belong to, so a flower reads as a
# flower: brown base, green stem/leaves, coloured bloom. Huge readability win.
_BAND_COLOUR = [
    (("pot", "base", "root", "ground", "soil", "vase", "trunk"), 6),          # brown
    (("stem", "leaf", "leaves", "calyx", "sepal", "branch", "vine", "grass"), 2),  # green
    (("bloom", "flower", "petal", "blossom", "head", "bud", "crown", "center"), 4),  # red
]


def _band_colour(name, prompt):
    n = (name or "").lower()
    for words, code in _BAND_COLOUR:
        if any(w in n for w in words):
            # let an explicit colour word in the prompt override the bloom colour
            if code == 4:
                return harness._color_for(prompt) if _has_colour_word(prompt) else 4
            return code
    return harness._color_for(prompt)


def _has_colour_word(prompt):
    import re
    return any(re.search(rf"\b{w}\b", prompt.lower()) for w in harness.NAME_TO_CODE)


def _colours_for(placed, bands, prompt):
    out = []
    for (h, w, x, y, z) in placed:
        band = next((b for b in bands if b["z_from"] <= z <= b["z_to"]), None)
        out.append(_band_colour(band["name"] if band else "", prompt))
    return out


def _drop_islands(items):
    """Drop ONLY fully-isolated bricks (no face-adjacent neighbour, not on the
    ground) — stray floaters. Keep connected clusters (a bloom) even if the whole
    cluster overhangs; instability is reported, not deleted."""
    if not items:
        return items
    cell = {}
    for i, b in enumerate(items):
        for c in bricks.cells(*b):
            cell[c] = i
    ground_z = min(z for (h, w, x, y, z) in items)
    kept = []
    for i, (h, w, x, y, z) in enumerate(items):
        if z == ground_z:
            kept.append((h, w, x, y, z)); continue
        nb = False
        for (cx, cy, cz) in bricks.cells(h, w, x, y, z):
            for q in ((cx + 1, cy, cz), (cx - 1, cy, cz), (cx, cy + 1, cz),
                      (cx, cy - 1, cz), (cx, cy, cz - 1), (cx, cy, cz + 1)):
                j = cell.get(q)
                if j is not None and j != i:
                    nb = True; break
            if nb:
                break
        if nb:
            kept.append((h, w, x, y, z))
    return kept


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
    bands = bands[:4]                            # cap calls — each CLI call is slow
    tape.emit("planner", "plan",
              f"plan: {len(bands)} bands — {', '.join(b['name'] for b in bands)}",
              status="ok", ms=100)

    placed, occ = [], {}
    for band in bands:
        tape.emit("builder", "build",
                  f"building {band['name']} (z{band['z_from']}–{band['z_to']})…",
                  status="running", ms=900, tokens=400)
        t0 = time.time()
        try:
            new = build_layer(prompt, bands, band, placed, occ)
        except subprocess.TimeoutExpired:
            tape.emit("builder", "build", f"{band['name']}: builder timed out — "
                      f"skipping this band, keeping what stands", status="warn", ms=5)
            _log(f"band {band['name']}: TIMED OUT, skipping")
            continue                             # a slow band never kills the whole build
        kept, issues = inspect(new, occ, band)
        _log(f"band {band['name']}: builder gave {len(new)}, kept {len(kept)}, "
             f"{len(issues)} issues, {time.time()-t0:.0f}s")
        # one recursive repair if the band came back mostly broken
        if issues and len(kept) < max(2, band["n"] // 2):
            tape.emit("inspector", "reject",
                      f"{band['name']}: {len(issues)} bad bricks — sending back to the builder",
                      status="warn", ms=30)
            try:
                new = build_layer(prompt, bands, band, placed, occ, fixup=_fixup_note(issues))
                k2, _ = inspect(new, occ, band)
                kept += k2
            except subprocess.TimeoutExpired:
                pass
        placed += kept
        tape.emit("inspector", "check",
                  f"{band['name']}: {len(kept)} bricks held (total {len(placed)})",
                  status="ok", ms=40)
        harness._emit_geometry(tape, placed, f"placed {band['name']} — {len(placed)} bricks", draft=False)

    # Keep the whole inspected shape (each brick already passed bounds+collision
    # per band). We DON'T flood-fill to ground here anymore — that was dropping a
    # flower's entire bloom as "disconnected." A few overhanging bricks are fine;
    # instability is reported (red), not deleted. Just drop isolated single cells.
    placed = _drop_islands(placed)
    if len(placed) < 6:
        tape.emit("inspector", "reject",
                  f"only {len(placed)} bricks survived — too sparse", status="fail", ms=5)
        raise HarnessError(f"only {len(placed)} bricks held up for “{prompt}”. Try again.")
    colours = _colours_for(placed, bands, prompt)     # colour by band role (pre-normalize z)
    placed = harness._normalize(placed)
    res = physics.analyze(placed)
    stable = physics.stands(placed)
    tape.emit("inspector", "physics",
              f"stability check: {'stands up' if stable else 'top-heavy, may not stand'} "
              f"({res.get('studs', 0)} stud joints)",
              status="ok" if stable else "warn", ms=45)
    build = bricks.to_build(placed, name=name or prompt.title(), colors=colours)
    _log(f"assemble '{prompt}': DONE — {len(build.parts)} parts, stable={res['stable']}")
    return build


def vision_check(build, prompt, tape=None):
    """VISION CRITIC: render the finished model and show the IMAGE to a strong
    multimodal model — does it actually read as the object? Returns (score, note).
    This is the 'give it the images' loop; failure never blocks the build."""
    try:
        import render
        img = "/tmp/agent_look.png"
        render.render_build(build, img, view="iso")
        ask = (f"@{img}\nThis is an isometric render of a LEGO brick model meant to be "
               f"\"{prompt}\". Judge ONLY whether it clearly reads as that object in 3D. "
               f"Reply with exactly one line: SCORE=<0-10> — <one short sentence on what's "
               f"missing or wrong structurally>.")
        out = _claude(ask, model=CRITIC_MODEL, timeout=90)
        m = re.search(r"SCORE\s*=\s*(\d+)", out)
        score = int(m.group(1)) if m else 5
        note = re.sub(r"\s+", " ", out).strip()[:200]
        _log(f"vision_check '{prompt}': score={score} — {note}")
        if tape:
            tape.emit("critic", "look", f"looked at the render — {note}",
                      status="ok" if score >= 6 else "warn", ms=80, tokens=500)
        return score, note
    except Exception as e:
        _log(f"vision_check failed: {e}")
        return 10, ""
