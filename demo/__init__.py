"""The demo package: everything that has to work when the conference wifi dies.

Four small modules, each runnable on its own:

    python -m demo.snapshot     freeze a known-good run to demo/canned/
    python -m demo.check        prove a snapshot is internally consistent, disk only
    python -m demo.serve        (as an ASGI app) serve that snapshot with DEMO_SAFE=1
    python -m demo.verify       hit every endpoint of a running server and score it

`scripts/demo_safe.sh` is the one command that runs all four in the right order.

Nothing in here is imported by `core/`, `api/` or `render/`. The dependency arrow points one
way, so the demo package can monkeypatch the app it serves (see `demo/serve.py`) without any
other lane carrying a `if demo:` branch.
"""

from __future__ import annotations

import pathlib

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
CANNED = HERE / "canned"

__all__ = ["HERE", "ROOT", "CANNED"]
