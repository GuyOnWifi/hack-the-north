"""Share the gallery between machines, through the repo.

Runs are local (they are big, and most are throwaway). The ones worth keeping
travel with the code instead: `export` copies them into `brickify/gallery/`,
slimmed to the winning model and its pictures, and `import` unpacks them into
someone else's runs folder. A shared model replays there exactly as it does
here, because a record's paths are rebuilt from its folder when it is read.

    uv run python -m brickify.share export        # the ones you starred
    uv run python -m brickify.share export --all
    uv run python -m brickify.share import        # after a git pull
    uv run python -m brickify.share list
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from .pipeline import ROOT, RUNS, record

GALLERY = ROOT / "gallery"
ART = 900  # the concept art is a reference, not a print: this is plenty
SHOT = 640


def _shrink(src: Path, dest: Path, side: int) -> Path | None:
    """Copy a picture down to `side`, so the repo carries kilobytes not
    megabytes. Concept art is photographic, so it travels as JPEG (60KB rather
    than 700KB); renders are flat and stay PNG."""
    try:
        from PIL import Image

        with Image.open(src) as im:
            im = im.convert("RGB")
            im.thumbnail((side, side))
            if dest.suffix == ".jpg":
                im.save(dest, "JPEG", quality=86, optimize=True)
            else:
                im.save(dest, "PNG", optimize=True)
        return dest
    except Exception:
        shutil.copy(src, dest)
        return dest if dest.exists() else None


def export(only_kept: bool = True) -> int:
    """Put the models worth keeping into the repo."""
    GALLERY.mkdir(exist_ok=True)
    shared = 0
    for d in sorted(RUNS.glob("*")):
        if d.name.startswith(".") or d.name == "removed" or not d.is_dir():
            continue
        r = record(d)
        if not r or (only_kept and not r.get("kept")):
            continue
        out = GALLERY / d.name
        out.mkdir(exist_ok=True)
        label = r["label"]
        # the model that won, its design, and the story of how it was made
        shutil.copy(r["ldr"], out / f"{label}.ldr")
        shutil.copy(r["brief"], out / f"brief-{label}.json")
        for name in ("tape.jsonl", "distilled.json"):
            if (d / name).exists():
                shutil.copy(d / name, out / name)
        for art in ("concept.png", "concept-side.png", "concept-back.png"):
            if (d / art).exists():
                _shrink(d / art, out / f"{Path(art).stem}.jpg", ART)
        shots = Path(r["run"]) / f"views-{label}"
        shots = shots if shots.exists() else d / f"views-r{r['round']}"
        if shots.exists():
            (out / f"views-{label}").mkdir(exist_ok=True)
            for shot in shots.glob("*.png"):
                _shrink(shot, out / f"views-{label}" / shot.name, SHOT)
        # paths are rebuilt on the machine that reads it, so don't carry mine
        (out / "result.json").write_text(json.dumps(
            {k: v for k, v in r.items() if k not in ("run", "ldr", "brief", "concept", "views")}, indent=1))
        shared += 1
        print(f"shared {d.name} ({r['parts']} parts)")
    return shared


def take() -> int:
    """Copy shared models into this machine's runs folder."""
    RUNS.mkdir(parents=True, exist_ok=True)
    taken = 0
    for d in sorted(GALLERY.glob("*")):
        if not d.is_dir() or (RUNS / d.name).exists():
            continue
        shutil.copytree(d, RUNS / d.name)
        taken += 1
        print(f"took {d.name}")
    return taken


def main():
    ap = argparse.ArgumentParser(prog="brickify.share", description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=("export", "import", "list"))
    ap.add_argument("--all", action="store_true", help="export every model, not only the ones you starred")
    a = ap.parse_args()
    if a.action == "export":
        n = export(only_kept=not a.all)
        print(f"{n} model(s) in {GALLERY.relative_to(ROOT.parent)} - commit them and your team can `import`")
    elif a.action == "import":
        print(f"{take()} model(s) added to your gallery")
    else:
        for d in sorted(GALLERY.glob("*")):
            r = record(d)
            if r:
                print(f"{d.name:44} {r.get('parts')} parts  {'(here)' if (RUNS / d.name).exists() else ''}")


if __name__ == "__main__":
    main()
