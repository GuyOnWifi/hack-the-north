"""Self-contained test suite. Run:  python bricolage/tests.py
No pytest dependency — plain asserts so it runs anywhere (DEMO_SAFE).

The four validator tests come first (build plan T+4->T+8): three bad builds,
one good. If the validator is right, nothing downstream can produce a model
that doesn't exist.
"""
from __future__ import annotations

from model import Build, Part, Inventory
from validate import validate
from generators import expand
from ldraw import to_ldr
from sequence import sequence
from proposer import synthesize
from pipeline import build_from_prompt
import json

PASS, FAIL = "\x1b[32mPASS\x1b[0m", "\x1b[31mFAIL\x1b[0m"
_n = [0, 0]


def check(name, cond):
    _n[0] += 1
    if cond:
        _n[1] += 1
        print(f"  {PASS}  {name}")
    else:
        print(f"  {FAIL}  {name}")


def _b(parts):
    return Build("t", 0, "t", tuple(parts), (), {})


# ---------------------------------------------------- the four validator tests
def test_good():
    b = _b([Part("a", "3001", 4, (0, 0, 0)),
            Part("b", "3001", 4, (0, 3, 0))])   # stacked, connected, grounded
    check("GOOD: stacked bricks validate ok", validate(b).ok)


def test_overlap():
    b = _b([Part("a", "3001", 4, (0, 0, 0)),
            Part("b", "3003", 4, (0, 0, 0))])
    codes = {e["code"] for e in validate(b).errors}
    check("BAD: overlapping bricks -> OVERLAP", "OVERLAP" in codes)


def test_floating():
    b = _b([Part("g", "3001", 4, (0, 0, 0)),
            Part("f", "3001", 4, (0, 10, 0))])
    codes = {e["code"] for e in validate(b).errors}
    check("BAD: brick in mid-air -> FLOATING", "FLOATING" in codes)


def test_disconnected():
    b = _b([Part("a", "3001", 4, (0, 0, 0)),
            Part("b", "3001", 4, (20, 0, 0))])   # both grounded, far apart
    codes = {e["code"] for e in validate(b).errors}
    check("BAD: two separate piles -> DISCONNECTED", "DISCONNECTED" in codes)


# ---------------------------------------------------------------- invariants
def test_no_floats_in_model():
    b = expand(synthesize("rover"), seed=0)
    ok = all(isinstance(v, int) for p in b.parts for v in p.pos)
    ok = ok and all(p.rot in (0, 90, 180, 270) for p in b.parts)
    check("INVARIANT: build model is pure-integer, 90-deg rots", ok)


def test_determinism():
    a = to_ldr(expand(synthesize("rover"), seed=7))
    c = to_ldr(expand(synthesize("rover"), seed=7))
    check("INVARIANT: same seed => byte-identical LDraw", a == c)
    d = to_ldr(expand(synthesize("rover"), seed=8))
    check("determinism: different seed => different tiling", a != d)


def test_ldraw_roundtrip():
    b = expand(synthesize("rover"), seed=0)
    text = to_ldr(b)
    lines = [l for l in text.splitlines() if l.startswith("1 ")]
    check("LDraw: one type-1 line per part", len(lines) == len(b.parts))
    check("LDraw: every line references a .dat", all(l.endswith(".dat") for l in lines))


def test_insertion_sweep():
    # a brick trapped directly under another in the same column is unbuildable
    from sequence import Unbuildable
    b = _b([Part("low", "3005", 4, (0, 0, 0)),
            Part("cap", "3005", 4, (0, 3, 0))])
    try:
        sequence(b)
        check("SEQUENCE: normal stack is buildable", True)
    except Unbuildable:
        check("SEQUENCE: normal stack is buildable", False)


# ---------------------------------------------------------- golden compose set
GOLDEN = ["build a rover", "a small truck", "build a big buggy", "build a house",
          "build a garage", "make a tower", "a long wall", "build a jet",
          "build a pyramid", "build a heart"]


def test_golden():
    from demo import rich_bin
    ok_count = 0
    for prompt in GOLDEN:
        res = build_from_prompt(prompt, rich_bin(), seed=0)
        if res["report"].ok and res["steps"]:
            ok_count += 1
        else:
            print(f"       \x1b[33m{prompt!r} -> {'ok' if res['report'].ok else 'DEGRADED'}\x1b[0m")
    check(f"GOLDEN: {ok_count}/{len(GOLDEN)} prompts reach a valid, sequenced build",
          ok_count == len(GOLDEN))


