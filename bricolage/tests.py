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
    from demo import adversarial_bin
    res = build_from_prompt("build a rover", adversarial_bin(), seed=0)
    used_sub = res["fix"].rung_hits.get(2, 0) > 0
    check("REPAIR: adversarial bin (no 2x4s) forces the substitution rung",
          used_sub and res["report"].ok)


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
    print(f"\n  \x1b[1m{_n[1]}/{_n[0]} checks passed\x1b[0m\n")
    return _n[1] == _n[0]


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)
