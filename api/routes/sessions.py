"""POST /sessions -- where a user's bin starts."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import engine
from ..store import Store
from . import get_store

router = APIRouter(tags=["sessions"])


class NewSession(BaseModel):
    items: list[dict] = Field(default_factory=list)


@router.post("/sessions", status_code=201)
def create_session(body: NewSession | None = None, store: Store = Depends(get_store)) -> dict:
    items = list(body.items) if body else []
    # DEMO_SAFE hands every new session the canned bin, so the demo never depends on a photo
    # having been taken, a camera working, or anyone having typed a row.
    if not items and engine.demo_safe():
        items = engine.load_fixture_inventory()
    s = store.create_session(items)
    return {"session_id": s.id, "totals": s.totals(), "demo_safe": engine.demo_safe()}


@router.get("/sessions/{session_id}")
def read_session(session_id: str, store: Store = Depends(get_store)) -> dict:
    s = store.session(session_id)
    if s is None:
        raise HTTPException(404, {"code": "NO_SESSION", "human": f"No session {session_id}."})
    return s.to_dict()