def test_substitution_fires():
    # Prompts go to the design harness now, which skips the inventory ladder;
    # the ladder still repairs edits, so drive it directly with a rover.
    from demo import adversarial_bin
    from generators import expand
    from proposer import synthesize
    from repair import Budget, fix
    from tape import Tape
    rover = expand(synthesize("rover", 1.0, 0), name="rover", seed=0)
    res = fix(rover, adversarial_bin(), Budget(seed=0), Tape())
    used_sub = res.rung_hits.get(2, 0) > 0
    check("REPAIR: adversarial bin (no 2x4s) forces the substitution rung",
          used_sub and res.report.ok)


def test_generator_ids_unique():
    from generators import bonded, roof
    ps = bonded(6, 6, 0, 4, 0, plates=True, courses=2)
    check("GEN: bonded emits unique part ids across courses",
          len({p.id for p in ps}) == len(ps))
    for pitch in ("flat", "hip", "gable"):
        r = roof(6, 6, pitch)
        check(f"GEN: roof pitch={pitch} is internally valid",
              validate(_b(list(r.parts))).ok)


def test_lenient_expand():
    from generators import expand
    comp = {"root": {"gen": "chassis", "args": {"length": 8, "width": 4},
            "children": [
                {"gen": "cabin", "attach": "deck_front", "args": {"width": 4, "depth": 4}},
                {"gen": "wall", "attach": "deck_rear", "args": {"length": 6}},  # too big
                {"gen": "cabin", "attach": "bogus_socket", "args": {}}]}}       # unknown
    b = expand(comp, lenient=True, seed=0)
    kept = {s.gen for s in b.subs}
    check("LENIENT: keeps valid children, drops the impossible ones",
          kept == {"chassis", "cabin"} and len(b.provenance["dropped"]) == 2
          and validate(b).ok)


def test_meta_parser():
    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "scripts"))
    from build_part_meta import parse_description, derive_meta
    b = parse_description("Brick 2 x 4")
    check("META: 'Brick 2 x 4' -> 2x4 h3 studs",
          b == {"name": "Brick 2 x 4", "dx": 2, "dz": 4, "h": 3, "studs": True})
    t = parse_description("Tile 2 x 2 with Groove")
    check("META: 'Tile ...' -> h1, no studs", t["h"] == 1 and t["studs"] is False)
    p = parse_description("Plate 1 x 2")
    check("META: 'Plate 1 x 2' -> h1 studs", p["h"] == 1 and p["studs"] is True)
    d = derive_meta("0 Brick 2 x 2\n0 Name: 3003.dat\n1 16 0 0 0 ...\n")
    check("META: derive_meta reads the description line",
          d["dx"] == 2 and d["dz"] == 2)
    from build_part_meta import redirect_target
    check("META: follows '~Moved to' redirects",
          redirect_target("0 ~Moved to 3023b\n0 Name: 3023.dat\n") == "3023b")


def test_physics():
    import stability
    from generators import bonded, expand
    from proposer import synthesize
    # a leaning corbel: each 2x2 course overlaps the one below by 1 stud (so it
    # stays CONNECTED) but keeps stepping out until its COM leaves the base.
    corbel = []
    for k in range(8):
        for p in bonded(2, 2, 0, 4, 0, courses=1):
            corbel.append(Part(f"c{k}_{p.id}", p.part, p.color,
                               (p.pos[0] + k, 3 * k, p.pos[2]), 0, "c"))
    conn_ok = validate(_b(corbel), physics=False).ok      # connectivity passes
    phys = [f.code for f in stability.analyze(corbel)]
    check("PHYSICS: a connected-but-leaning tower is caught (TOPPLE)",
          conn_ok and "TOPPLE" in phys)
    rover = expand(synthesize("rover"), seed=0)
    check("PHYSICS: a normal rover is stable", not stability.analyze(rover.parts))


def test_stabilize():
    import stability
    from generators import bonded
    corbel = []
    for k in range(8):
        for p in bonded(2, 2, 0, 4, 0, courses=1):
            corbel.append(Part(f"c{k}_{p.id}", p.part, p.color,
                               (p.pos[0] + k, 3 * k, p.pos[2]), 0, "c"))
    assert any(f.code == "TOPPLE" for f in stability.analyze(corbel))
    fixed, added = stability.stabilize(corbel, 0)
    check("PHYSICS: self-repair adds a foundation that removes the topple",
          added > 0 and not any(f.code == "TOPPLE" for f in stability.analyze(fixed)))


