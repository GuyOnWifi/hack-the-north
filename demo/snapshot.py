"""Freeze one complete known-good run to `demo/canned/`. Regenerable with one command.

    .venv/bin/python -m demo.snapshot                      # the real bin, the demo prompt
    .venv/bin/python -m demo.snapshot --inventory fixtures/inventory.json --out demo/canned-rich
    .venv/bin/python -m demo.snapshot --no-render          # skip the PDF while iterating

WHY the REAL bin (`data/real/inventory.json`) and not a fixture: the fixture bin is a tidy pile
of round numbers, and a judge can tell. The real bin is 74 detections, 57 identified pieces,
49 part+colour combinations -- almost everything quantity one -- with amber rows a presenter can
click. It is the more convincing artifact and it is the one that finds our bugs.

WHY it runs the real pipeline instead of writing JSON by hand: a hand-written snapshot is a
fixture, and a fixture that disagrees with the code is worse than no fixture. This drives
`api.engine.run_build`, the exact coroutine the HTTP layer drives, so the canned tape is a tape
that actually happened and the canned build is one the validator actually passed. When another
lane improves the allocator, re-running this command is the whole integration step.

WHAT it deliberately does NOT do: reach the network, need an API key, or accept a build it
cannot vouch for. `DEMO_SAFE` is forced off here (we are *making* the canned run, not serving
it) but the LLM seam degrades to the offline planner with no key, and `demo.netguard` is
installed so a snapshot can never quietly depend on a service that will be gone at judging.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from demo import netguard                                            # noqa: E402
from demo.check import check_snapshot                                # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "demo" / "canned"
DEFAULT_INVENTORY = ROOT / "data" / "real" / "inventory.json"
DEFAULT_PROMPT = "build me a rover"
DEFAULT_SEED = 41

# The canned session is addressed by a stable id, not a uuid: invariant 6 says the same inputs
# and seed give identical output, and a fresh uuid in every snapshot would break the diff that
# proves it.
CANNED_SESSION = "ses_canned"
CANNED_BUILD = "bld_canned"


@dataclass(frozen=True, slots=True)
class Frozen:
    """What one run produced, before it is written anywhere."""

    items: list[dict]
    build: dict
    report: dict
    steps: dict
    ldr: str
    tape: list[dict]
    composition: dict
    notes: tuple[str, ...]
    status: str
    human: str | None
    ms: int


# ---------------------------------------------------------------- the run


def _load_items(path: pathlib.Path) -> list[dict]:
    raw = json.loads(path.read_text())
    items = raw.get("items") if isinstance(raw, dict) else raw
    if not items:
        raise SystemExit(f"{path} has no items -- nothing to snapshot.")
    return [dict(i) for i in items]


def run_once(items: list[dict], prompt: str, seed: int) -> Frozen:
    """Drive the real engine coroutine over a real Store session. No HTTP, no network."""
    os.environ["DEMO_SAFE"] = "0"          # we are producing the canned run, not replaying it
    from api import engine                 # imported late: the env var above is read per call
    from api.store import Store, build_to_json, steps_to_json

    store = Store()
    session = store.create_session(items)
    session.id = CANNED_SESSION
    store.sessions = {CANNED_SESSION: session}

    rec = store.create_build(session.id, prompt, "compose", seed)
    rec.id = CANNED_BUILD
    t0 = time.monotonic()
    asyncio.run(engine.run_build(rec, session))
    ms = int((time.monotonic() - t0) * 1000)

    version = rec.tree.current()
    if version is None:
        raise SystemExit(f"the engine produced no version: {rec.error or rec.status}")

    return Frozen(
        items=[dict(i) for i in session.items],
        build=build_to_json(version.build),
        report=version.report.to_dict(),
        steps=steps_to_json(version.steps),
        ldr=engine.ldr_of(version),
        tape=[dict(e) for e in rec.events],
        composition=dict((version.op.args or {}).get("composition") or {}),
        notes=tuple(version.notes),
        status=rec.status,
        human=rec.error,
        ms=ms,
    )


# ---------------------------------------------------------------- writing it down


def _git_rev() -> str:
    """The commit this snapshot came from, so a stale canned run is identifiable, not mysterious."""
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or "uncommitted"
    except Exception:
        return "unknown"


def _write_json(path: pathlib.Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2) + "\n")


def write(frozen: Frozen, out: pathlib.Path, *, source: pathlib.Path) -> None:
    out.mkdir(parents=True, exist_ok=True)

    # The filenames are the ones `api.engine` reads in DEMO_SAFE (`load_fixture_*`). That is
    # why this directory can be swapped in for `fixtures/` with a single attribute assignment
    # in demo/serve.py instead of a branch inside the API.
    _write_json(out / "inventory.json", {
        "session_id": CANNED_SESSION,
        "items": frozen.items,
        "totals": {"pieces": sum(int(i.get("qty", 1)) for i in frozen.items),
                   "distinct": len(frozen.items),
                   "unknown": sum(int(i.get("qty", 1)) for i in frozen.items
                                  if i.get("status") == "unknown")},
        "source": str(source.relative_to(ROOT)) if source.is_relative_to(ROOT) else str(source),
    })
    _write_json(out / "build.json", frozen.build)
    _write_json(out / "report.json", frozen.report)
    _write_json(out / "steps.json", frozen.steps)
    _write_json(out / "composition.json", frozen.composition)
    (out / "model.ldr").write_text(frozen.ldr)
    (out / "tape.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in frozen.tape))


def render_manual(out: pathlib.Path, *, width: int, height: int) -> dict:
    """Step PNGs + HTML + PDF into `<out>/manual`. Never raises: no PDF is not no manual."""
    from render import RenderOpts, load_build, load_steps, make_manual

    target = out / "manual"
    if target.exists():
        shutil.rmtree(target)                        # a stale step_08.png is a wrong manual
    build = load_build(out / "build.json")
    steps = load_steps(out / "steps.json")
    res = make_manual(build, steps, target, RenderOpts(width=width, height=height))
    return {"backend": res.steps.backend, "pdf_backend": res.pdf.backend,
            "pdf": res.pdf.ok, "step_pngs": len(res.steps.images),
            "notes": list(res.notes)}


# ---------------------------------------------------------------- cli


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m demo.snapshot", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inventory", default=str(DEFAULT_INVENTORY))
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--no-render", action="store_true", help="skip the manual (fast)")
    ap.add_argument("--width", type=int, default=1200)
    ap.add_argument("--height", type=int, default=900)
    ap.add_argument("--min-parts", type=int, default=12)
    ap.add_argument("--allow-degenerate", action="store_true",
                    help="write and exit 0 even when the build is too small to show")
    ap.add_argument("--allow-network", action="store_true",
                    help="do not install the offline guard (only to test a live provider)")
    a = ap.parse_args(argv)

    if not a.allow_network:
        netguard.install()

    source = pathlib.Path(a.inventory).resolve()
    out = pathlib.Path(a.out).resolve()
    items = _load_items(source)

    print(f"bin     {source}")
    print(f"        {len(items)} rows, {sum(int(i.get('qty', 1)) for i in items)} pieces")
    print(f"ask     {a.prompt!r}  seed={a.seed}")

    frozen = run_once(items, a.prompt, a.seed)
    print(f"run     {frozen.status} in {frozen.ms} ms, "
          f"{len(frozen.build['parts'])} parts, {frozen.steps['total']} steps, "
          f"{len(frozen.tape)} tape events")
    for n in frozen.notes:
        print(f"        note: {n}")

    write(frozen, out, source=source)
    render = {"skipped": True}
    if not a.no_render:
        render = render_manual(out, width=a.width, height=a.height)
        print(f"manual  {render['step_pngs']} step PNGs via {render['backend']}, "
              f"pdf={render['pdf']} via {render['pdf_backend']}")
        for n in render.get("notes", []):
            print(f"        note: {n}")

    _write_json(out / "meta.json", {
        "prompt": a.prompt,
        "seed": a.seed,
        "inventory_source": str(source.relative_to(ROOT))
        if source.is_relative_to(ROOT) else str(source),
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "git": _git_rev(),
        "python": sys.version.split()[0],
        "engine_status": frozen.status,
        "engine_human": frozen.human,
        "engine_ms": frozen.ms,
        "notes": list(frozen.notes),
        "render": render,
        "counts": {"parts": len(frozen.build["parts"]), "steps": frozen.steps["total"],
                   "tape_events": len(frozen.tape), "inventory_rows": len(frozen.items)},
    })

    result = check_snapshot(out, expect_render=not a.no_render, min_parts=a.min_parts)
    # The verdict is written into the snapshot as well as printed: at judging time nobody reads
    # the terminal scrollback from six hours ago, and `demo/canned/meta.json` is the thing the
    # checklist tells a presenter to open.
    meta = json.loads((out / "meta.json").read_text())
    meta["check"] = result.to_dict()
    _write_json(out / "meta.json", meta)

    print(f"wrote   {out}")
    for w in result.warnings:
        print(f"  WARN  {w}")
    for e in result.errors:
        print(f"  ERROR {e}")

    if result.errors:
        print("\nThis snapshot is NOT usable. Fix the errors above and re-run.")
        return 1
    if any(w.startswith("DEGENERATE") for w in result.warnings) and not a.allow_degenerate:
        print("\nWritten, but too small to demo. Re-run with --allow-degenerate to accept it,\n"
              "or with --inventory fixtures/inventory.json for a bin that is not long-tail.")
        return 2
    print("\nDemo-safe snapshot ready.  scripts/demo_safe.sh")
    return 0


if __name__ == "__main__":
    sys.exit(main())
