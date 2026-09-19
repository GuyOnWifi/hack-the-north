"""The FastAPI app.

    .venv/bin/python -m uvicorn api.main:app --reload --port 8000
    DEMO_SAFE=1 .venv/bin/python -m uvicorn api.main:app --port 8000   # no network, no LLM

`core/` stays framework-free; this module is the only place that knows what HTTP is. State lives
on `app.state.store`, created per app instance rather than as a module global, so a test can hold
two independent servers and the next lane can hold one per worker.
"""

from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import engine
from .routes import builds, inventory, sessions
from .store import Store


def create_app() -> FastAPI:
    app = FastAPI(title="Bricolage", version="0.1.0",
                  description="Photo of a LEGO pile -> a buildable model -> a real manual.")
    app.state.store = Store()

    # The frontend is a separate origin in dev and a phone on the conference wifi at judging.
    # Locking CORS down would cost demo time and protect nothing: there is no auth and no
    # user data here, just bricks.
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                       allow_headers=["*"], expose_headers=["*"])

    app.include_router(sessions.router)
    app.include_router(inventory.router)
    app.include_router(builds.router)

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        from core.generators import GENERATORS
        return {
            "ok": True,
            "demo_safe": engine.demo_safe(),
            "llm": engine._llm_module() is not None,
            "generators": sorted(GENERATORS),
            "sessions": len(app.state.store.sessions),
            "builds": len(app.state.store.builds),
        }

    return app


app = create_app()


if __name__ == "__main__":           # pragma: no cover -- convenience only
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT", "8000")))