def test_repair_survives_bad_composition():
    from model import Inventory
    from generators import expand
    from repair import Budget, fix
    from tape import Tape
    comp = {"root": {"gen": "chassis", "args": {"length": 8, "width": 4},
            "children": [{"gen": "tower", "attach": "underside_front", "args": {}},
                         {"gen": "cabin", "attach": "deck_front", "args": {"width": 4}}]}}
    b = expand(comp, lenient=True, seed=0)
    try:
        fix(b, Inventory({("3003", 72): 2}), Budget(seed=0), Tape())
        ok = True
    except Exception:
        ok = False
    check("REPAIR: a bad LLM composition degrades, never crashes the loop", ok)


def test_voxel_shapes():
    from demo import rich_bin
    from pipeline import build_from_prompt
    import stability
    for prompt in ("build me a flower", "build a tree", "build a mushroom"):
        res = build_from_prompt(prompt, rich_bin(), seed=0)
        ok = (res["report"].ok and res["steps"] and
              stability.report(res["build"].parts)["stable"])
        check(f"SHAPE: '{prompt}' -> valid, stable, sequenced build", ok)


def test_version_tree():
    from demo import rich_bin
    from session import Session
    s = Session(rich_bin())
    s.build("build a rover"); s.edit("make the chassis longer")
    head_before = s.head
    sib = s.try_another()                       # sibling of head, same parent
    check("VERSION: try_another makes a sibling (same parent)",
          sib.parent == s.versions[head_before].parent and sib.id != head_before)
    s.undo()
    check("VERSION: undo moves head to parent", s.head == sib.parent)
    s.redo()
    check("VERSION: redo returns to the child", s.head == sib.id)


def test_replay_identical():
    from demo import rich_bin
    from session import Session
    s = Session(rich_bin())
    s.build("build a truck"); s.edit("make the chassis longer")
    s.edit("make the cabin taller")
    orig = to_ldr(s.versions[s.head].build)
    replay = to_ldr(s.replay())
    check("VERSION: replay of the op chain is byte-identical (DoD #2)",
          orig == replay)




# ======================================================== pipeline C: editing
# docs/EDITING.md section I. All offline: no model call, no clock, no network.
import os as _os
import pathlib as _pathlib

LAB = _pathlib.Path(__file__).resolve().parent.parent / "web" / "public" / "lab"
MODELS = _pathlib.Path(__file__).resolve().parent.parent / "web" / "public" / "models"


def _sess():
    from model import Inventory
    from session import Session
    return Session(Inventory({}, unlimited=True))


def _load(name, folder=LAB, ext=".ldr"):
    s = _sess()
    s.load_ldr(name, (folder / f"{name}{ext}").read_text(), name)
    return s


def _type1(text):
    return [l for l in text.splitlines() if l.startswith("1 ")]


def _highest(model):
    """The part with nothing above it: smallest LDraw y (—Y is up)."""
    return min(model.parts, key=lambda p: p.M[1, 3]).id


def test_c_load():
    from brickify import edits as E
    ok = True
    for name, want_clean in (("a-fox", True), ("cat", True), ("dog-holding-an-umbrella", False)):
        src = (LAB / f"{name}.ldr").read_text()
        s = _load(name)
        m = s.model_at()
        v = s.versions[s.head]
        ok = ok and len(m.parts) == len(_type1(src))
        ok = ok and [p.id for p in m.parts] == [f"p{i}" for i in range(len(m.parts))]
        ok = ok and not E.scene(m)["loose"]
        ok = ok and _type1(v.build.provenance["ldr"]) == _type1(src)
        if want_clean:
            ok = ok and len(E.pairs(m)) == 0
    check("C-LOAD: fox/cat/umbrella load flat, ids p0.., nothing loose, text preserved", ok)


