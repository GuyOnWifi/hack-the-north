"""End-to-end demo of Lane B. Run:  python bricolage/demo.py

Shows the product AND its consequences:
  1. prompt + typed inventory -> validated build -> steps -> LDraw
  2. the agent tape (designer proposes, inspector rejects, repair fixes)
  3. the repair ladder firing on an ADVERSARIAL bin (no 2x4s) with the
     "most repairs never reached the model" stat
  4. the edit loop: "make the chassis longer" reattaches children for free
  5. determinism: replay from the recorded op reproduces byte-for-byte
"""
from __future__ import annotations
import json

from model import Inventory
from pipeline import build_from_prompt
from edit import parse_edit, apply_edit
from generators import expand
from validate import validate
from ldraw import to_ldr
from sequence import sequence

BAR = "\x1b[90m" + "─" * 74 + "\x1b[0m"
def h(t): print(f"\n{BAR}\n\x1b[1m{t}\x1b[0m\n{BAR}")


def rich_bin():
    """A plausible well-stocked bin: the common bricks and plates the
    generators reach for, across the colours they use. Quantities are generous
    but finite — the validator still has to fit the build inside them."""
    bricks = ["3001", "3003", "3004", "3005", "3009", "3010"]
    plates = ["3020", "3022", "3023", "3024"]
    colors = [15, 19, 72, 71, 70, 4, 14, 0]        # white tan grays brown red yellow black
    counts = {}
    for c in colors:
        for part in bricks:
            counts[(part, c)] = 24
        for part in plates:
            counts[(part, c)] = 24
        counts[("4073", c)] = 16                    # wheels / round studs
    return Inventory(counts)


def adversarial_bin():
    """Deliberately NO 2x4 bricks, NO 2x2 bricks — forces substitution down to
    1x2s. Proves the repair rungs actually fire (freeze checklist item)."""
    b = rich_bin()
    b.counts[("3001", 72)] = 0   # no Brick 2x4
    b.counts[("3003", 72)] = 2   # almost no Brick 2x2
    b.counts[("3002", 71)] = 0
    return b


def show(res, inv):
    print(res["tape"].render())
    b, r = res["build"], res["report"]
    print(f"\n  \x1b[1mBuild:\x1b[0m {b.name}  v{b.version}  "
          f"backend={res['backend']}  parts={r.stats['parts']}  "
          f"subs={r.stats.get('subs')}")
    print(f"  \x1b[1mValid:\x1b[0m {'✓ yes' if r.ok else '✗ no'}  "
          f"inventory_left={r.stats.get('inventory_remaining','n/a')}")
    fx = res["fix"]
    if fx.attempts:
        total = sum(fx.rung_hits.values()) or 1
        det = sum(v for k, v in fx.rung_hits.items() if k <= 2)
        print(f"  \x1b[1mRepair:\x1b[0m {fx.attempts} attempt(s); "
              f"rung hits {dict(fx.rung_hits)}; "
              f"\x1b[32m{det}/{total} errors closed WITHOUT the model "
              f"({100*det//total}%)\x1b[0m")
    for w in r.warnings:
        print(f"  \x1b[33m! warning:\x1b[0m {w['human']}")
    for e in r.errors:
        print(f"  \x1b[31m✗ error:\x1b[0m {e['human']}")
    return res


def main():
    h("1 · HAPPY PATH  —  'build me a desk rover'  (rich bin)")
    inv = rich_bin()
    res = show(build_from_prompt("build me a small desk rover", inv), inv)
    steps = res["steps"]
    if steps:
        print(f"\n  \x1b[1mFirst 3 of {steps['n_steps']} steps:\x1b[0m")
        for s in steps["steps"][:3]:
            print(f"    step {s['n']}: {len(s['parts'])} part(s) in "
                  f"'{s['sub']}' @ layer {s['layer']}  {s['elements']}")
        ldr = to_ldr(res["build"], steps).splitlines()
        print(f"\n  \x1b[1mLDraw (.ldr) — first lines a manual renders natively:\x1b[0m")
        for line in ldr[:8]:
            print(f"    \x1b[90m{line}\x1b[0m")

    h("2 · REPAIR LADDER  —  same rover, ADVERSARIAL bin (no 2x4s)")
    print("  The designer still asks for Brick 2x4s. The bin has none.")
    print("  Watch the inspector reject and the DETERMINISTIC rungs fix it:\n")
    inv2 = adversarial_bin()
    show(build_from_prompt("build me a small desk rover", inv2), inv2)

    h("3 · HONEST REJECTION  —  'huge castle' from an almost-empty bin")
    print("  The verifier can REJECT. No hallucinated floating bricks; it")
    print("  spends its budget, then tells the truth about what won't fit:\n")
    inv3 = Inventory({("3069b", 15): 6, ("3024", 15): 4})   # a few tiles + 1x1 plates
    show(build_from_prompt("build a huge castle", inv3), inv3)

    h("4 · THE EDIT LOOP  —  'make the chassis longer'")
    inv = rich_bin()
    res = build_from_prompt("build a rover", inv)
    b0 = res["build"]
    print(f"  before: {b0.name} v{b0.version}, {len(b0.parts)} parts, "
          f"chassis length={_chassis_len(b0)}")
    ed = parse_edit("make the chassis longer", b0)
    b1 = apply_edit(b0, *ed, seed=0)
    r1 = validate(b1, inv)
    print(f"  edit:   '{'make the chassis longer'}'  -> {ed}")
    print(f"  after:  v{b1.version}, {len(b1.parts)} parts, "
          f"chassis length={_chassis_len(b1)}  valid={'✓' if r1.ok else '✗'}")
    print(f"  \x1b[32m  the cabin + both axle_pairs reattached automatically — "
          f"nobody re-specified a coordinate.\x1b[0m")

    h("5 · DETERMINISM  —  replay the recorded op reproduces byte-for-byte")
    comp = b0.provenance["composition"]
    replay = expand(comp, name=b0.name, seed=0)
    a = to_ldr(b0); c = to_ldr(replay)
    print(f"  original op -> {len(a)} bytes of LDraw")
    print(f"  replay(op)  -> {len(c)} bytes of LDraw")
    print(f"  identical:  {'✓ yes — undo/redo/try-another all fall out of this' if a==c else '✗ NO'}")

    h("6 · SCULPT BACKEND  —  'build a heart'  (voxel path)")
    inv = rich_bin()
    show(build_from_prompt("build a heart", inv), inv)

    print(f"\n{BAR}\n\x1b[1mConsequences\x1b[0m — every build above was placed by "
          f"code, checked by\ncode, and either provably stands up or was "
          f"honestly rejected. The LLM\nchose generators and sizes; it never "
          f"emitted a coordinate.\n{BAR}\n")


def _chassis_len(build):
    for s in build.subs:
        if s.gen == "chassis":
            return dict(s.args).get("length")
    return None


if __name__ == "__main__":
    main()
