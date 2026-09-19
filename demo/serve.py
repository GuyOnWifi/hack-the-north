"""The ASGI app for judging day: the real API, pointed at a canned snapshot, network off.

    DEMO_CANNED=demo/canned .venv/bin/python -m uvicorn demo.serve:app --port 8000

WHY this module exists instead of a `DEMO_CANNED` branch inside `api/`: `api.engine` already has
exactly one demo-safe path and it reads its files from `engine.FIXTURES`. Re-pointing that one
attribute is the whole integration. The API lane keeps a single code path to reason about, this
lane keeps the panic button, and nothing in `api/` has to know that `demo/` exists.

What it changes, and nothing else:
  * `DEMO_SAFE=1`, forced -- not defaulted. A stale `DEMO_SAFE=0` in a shell profile is exactly
    the kind of thing that eats a demo slot.
  * `engine.FIXTURES` -> the snapshot directory, so sessions, builds, steps, tape and .ldr all
    come off that disk.
  * `engine.DEMO_COMPOSITION` -> the recipe that actually produced this snapshot, so the 2:15
    beat ("make the chassis longer") regenerates the right subtree instead of the fixture's.
  * mounts the snapshot read-only at `/demo`, so the manual, the PDF and the step PNGs are
    reachable from the browser with no file:// paths and no second server.
"""

from __future__ import annotations

import json
import os
import pathlib

from fastapi.staticfiles import StaticFiles

from demo import netguard

ROOT = pathlib.Path(__file__).resolve().parents[1]
CANNED = pathlib.Path(os.getenv("DEMO_CANNED") or (ROOT / "demo" / "canned")).resolve()

# Forced, not defaulted: this module IS demo-safe mode. Setting it before `api` is imported
# also means the lazy LLM import in `api.engine._llm_module` never happens.
os.environ["DEMO_SAFE"] = "1"
os.environ.setdefault("BRICOLAGE_NO_LLM", "1")

if os.getenv("BRICOLAGE_NETGUARD", "1").strip() not in ("0", "false", "no", "off"):
    netguard.install()

from api import engine                                              # noqa: E402
from api.main import create_app                                     # noqa: E402

engine.FIXTURES = CANNED

_composition = CANNED / "composition.json"
if _composition.exists():
    recipe = json.loads(_composition.read_text())
    if recipe.get("nodes"):
        engine.DEMO_COMPOSITION = recipe

app = create_app()


@app.get("/demo/snapshot", tags=["meta"])
def snapshot_meta() -> dict:
    """What is loaded right now. The first thing to check at the demo table."""
    meta_path = CANNED / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    return {
        "canned": str(CANNED),
        "exists": CANNED.is_dir(),
        "netguard": netguard.installed(),
        "meta": meta,
    }


if CANNED.is_dir():
    # Mounted after the route above so `/demo/snapshot` still resolves. Read-only by
    # construction -- StaticFiles has no write path.
    app.mount("/demo", StaticFiles(directory=str(CANNED)), name="canned")
