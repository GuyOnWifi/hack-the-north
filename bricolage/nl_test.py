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
    # shapes (sculpt)
    "build me a flower", "make me a heart", "a star", "build a tree",
    "make a mushroom", "a moon", "build a fish", "a smiley face",
    "make a dragon", "a cat", "a crown", "build a sword", "a dog",
    "an ice cream cone", "a christmas tree", "a pixel mario", "a red apple",
    "the letter A", "a spooky ghost", "a green frog", "a birthday cake",
    # structures (compose)
    "a house", "make me a rover", "build a truck", "a tall tower",
    "a long wall", "build a jet", "a rocket ship", "make me a robot",
    "a castle", "a little blue car", "a big wide house", "a garage",
    # awkward phrasings / edge cases
    "can you build me something like a boat", "I want a small tower please",
    "make the coolest robot ever", "surprise me", "asdfghjkl",
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
    print("\n\x1b[1mIMAGINE mode — unlimited bricks, any request must be VALID\x1b[0m")
    npass = 0
    for p in PROMPTS:
        ok, why, n, backend = check_build(p, unlimited_bin())
        npass += ok
        mark = PASS if ok else FAIL
        print(f"  {mark} {p:34} [{backend:7}] {n:3} parts  {why}")
    print(f"  \x1b[1m{npass}/{len(PROMPTS)} valid\x1b[0m")

    # SOLVE mode: a finite generic LEGO set. Big asks may honestly degrade
    # (that's fine) — what must NOT happen is a crash or a spurious invalid.
    print("\n\x1b[1mSOLVE mode — finite generic set, must COMPLETE (valid or honest)\x1b[0m")
    completed = 0
    for p in PROMPTS:
        try:
            res = build_from_prompt(p, rich_bin(), 0)
            complete = res["steps"] is not None or not res["report"].ok  # built or honestly rejected
            completed += bool(complete)
        except Exception as e:
            print(f"  {FAIL} {p:34} CRASHED: {e}")
    print(f"  \x1b[1m{completed}/{len(PROMPTS)} completed without crashing\x1b[0m")

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
