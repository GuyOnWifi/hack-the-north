"""Route modules plus the two dependencies every one of them needs.

Sessions are addressed by the `X-Session-Id` header (or a `session_id` query param) rather than
by a path segment, because the frontend holds exactly one session at a time and threading an id
through every inventory URL buys nothing. An unset header means the default session, so `curl`
and the demo both work with no ceremony.
"""

from __future__ import annotations

from fastapi import Header, HTTPException, Query, Request

from ..store import Session, Store


def get_store(request: Request) -> Store:
    return request.app.state.store


def default_session(store: Store) -> Session:
    """The session a client gets when it never asked for one. Seeded in DEMO_SAFE."""
    from .. import engine

    s = store.sessions.get("ses_default")
    if s is None:
        s = Session(id="ses_default")
        if engine.demo_safe():
            for item in engine.load_fixture_inventory():
                store.add_item(s, item)
        store.sessions[s.id] = s
    return s


def get_session(request: Request,
                x_session_id: str | None = Header(default=None),
                session_id: str | None = Query(default=None)) -> Session:
    store = get_store(request)
    sid = x_session_id or session_id
    if not sid:
        return default_session(store)
    s = store.session(sid)
    if s is None:
        raise HTTPException(404, {"code": "NO_SESSION",
                                  "human": f"No session {sid}. POST /sessions to start one."})
    return s
