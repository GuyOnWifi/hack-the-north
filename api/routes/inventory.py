"""The bin: read it, type into it, fix it, import into it.

Invariant 10 lives here -- the inventory grid is always editable. CV proposes rows, the human is
the authority, and no endpoint in this file can refuse an edit because a model disagreed.
"""

from __future__ import annotations

import json
import pathlib

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import engine
from ..store import Session, Store
from . import get_session, get_store

router = APIRouter(prefix="/inventory", tags=["inventory"])

SETS_DIR = pathlib.Path(__file__).resolve().parents[2] / "data" / "sets"


class ItemIn(BaseModel):
    part: str
    color: int
    qty: int = 1
    source: str = "typed"
    status: str = "confirmed"
    name: str | None = None


class ItemPatch(BaseModel):
    part: str | None = None
    color: int | None = None
    qty: int | None = None
    status: str | None = None


class InventoryIn(BaseModel):
    items: list[ItemIn] = Field(default_factory=list)
    replace: bool = True
    color_mode: str | None = None


class ImportSet(BaseModel):
    set_num: str


@router.get("")
def read_inventory(session: Session = Depends(get_session)) -> dict:
    return session.to_dict()


@router.post("")
def write_inventory(body: InventoryIn, session: Session = Depends(get_session),
                    store: Store = Depends(get_store)) -> dict:
    if body.replace:
        session.items.clear()
    for item in body.items:
        store.add_item(session, item.model_dump(exclude_none=True))
    if body.color_mode:
        session.color_mode = body.color_mode
    return session.to_dict()


@router.post("/items", status_code=201)
def add_item(body: ItemIn, session: Session = Depends(get_session),
             store: Store = Depends(get_store)) -> dict:
    return store.add_item(session, body.model_dump(exclude_none=True))


@router.patch("/items/{item_id}")
def patch_item(item_id: str, body: ItemPatch, session: Session = Depends(get_session),
               store: Store = Depends(get_store)) -> dict:
    row = store.patch_item(session, item_id, body.model_dump(exclude_none=True))
    if row is None:
        raise HTTPException(404, {"code": "NO_ITEM", "human": f"No inventory row {item_id}."})
    return row


@router.delete("/items/{item_id}")
def delete_item(item_id: str, session: Session = Depends(get_session),
                store: Store = Depends(get_store)) -> dict:
    if not store.delete_item(session, item_id):
        raise HTTPException(404, {"code": "NO_ITEM", "human": f"No inventory row {item_id}."})
    return {"deleted": item_id, "totals": session.totals()}


@router.delete("")
def clear_inventory(session: Session = Depends(get_session)) -> dict:
    session.items.clear()
    return session.to_dict()


@router.post("/import-set")
def import_set(body: ImportSet, session: Session = Depends(get_session),
               store: Store = Depends(get_store)) -> dict:
    """Import a set's parts by number.

    HONEST STUB. Set inventories come from Rebrickable, which needs an API key and a network,
    and this lane has neither guaranteed at judging time. So: a local `data/sets/<num>.json`
    (a list of {part, color, qty}) imports for real; DEMO_SAFE imports the canned fixture bin;
    anything else returns 501 with a sentence saying exactly what is missing, rather than
    pretending an empty import succeeded.
    """
    def _imported(rows: list[dict]) -> None:
        # Drop incoming ids: this session numbers its own rows, and a merge into an existing
        # bin must not be able to collide with a row the user already has.
        for r in rows:
            store.add_item(session, {k: v for k, v in r.items() if k != "id"}
                           | {"source": "set_import"})

    local = SETS_DIR / f"{body.set_num}.json"
    if local.exists():
        rows = json.loads(local.read_text())
        _imported(rows)
        return {"imported": len(rows), "source": str(local), "totals": session.totals()}

    if engine.demo_safe():
        rows = engine.load_fixture_inventory()
        _imported(rows)
        return {"imported": len(rows), "source": "fixtures",
                "human": f"DEMO_SAFE: served the canned fixture bin instead of set {body.set_num}.",
                "totals": session.totals()}

    raise HTTPException(501, {
        "code": "SET_IMPORT_UNAVAILABLE",
        "human": (f"Set import needs the Rebrickable catalogue, which this build does not ship. "
                  f"Drop a parts list at data/sets/{body.set_num}.json (a list of "
                  f"{{part, color, qty}}) and it will import, or type the rows in the grid."),
    })
