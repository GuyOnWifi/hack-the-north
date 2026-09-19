"""Builds: start one, watch it think, read it, edit it, undo it.

`POST /builds` returns immediately with a `build_id` and the work continues on the event loop,
because the interesting part of this system is the 25 seconds in between -- and the client is
meant to be watching `/events` during them, not staring at a pending request.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from .. import engine
from ..store import BuildRecord, Session, Store, build_to_json, steps_to_json, version_to_json
from . import get_session, get_store

router = APIRouter(prefix="/builds", tags=["builds"])

# How long an idle SSE connection waits before sending a comment line. Proxies and phone
# browsers drop a silent stream; a colon-comment costs nothing and keeps it open.
HEARTBEAT_S = 15.0


class BuildIn(BaseModel):
    prompt: str
    mode: str = "compose"
    seed: int = 41


class EditIn(BaseModel):
    instruction: str
    node_id: str | None = None


def _build(store: Store, build_id: str) -> BuildRecord:
    rec = store.build(build_id)
    if rec is None:
        raise HTTPException(404, {"code": "NO_BUILD", "human": f"No build {build_id}."})
    return rec


def _head(rec: BuildRecord):
    v = rec.tree.current()
    if v is None:
        raise HTTPException(409, {
            "code": "NOT_READY",
            "human": rec.error or "That build is still being designed. Watch /events."})
    return v


@router.post("", status_code=202)
async def start_build(body: BuildIn, request: Request,
                      idempotency_key: str | None = Header(default=None),
                      session: Session = Depends(get_session),
                      store: Store = Depends(get_store)) -> dict:
    # Double-tapping the button at the demo table must not start two builds (docs/04-loop.md §7).
    existing = store.idempotent(idempotency_key)
    if existing is not None:
        return {"build_id": existing.id, "status": existing.status, "idempotent": True}

    rec = store.create_build(session.id, body.prompt, body.mode, body.seed)
    store.remember_idempotency(idempotency_key, rec.id)
    # Hold the task on the record: a bare create_task can be garbage-collected mid-build.
    rec.task = asyncio.create_task(engine.run_build(rec, session))
    return {"build_id": rec.id, "status": rec.status}


@router.get("/{build_id}")
def read_build(build_id: str, store: Store = Depends(get_store)) -> dict:
    rec = _build(store, build_id)
    v = rec.tree.current()
    out = {
        "build_id": rec.id,
        "session_id": rec.session_id,
        "prompt": rec.prompt,
        "mode": rec.mode,
        "status": rec.status,
        "build": build_to_json(v.build) if v else None,
        "validation": v.report.to_dict() if v else None,
        "steps_ready": bool(v and v.steps_ready),
        "version": v.version if v else None,
        "can_undo": rec.tree.can_undo,
        "can_redo": rec.tree.can_redo,
        "notes": list(v.notes) if v else [],
    }
    if rec.error:
        out["human"] = rec.error          # the honest refusal, rendered verbatim by the UI
    return out


@router.get("/{build_id}/versions")
def read_versions(build_id: str, store: Store = Depends(get_store)) -> dict:
    rec = _build(store, build_id)
    return {"head": rec.tree.head,
            "versions": [version_to_json(v, rec.tree) for v in rec.tree.all()]}


@router.get("/{build_id}/validation")
def read_validation(build_id: str, store: Store = Depends(get_store)) -> dict:
    return _head(_build(store, build_id)).report.to_dict()


@router.get("/{build_id}/steps")
def read_steps(build_id: str, store: Store = Depends(get_store)) -> dict:
    v = _head(_build(store, build_id))
    return steps_to_json(v.steps)


@router.get("/{build_id}/model.ldr", response_class=PlainTextResponse)
def read_ldr(build_id: str, store: Store = Depends(get_store)) -> Response:
    v = _head(_build(store, build_id))
    return PlainTextResponse(engine.ldr_of(v), media_type="text/plain; charset=utf-8",
                             headers={"Content-Disposition":
                                      f'inline; filename="{build_id}.ldr"'})


@router.get("/{build_id}/events")
async def read_events(build_id: str, store: Store = Depends(get_store)) -> StreamingResponse:
    """Contract 4, as `text/event-stream`. Replays the tape from the top, then follows it."""
    rec = _build(store, build_id)

    async def stream():
        cursor = 0
        waiter = rec.subscribe()
        try:
            while True:
                while cursor < len(rec.events):
                    yield f"data: {json.dumps(rec.events[cursor])}\n\n"
                    cursor += 1
                if rec.done:
                    tail = {"status": rec.status, "version": rec.tree.head,
                            "human": rec.error}
                    yield f"event: done\ndata: {json.dumps(tail)}\n\n"
                    return
                waiter.clear()
                try:
                    await asyncio.wait_for(waiter.wait(), HEARTBEAT_S)
                except (TimeoutError, asyncio.TimeoutError):
                    yield ": keep-alive\n\n"
        finally:
            rec.unsubscribe(waiter)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.post("/{build_id}/edit")
async def edit_build(build_id: str, body: EditIn, session: Session = Depends(get_session),
                     store: Store = Depends(get_store)) -> dict:
    rec = _build(store, build_id)
    _head(rec)
    try:
        v = await asyncio.to_thread(engine.apply_edit, rec, session, body.node_id,
                                    body.instruction)
    except engine.EditNotUnderstood as exc:
        # 422, not 400: the request was well-formed, we just cannot do that particular thing --
        # and the sentence we return names what we can do instead.
        raise HTTPException(422, {"code": "EDIT_NOT_UNDERSTOOD", "human": exc.human,
                                  "nodes": exc.nodes}) from None
    return {"build_id": rec.id, "version": v.version, "applied": True,
            "summary": v.op.args.get("summary", ""),
            "validation": v.report.to_dict(),
            "steps_ready": v.steps_ready,
            "can_undo": rec.tree.can_undo, "can_redo": rec.tree.can_redo}


@router.post("/{build_id}/undo")
def undo(build_id: str, store: Store = Depends(get_store)) -> dict:
    rec = _build(store, build_id)
    v = rec.tree.undo()
    return _pointer(rec, v, "Nothing to undo -- this is the first version.")


@router.post("/{build_id}/redo")
def redo(build_id: str, store: Store = Depends(get_store)) -> dict:
    rec = _build(store, build_id)
    v = rec.tree.redo()
    return _pointer(rec, v, "Nothing to redo.")


def _pointer(rec: BuildRecord, v, refusal: str) -> dict:
    """Undo and redo are pointer moves, so a no-op is a fact, not an error. 200 either way."""
    if v is None:
        return {"build_id": rec.id, "applied": False, "human": refusal,
                "version": rec.tree.head,
                "can_undo": rec.tree.can_undo, "can_redo": rec.tree.can_redo}
    return {"build_id": rec.id, "applied": True, "version": v.version,
            "validation": v.report.to_dict(), "steps_ready": v.steps_ready,
            "can_undo": rec.tree.can_undo, "can_redo": rec.tree.can_redo}