def test_c_load_mpd():
    from brickify import edits as E, partlib
    s = _load("car", MODELS, ".mpd")
    m = s.model_at()
    t = E.table(m)
    ok = (t["count"] == 61 and len(m.parts) == 61
          and all(r["geometry"] in ("kit", "derived", "described", "fallback") for r in t["parts"])
          and all(partlib.info(p.pid, m.lib) is not None for p in m.parts))
    s2 = _load("lunar", MODELS, ".mpd")
    m2 = s2.model_at()
    ok = ok and not any(p.ref.lower().endswith((".ldr", ".mpd")) for p in m2.parts)
    ok = ok and "Vehicle" in {p.body for p in m2.parts} and len(m2.parts) > 50
    check("C-LOAD: car.mpd resolves every part; lunar.mpd flattens its sub-models", ok)


def test_gate_overlap():
    s = _load("a-fox")
    m = s.model_at()
    before = s.versions[s.head].build.provenance["ldr"]
    v, res = s.edit_parts([{"op": "move", "ids": [_highest(m)], "d": [0, -3, 0], "settle": False}])
    check("GATE: pushing a piece into its neighbour -> COLLIDES, nothing changed",
          v is None and res.code == "COLLIDES" and res.human
          and s.versions[s.head].build.provenance["ldr"] == before)


def test_gate_floating():
    s = _load("a-fox")
    v, res = s.edit_parts([{"op": "move", "ids": [_highest(s.model_at())],
                            "d": [0, 10, 0], "settle": False}])
    check("GATE: lifting a piece into thin air -> FLOATING", v is None and res.code == "FLOATING")


TIP_LDR = """0 tip test
0 Name: tip.ldr

1 4 0 -24 0 1 0 0 0 1 0 0 0 1 3003.dat
0 STEP
1 14 0 -48 0 1 0 0 0 1 0 0 0 1 3007.dat
0 STEP
"""


def test_gate_tip():
    from brickify import edits as E
    s = _sess()
    s.load_ldr("Tip", TIP_LDR)
    accepted, verdict = 0, None
    for _ in range(8):
        m = s.model_at()
        v, res = s.edit_parts([{"op": "add", "part": "3007", "colour": 14,
                                "on": _highest(m), "settle": False}])
        if not res.accepted:
            verdict = res
            break
        accepted += 1
        v, res = s.edit_parts([{"op": "move", "ids": [res.added[0]], "d": [1, 0, 0], "settle": False}])
        if not res.accepted:
            verdict = res
            break
        accepted += 1
    ok = (verdict is not None and verdict.code == "TIPS" and accepted >= 2
          and any(w in verdict.human for w in ("front", "back", "left", "right")))
    check("GATE: stacking a tower outward is accepted until it would tip, then TIPS", ok)

    # an already-leaning model: an edit may not make the lean worse, but a
    # recolour (which moves no weight) still goes through
    s2 = _load("dog-holding-an-umbrella")
    m2 = s2.model_at()
    st = E.stand_of(m2)
    axis = 0 if st["direction"] in ("-x", "+x") else 2
    sign = -1 if st["direction"].startswith("-") else 1
    d = [0, 0, 0]
    d[axis] = 2 * sign
    worse = None
    from brickify import partlib as _pl

    def _vol(q):
        b = _pl.info(q.pid, m2.lib).box
        return (b[1] - b[0]) * (b[3] - b[2]) * (b[5] - b[4])

    # the heaviest pieces furthest down the slope shift the weight most
    for p in sorted(m2.parts, key=lambda q: (-_vol(q), -sign * q.M[axis, 3]))[:40]:
        _, r = s2.edit_parts([{"op": "move", "ids": [p.id], "d": d, "settle": False}], dry_run=True)
        if r.code == "TIPS_WORSE":
            worse = r
            break
    _, rc = s2.edit_parts([{"op": "recolour", "ids": [m2.parts[0].id], "colour": 4}], dry_run=True)
    check("GATE: on a model that already leans, leaning further is TIPS_WORSE; a recolour is fine",
          not st["stable"] and worse is not None and rc.accepted)


def test_move_settles():
    s = _load("a-fox")
    ident = _highest(s.model_at())
    v, res = s.edit_parts([{"op": "move", "ids": [ident], "d": [0, 10, 0], "settle": True}])
    land = res.landed[0] if res.landed else {}
    ok = (res.accepted and land.get("settled") and land["d"][1] < 10
          and all(isinstance(x, int) for x in land["d"])
          and abs(land["origin"][0] % 10) < 1e-6 and abs(land["origin"][1] % 8) < 1e-6
          and abs(land["origin"][2] % 10) < 1e-6)
    check("SETTLE: a piece lifted into the air comes back down to where it rests", ok)


