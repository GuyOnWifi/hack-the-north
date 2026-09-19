"""Is this snapshot internally consistent? Disk only -- no server, no network, no core import.

WHY it deliberately re-derives the invariants instead of importing `core.validate`: the point of
a canned snapshot is that it still works when the code that produced it has moved on. A checker
that shares code with the producer cannot catch the producer drifting. So this file reads JSON
and counts, and it is the one thing in the demo package with no interesting dependencies.

    python -m demo.check demo/canned

Errors are demo-stoppers. Warnings are things to be able to say out loud -- notably a build
whose colours are substituted, which is legal (Contract 1, `color_mode: "similar"`) but which a
presenter should not be surprised by while holding the bricks.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from dataclasses import dataclass, field

# The files `api.engine` reads in DEMO_SAFE, plus the recipe an edit needs. Missing any one of
# these is not a degraded demo, it is no demo.
REQUIRED = ("inventory.json", "build.json", "report.json", "steps.json", "tape.jsonl",
            "model.ldr", "composition.json", "meta.json")

ACTORS = {"designer", "inspector", "repair", "scribe", "cataloguer"}
STATUSES = {"ok", "fail", "warn", "running"}

# Below this the model is a lump and the manual is one page. It is a warning, not an error,
# because a small snapshot that serves is still better than no snapshot at judging time.
MIN_PARTS = 12
MIN_STEPS = 3


@dataclass
class CheckResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {"ok": self.ok, "errors": list(self.errors),
                "warnings": list(self.warnings), "stats": dict(self.stats)}


def _load(path: pathlib.Path):
    return json.loads(path.read_text())


def check_snapshot(directory, *, expect_render: bool = True,
                   min_parts: int = MIN_PARTS) -> CheckResult:
    """Read a snapshot directory and report everything wrong with it."""
    d = pathlib.Path(directory)
    r = CheckResult()

    if not d.is_dir():
        r.errors.append(f"{d} does not exist. Run: python -m demo.snapshot")
        return r
    for name in REQUIRED:
        if not (d / name).exists():
            r.errors.append(f"missing {name}")
    if r.errors:
        return r

    try:
        inventory = _load(d / "inventory.json")
        build = _load(d / "build.json")
        report = _load(d / "report.json")
        steps = _load(d / "steps.json")
        meta = _load(d / "meta.json")
    except json.JSONDecodeError as exc:
        r.errors.append(f"unreadable JSON: {exc}")
        return r

    parts = build.get("parts") or []
    r.stats.update(parts=len(parts), steps=len(steps.get("steps") or []),
                   inventory_rows=len(inventory.get("items") or []),
                   prompt=meta.get("prompt"), seed=meta.get("seed"))

    # -- the build itself -------------------------------------------------
    if not parts:
        r.errors.append("the build has no parts in it")
    if not report.get("ok", False):
        r.errors.append("report.ok is false -- this snapshot failed validation: "
                        + "; ".join(e.get("human", e.get("code", "?"))
                                    for e in report.get("errors", []))[:200])
    for p in parts:
        if not all(isinstance(v, int) for v in p.get("pos", [])):
            r.errors.append(f"part {p.get('id')} has a non-integer pos (invariant 1)")
            break
        if p.get("rot") not in (0, 90, 180, 270):
            r.errors.append(f"part {p.get('id')} has rot={p.get('rot')} (invariant 1)")
            break

    # -- the steps reference only parts in the build ----------------------
    step_ids: list[str] = []
    for s in steps.get("steps") or []:
        for p in s.get("parts") or []:
            step_ids.append(p.get("id"))
    build_ids = [p.get("id") for p in parts]
    unknown = sorted(set(step_ids) - set(build_ids))
    if unknown:
        r.errors.append(f"steps reference {len(unknown)} part(s) not in the build: "
                        f"{', '.join(unknown[:5])}")
    missing = sorted(set(build_ids) - set(step_ids))
    if missing:
        r.errors.append(f"{len(missing)} build part(s) appear in no step: "
                        f"{', '.join(missing[:5])}")
    if len(step_ids) != len(set(step_ids)):
        r.errors.append("a part appears in more than one step")

    # -- the build uses only parts the bin actually has -------------------
    have: dict[tuple[str, int], int] = {}
    for item in inventory.get("items") or []:
        if item.get("status") == "unknown":          # Contract 1: excluded from the solver
            continue
        key = (str(item["part"]), int(item["color"]))
        have[key] = have.get(key, 0) + int(item.get("qty", 1))
    pooled: dict[str, int] = {}
    for (part, _c), qty in have.items():
        pooled[part] = pooled.get(part, 0) + qty

    used: dict[tuple[str, int], int] = {}
    for p in parts:
        key = (str(p["part"]), int(p["color"]))
        used[key] = used.get(key, 0) + 1
    for (part, color), n in sorted(used.items()):
        if have.get((part, color), 0) >= n:
            continue
        # A colour the bin does not have in that quantity is legal when the row said
        # `color_mode: "similar"` -- colour is our weakest stage and the contract lets the
        # solver substitute. A PART the bin does not have at all is never legal.
        if pooled.get(part, 0) >= n:
            r.warnings.append(
                f"{n}x {part} in colour {color}, but the bin has that part in other colours "
                f"(colour substitution -- legal, but say it out loud)")
        else:
            r.errors.append(f"build uses {n}x part {part} (colour {color}); the bin has "
                            f"{pooled.get(part, 0)} of that part in any colour")

    # -- the tape ---------------------------------------------------------
    tape = [json.loads(line) for line in (d / "tape.jsonl").read_text().splitlines()
            if line.strip()]
    r.stats["tape_events"] = len(tape)
    if not tape:
        r.errors.append("tape.jsonl is empty -- the agent panel will be blank on stage")
    for ev in tape:
        if ev.get("actor") not in ACTORS or ev.get("status") not in STATUSES:
            r.errors.append(f"tape event is not Contract 4 shaped: {ev}")
            break
        if not isinstance(ev.get("t"), int) or not isinstance(ev.get("text"), str):
            r.errors.append(f"tape event has a bad t/text: {ev}")
            break
    actors = {ev.get("actor") for ev in tape}
    if "inspector" not in actors:
        r.warnings.append("no inspector line in the tape -- the 0:50 beat of the script is "
                          "'the inspector rejects it', and there is nothing to point at")

    # -- the .ldr ---------------------------------------------------------
    ldr = (d / "model.ldr").read_text()
    n_refs = sum(1 for line in ldr.splitlines() if line.startswith("1 "))
    n_steps_ldr = sum(1 for line in ldr.splitlines() if line.strip() == "0 STEP")
    r.stats["ldr_part_refs"] = n_refs
    if n_refs != len(parts):
        r.errors.append(f"model.ldr has {n_refs} part refs but the build has {len(parts)}")
    if n_steps_ldr == 0:
        r.warnings.append("model.ldr has no `0 STEP` markers -- viewers will show one lump")

    # -- the manual -------------------------------------------------------
    if expect_render:
        manual = d / "manual"
        pngs = sorted((manual / "steps").glob("step_*.png")) if manual.is_dir() else []
        r.stats["step_pngs"] = len(pngs)
        if not (manual / "manual.html").exists():
            r.errors.append("manual/manual.html is missing -- there is nothing to scrub on stage")
        if len(pngs) != r.stats["steps"]:
            r.errors.append(f"{len(pngs)} step PNGs for {r.stats['steps']} steps")
        pdf = manual / "manual.pdf"
        r.stats["pdf"] = pdf.exists()
        if not pdf.exists():
            r.warnings.append("no manual.pdf -- print from manual.html in a browser instead, "
                              "and note that .gitignore excludes *.pdf from the repo")

    # -- is it worth showing? ---------------------------------------------
    if r.stats["parts"] < min_parts:
        r.warnings.append(
            f"DEGENERATE: {r.stats['parts']} parts (want >= {min_parts}). The bin is long-tail "
            f"and the allocator matches on part+colour, so almost every row is quantity one. "
            f"Re-run the snapshot once colour pooling lands.")
    if r.stats["steps"] < MIN_STEPS:
        r.warnings.append(f"only {r.stats['steps']} steps -- the manual is barely a manual")

    return r


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m demo.check", description=__doc__)
    ap.add_argument("directory", nargs="?",
                    default=str(pathlib.Path(__file__).resolve().parent / "canned"))
    ap.add_argument("--no-render", action="store_true",
                    help="do not require the rendered manual")
    ap.add_argument("--min-parts", type=int, default=MIN_PARTS)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    r = check_snapshot(a.directory, expect_render=not a.no_render, min_parts=a.min_parts)
    if a.json:
        print(json.dumps(r.to_dict(), indent=2))
    else:
        print(f"snapshot {a.directory}")
        for k, v in r.stats.items():
            print(f"  {k}: {v}")
        for w in r.warnings:
            print(f"  WARN   {w}")
        for e in r.errors:
            print(f"  ERROR  {e}")
        print("  OK" if r.ok else "  NOT USABLE")
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main())
