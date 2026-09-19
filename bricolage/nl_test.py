"""Natural-language sweep: does ANY request complete into a valid, connected,
stable, sequenced build? Runs against IMAGINE mode (unlimited bricks) so shape
design isn't masked by inventory. Also checks edits (recolour, resize).

  python bricolage/nl_test.py           # mock designer (fast, offline)
  PROVIDER=claude_cli python .../nl_test.py   # real LLM + vision (slow)
"""
from __future__ import annotations
import stability
from demo import unlimited_bin, rich_bin
from pipeline import build_from_prompt
from session import Session

PROMPTS = [
    "build me a flower", "make me a heart", "a star", "build a tree",
    "make a mushroom", "a moon", "build a fish", "a smiley face", "a house",
    "make me a rover", "build a truck", "a tall tower", "a long wall",
    "build a jet", "make a dragon", "a cat", "a rocket ship", "a crown",
    "build a sword", "make me a robot", "a castle", "a dog",
]
PASS, FAIL = "\x1b[32m✓\x1b[0m", "\x1b[31m✗\x1b[0m"


def check_build(prompt, inv):
    res = build_from_prompt(prompt, inv, 0)
    b, rep = res["build"], res["report"]
    phys = stability.report(b.parts)
    ok = rep.ok and res["steps"] and phys["stable"] and len(b.parts) >= 3
    why = ""
    if not ok:
        if not rep.ok:
            why = "invalid: " + ",".join(e["code"] for e in rep.errors[:2])
        elif not phys["stable"]:
            why = "unstable"
        elif not res["steps"]:
            why = "unsequenced"
        else:
            why = f"only {len(b.parts)} parts"
    return ok, why, len(b.parts), res["backend"]


def main():
    inv = unlimited_bin()
    print("\n\x1b[1mIMAGINE mode — unlimited bricks, any request\x1b[0m")
    npass = 0
    for p in PROMPTS:
        ok, why, n, backend = check_build(p, inv)
        npass += ok
        print(f"  {PASS if ok else FAIL} {p:22} [{backend:7}] {n:3} parts  {why}")
    print(f"  \x1b[1m{npass}/{len(PROMPTS)} complete\x1b[0m")

    print("\n\x1b[1mEDITS — recolour & resize\x1b[0m")
    edits = 0
    s = Session(unlimited_bin())
    s.build("make me a flower")
    for text in ["make the flower orange", "make it blue", "make it green"]:
        v = s.edit(text)
        from collections import Counter
        cols = Counter(pp.color for pp in v.build.parts if pp.sub != "base")
        top = cols.most_common(1)[0][0] if cols else None
        ok = v.report.ok
        edits += ok
        print(f"  {PASS if ok else FAIL} '{text:24}' -> valid={v.report.ok}, "
              f"dominant colour code now {top}")
    s2 = Session(rich_bin())
    s2.build("build a rover")
    v = s2.edit("make the chassis longer")
    print(f"  {PASS if v.report.ok else FAIL} 'make the chassis longer'  -> valid={v.report.ok}")
    edits += v.report.ok

    print(f"\n  \x1b[1m{npass}/{len(PROMPTS)} builds, {edits}/4 edits\x1b[0m\n")
    return npass == len(PROMPTS)


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)