def test_settle_budget():
    from brickify import edits as E
    s = _load("a-fox")
    ident = _highest(s.model_at())
    E.GATES[0] = 0
    v, res = s.edit_parts([{"op": "move", "ids": [ident], "d": [60, 0, 0], "settle": True}])
    gates = E.GATES[0]
    check("SETTLE: the search is budgeted — at most 3 full gates, then an honest answer",
          (res.accepted or res.code in ("NO_SPOT", "FLOATING", "COLLIDES")) and gates <= 3 + 1)


def _sole_supporter(s):
    """A part whose removal would strand something: found by asking the gate."""
    for p in s.model_at().parts:
        _, r = s.edit_parts([{"op": "delete", "ids": [p.id], "cascade": False}], dry_run=True)
        if r.code == "WOULD_FALL":
            return p.id, r
    return None, None


def test_delete_cascade():
    from brickify import edits as E
    s = _load("a-fox")
    ident, r = _sole_supporter(s)
    if ident is None:
        return check("DELETE: removing a sole supporter offers to take its passengers too", False)
    ok = bool(r.culprits) and r.offer == {"cascade": True}
    v, res = s.edit_parts([{"op": "delete", "ids": [ident], "cascade": True}])
    ok = ok and res.accepted and set(r.culprits) <= set(res.removed)
    ok = ok and not E.scene(s.model_at())["loose"]
    check("DELETE: removing a sole supporter offers to take its passengers too", ok)


def test_recolour():
    s = _load("a-fox")
    m = s.model_at()
    before = s.versions[s.head].build.provenance["ldr"].splitlines()
    steps_before = len({p.step for p in m.parts})
    ids = [p.id for p in m.parts[:5]]
    v, res = s.edit_parts([{"op": "recolour", "ids": ids, "colour": 4}])
    after = s.versions[s.head].build.provenance["ldr"].splitlines()
    changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
    ok = res.accepted and len(before) == len(after) and len(changed) == 5
    for i in changed:
        a, b = before[i].split(), after[i].split()
        ok = ok and a[0] == b[0] and b[1] == "4" and a[2:] == b[2:]
    ok = ok and steps_before == len({p.step for p in s.model_at().parts})
    check("RECOLOUR: only the colour token moves; every other byte and step survives", ok)


def test_duplicate_add_ids():
    s = _load("a-fox")
    ident = _highest(s.model_at())
    v, r1 = s.edit_parts([{"op": "duplicate", "ids": [ident]}])
    v, r2 = s.edit_parts([{"op": "add", "part": "3024", "colour": 4, "on": ident}])
    v, r3 = s.edit_parts([{"op": "delete", "ids": list(r1.added), "cascade": True}])
    v, r4 = s.edit_parts([{"op": "add", "part": "3024", "colour": 4, "on": ident}])
    ok = (list(r1.added) == ["n0"] and list(r2.added) == ["n1"] and r3.accepted
          and list(r4.added) == ["n2"])
    from brickify import edits as E
    t = E.table(s.model_at())
    ok = ok and all(r["line"] == i for i, r in enumerate(t["parts"]))
    lines = {r["id"]: r["line"] for r in t["parts"]}
    ok = ok and lines["n2"] > lines[ident]
    check("IDS: new pieces mint n0, n1, n2 (never reused) and sit after their supporter", ok)


def test_rotate_snap():
    from brickify import edits as E
    s = _load("a-fox")
    m = s.model_at()
    tgt = next((p for p in m.parts if p.pid in ("3023", "3004") and E.upright(p.M)), None)
    if tgt is None:
        return check("ROTATE: a turned 1x2 lands back on the stud lattice", False)
    b0 = E.world_box(tgt, m.lib)[0]
    v, res = s.edit_parts([{"op": "rotate", "ids": [tgt.id], "quarters": 1, "settle": False}])
    if not res.accepted:
        # a rejection is a legal outcome; what must never happen is a half stud
        return check("ROTATE: a turned 1x2 lands back on the stud lattice",
                     res.code in ("COLLIDES", "FLOATING", "WOULD_FALL", "TIPS", "TIPS_WORSE"))
    after = next(p for p in s.model_at().parts if p.id == tgt.id)
    b1 = E.world_box(after, s.model_at().lib)[0]
    ok = all(abs(((b1[a] - b0[a]) % 20)) < 1e-6 for a in (0, 2))
    check("ROTATE: a turned 1x2 lands back on the stud lattice", ok)


def test_dry_run():
    s = _load("a-fox")
    ident = _highest(s.model_at())
    s.edit_parts([{"op": "recolour", "ids": [ident], "colour": 4}])
    s.undo()
    head, versions, redo = s.head, len(s.versions), list(s._redo_stack)
    v, res = s.edit_parts([{"op": "move", "ids": [_highest(s.model_at())],
                            "d": [0, 10, 0], "settle": True}], dry_run=True)
    check("DRY RUN: shows where it would land and changes nothing",
          v is None and res.accepted and res.landed
          and s.head == head and len(s.versions) == versions and s._redo_stack == redo)


def test_stale_base():
    s = _load("a-fox")
    before = s.versions[s.head].build.provenance["ldr"]
    v, res = s.edit_parts([{"op": "recolour", "ids": ["p0"], "colour": 4}], base="v99")
    check("STALE: an edit against an old version is refused, not applied",
          v is None and res.code == "STALE"
          and s.versions[s.head].build.provenance["ldr"] == before)


def test_replay_direct():
    from brickify import edits as E
    from brickify import pipeline as bp
    s = _load("a-fox")
    ident = _highest(s.model_at())
    s.edit_parts([{"op": "move", "ids": [ident], "d": [0, 10, 0], "settle": True}], text="lift it")
    s.edit_parts([{"op": "recolour", "ids": [ident], "colour": 33}])
    _, rd = s.edit_parts([{"op": "duplicate", "ids": [ident]}])
    sole, _ = _sole_supporter(s)
    if sole:
        s.edit_parts([{"op": "delete", "ids": [sole], "cascade": True}])
    s.undo()
    s.redo()
    orig = s.versions[s.head].build
    real = bp.claude

    def boom(*a, **k):
        raise AssertionError("replay must never call a model")

    bp.claude = boom
    try:
        again = s.replay()
    finally:
        bp.claude = real
    check("REPLAY: the recorded ops rebuild the model byte for byte, with no model call",
          again.provenance["ldr"] == orig.provenance["ldr"]
          and [p.id for p in again.parts] == [p.id for p in orig.parts])


PREPARSE_CASES = [
    ("make it red", "ops", "recolour"),
    ("make the orange pieces blue", "ops", "recolour"),
    ("paint these green", "reject", "NEEDS_SELECTION"),
    ("delete these", "reject", "NEEDS_SELECTION"),
    ("remove the top piece", "ops", "delete"),
    ("turn it around", "ops", "rotate"),
    ("undo", "nav", "undo"),
    ("make the ears bigger", None, None),
]


def test_preparse():
    from brickify import edits as E
    import nl_c
    s = _load("a-fox")
    t = E.table(s.model_at())
    ok = True
    for text, kind, detail in PREPARSE_CASES:
        p = nl_c.preparse(text, t, [])
        if kind is None:
            ok = ok and p is None
            continue
        if p is None or p["kind"] != kind:
            print(f"       \x1b[33m{text!r} -> {p}\x1b[0m")
            ok = False
            continue
        if kind == "ops":
            ok = ok and p["ops"][0]["op"] == detail
        elif kind == "reject":
            ok = ok and p["code"] == detail
        else:
            ok = ok and p["dir"] == detail
    sel = [t["parts"][0]["id"], t["parts"][1]["id"]]
    p = nl_c.preparse("paint these green", t, sel)
    ok = ok and p and p["kind"] == "ops" and p["ops"][0]["ids"] == sel
    p = nl_c.preparse("move these up two", t, sel)
    ok = ok and p and p["ops"][0]["d"] == [0, 2, 0]
    p = nl_c.preparse("move them left 3 studs", t, sel)
    ok = ok and p and p["ops"][0]["d"] == [-3, 0, 0]
    p = nl_c.preparse("raise it by one brick", t, sel)
    ok = ok and p and p["ops"][0]["d"] == [0, 3, 0]
    p = nl_c.preparse("turn it around", t, sel)
    ok = ok and p and p["ops"][0]["quarters"] == 2
    p = nl_c.preparse("copy this", t, sel)
    ok = ok and p and p["ops"][0]["op"] == "duplicate"
    p = nl_c.preparse("add a red 2x4 on top", t, sel)
    ok = ok and p and p["ops"][0] == {"op": "add", "part": "3001", "colour": 4, "on": None,
                                      "quarters": 0, "settle": True}
    p = nl_c.preparse("rotate the tail", t, [])
    ok = ok and (p is None or p["kind"] == "miss")
    check("NL: the offline pre-parser reads the phrases people actually type", ok)


def test_lights_blue():
    import nl_c
    s = _load("car", MODELS, ".mpd")
    v, edit = nl_c.handle(s, "make the lights blue", [], None, "auto", ask=None)
    from brickify import edits as E
    t = E.table(s.model_at())
    blue = [r for r in t["parts"] if r["colour"] == 33]
    kinds = [e["kind"] for e in edit["tape"]]
    ok = (edit["accepted"] and len(blue) == 8
          and kinds == ["edit.match", "edit.apply", "edit.gate", "edit.steps"]
          and not any("rover" in e["text"].lower() or "->" in e["text"] for e in edit["tape"]))
    check("NL: 'make the lights blue' really turns the car's eight lights blue", ok)


def test_llm_reply_guard():
    import nl_c
    from brickify import edits as E
    s = _load("a-fox")
    t = E.table(s.model_at())
    ident = t["parts"][0]["id"]
    refused = []
    for bad in (
        {"route": "direct", "ops": [{"op": "move", "target": {"ids": [ident]}, "dir": "up", "pos": [1, 2, 3]}]},
        {"route": "direct", "ops": [{"op": "move", "target": {"ids": [ident]}, "d": [1, 0, 0]}]},
        {"route": "direct", "ops": [{"op": "move", "target": {"ids": [ident]}, "dir": "up", "n": 1.5}]},
        {"route": "direct", "ops": [{"op": "move", "target": {"ids": [ident], "x": 20}, "dir": "up", "n": 1}]},
        {"route": "direct", "ops": [{"op": "recolour", "target": {"all": True}, "colour": "Zorp"}]},
        {"route": "direct", "ops": [{"op": "recolour", "target": {"ids": ["nope"]}, "colour": "Red"}]},
    ):
        try:
            nl_c.validate_reply(bad, t)
            refused.append(None)
        except nl_c.Refused as r:
            refused.append(r.code)
    ok = all(c is not None for c in refused)
    ok = ok and refused[0] == "LLM_COORDINATE" and refused[2] == "LLM_COORDINATE" and refused[3] == "LLM_COORDINATE"
    for good in (
        {"route": "direct", "say": "Making the 8 lights blue",
         "ops": [{"op": "recolour", "target": {"groups": ["g0"]}, "colour": "Blue"}]},
        {"route": "structural", "why": "bigger ears means reshaping the head"},
        {"route": "unclear", "ask": "Which ear?", "candidates": {"body": "ear_left"}},
    ):
        try:
            nl_c.validate_reply(good, t, groups=["g0", "g3"])
        except nl_c.Refused as r:
            print(f"       \x1b[33mrefused a good reply: {r.why}\x1b[0m")
            ok = False
    before = s.versions[s.head].build.provenance["ldr"]
    head = s.head

    def cheater(prompt, system):
        return json.dumps({"route": "direct", "ops": [
            {"op": "move", "target": {"ids": [ident]}, "dir": "up", "n": 1, "pos": [0, 0, 0]}]})

    v, edit = nl_c.handle(s, "shove it over there", [], None, "auto", ask=cheater)
    ok = ok and v is None and edit["code"] == "LLM_COORDINATE" and s.head == head
    ok = ok and s.versions[s.head].build.provenance["ldr"] == before
    check("NL: a reply carrying a coordinate is refused outright, twice, and nothing is committed", ok)


def test_nl_routes():
    import nl_c
    s = _load("a-fox")
    v, e1 = nl_c.handle(s, "make the ears bigger", [], None, "auto",
                        ask=lambda p, sy: '{"route":"structural","why":"reshaping the head"}')
    v, e2 = nl_c.handle(s, "change the thing", [], None, "auto",
                        ask=lambda p, sy: '{"route":"unclear","ask":"Which one?","candidates":{"body":"%s"}}'
                        % s.model_at().parts[0].body)
    v, e3 = nl_c.handle(s, "zzzz qqqq", [], None, "auto", ask=None)
    check("NL: structural on a loaded model, unclear with candidates, and an honest 'I can't'",
          e1["code"] == "STRUCTURAL_UNAVAILABLE" and not e1["accepted"]
          and e2["code"] == "AMBIGUOUS" and e2["candidates"]
          and e3["code"] == "NL_FAILED" and not e3["accepted"])


def test_tree_and_payload():
    from serialize import build_json
    from brickify import edits as E
    s = _load("a-fox")
    s.edit_parts([{"op": "recolour", "ids": ["p0"], "colour": 4}], text="make it red")
    cur = s.versions[s.head]
    fake = s._commit(s.head, {"kind": "edit_c", "text": "longer tail", "recipe": {}, "reapplied": [],
                              "dropped": []}, cur.build, cur.report, None, cur.model)
    tree = s.tree_ascii()
    bj = build_json(cur.build)
    phys = engine_c_physics(cur.build)
    check("PAYLOAD: the tree renders every op kind; provenance drops the bulky text; physics is real",
          "load a-fox" in tree and "edit_c" in tree and "recoloured" in tree
          and "ldr" not in bj["provenance"] and "lib" not in bj["provenance"]
          and phys["com"] is not None and phys["base"])


def engine_c_physics(build):
    import engine_c
    return engine_c.physics(build)


def test_reapply():
    from session import reapply_direct
    from brickify import edits as E
    s = _load("a-fox")
    base = s.model_at()
    a = _highest(base)
    _, r1 = s.edit_parts([{"op": "recolour", "ids": [a], "colour": 4}])
    step_keep = {"ops": s.versions[s.head].op["ops"], "new_ids": [], "base": base, "label": "made it red"}
    gone = [p for p in base.parts if p.id != a][0]
    step_drop = {"ops": [{"op": "recolour", "ids": [gone.id], "colour": 14}], "new_ids": [],
                 "base": base, "label": "made one yellow"}
    rebuilt = E.parse(E.write(E.Model(base.header, tuple(p for p in base.parts if p.id != gone.id),
                                      base.lib, 0)), lib=base.lib)
    model, kept, dropped = reapply_direct(rebuilt, [step_keep, step_drop])
    ok = (len(kept) == 1 and len(dropped) == 1 and dropped[0]["human"]
          and "made one yellow" in dropped[0]["human"]
          and any(p.colour == 4 for p in model.parts))
    check("REAPPLY: direct edits survive a rebuild where they can, and are named where they can't", ok)


def main_c():
    print("\n\x1b[1mpipeline C — loading and the gate\x1b[0m")
    test_c_load(); test_c_load_mpd(); test_gate_overlap(); test_gate_floating(); test_gate_tip()
    print("\n\x1b[1mpipeline C — the ops\x1b[0m")
    test_move_settles(); test_settle_budget(); test_delete_cascade(); test_recolour()
    test_duplicate_add_ids(); test_rotate_snap(); test_dry_run(); test_stale_base()
    print("\n\x1b[1mpipeline C — plain language\x1b[0m")
    test_preparse(); test_lights_blue(); test_llm_reply_guard(); test_nl_routes()
    print("\n\x1b[1mpipeline C — versions\x1b[0m")
    test_replay_direct(); test_tree_and_payload(); test_reapply()


def main():
    print("\n\x1b[1mvalidator — the law\x1b[0m")
    test_good(); test_overlap(); test_floating(); test_disconnected()
    print("\n\x1b[1minvariants\x1b[0m")
    test_no_floats_in_model(); test_determinism(); test_ldraw_roundtrip()
    test_insertion_sweep()
    print("\n\x1b[1mgenerators\x1b[0m")
    test_generator_ids_unique(); test_lenient_expand(); test_meta_parser()
    print("\n\x1b[1mphysics & arbitrary shapes\x1b[0m")
    test_physics(); test_stabilize(); test_repair_survives_bad_composition()
    test_voxel_shapes()
    print("\n\x1b[1mversion tree\x1b[0m")
    test_version_tree(); test_replay_identical()
    print("\n\x1b[1mend-to-end\x1b[0m")
    test_golden(); test_substitution_fires()
    main_c()
    print(f"\n  \x1b[1m{_n[1]}/{_n[0]} checks passed\x1b[0m\n")
    return _n[1] == _n[0]


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)
