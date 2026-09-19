"""Server state: sessions, inventories, and the version tree from docs/04-loop.md §0.

WHY a tree and not a list of builds: undo, redo and "try another" then stop being three features
and become one pointer move. A `Version` is immutable and always carries the `Report` that was
computed for *that* build -- there is no way to store a build nobody validated, which is
invariant 2 enforced by the type rather than by discipline.

Everything is in memory. That is a deliberate hackathon call, not an oversight: the whole of it
goes through the `Store` class, so the day this needs Postgres it is one class to reimplement
(`versions` becomes a JSONB table, `sessions` a row each) and no route changes.
"""

from __future__ import annotations

import asyncio
import itertools
import time
import uuid
from dataclasses import dataclass, field
from typing import Iterable

from core.model import Build, Inventory, Placed
from core.validate import Report

# ---------------------------------------------------------------- ops and cost


@dataclass(frozen=True, slots=True)
class Op:
    """What produced a version. Serializable and replayable (docs/04-loop.md §0 rule 4)."""

    kind: str                       # generate | edit | recolor | delete_node | add_node | import
    args: dict = field(default_factory=dict)
    seed: int = 0
    model: str | None = None
    prompt_hash: str | None = None

    def to_dict(self) -> dict:
        return {"kind": self.kind, "args": self.args, "seed": self.seed,
                "model": self.model, "prompt_hash": self.prompt_hash}


@dataclass(frozen=True, slots=True)
class Cost:
    tokens_in: int = 0
    tokens_out: int = 0
    ms: int = 0
    llm_calls: int = 0

    def to_dict(self) -> dict:
        return {"tokens_in": self.tokens_in, "tokens_out": self.tokens_out,
                "ms": self.ms, "llm_calls": self.llm_calls}


@dataclass(frozen=True, slots=True)
class Version:
    build_id: str
    version: int
    build: Build
    report: Report
    op: Op
    parent: int | None
    cost: Cost = Cost()
    steps: tuple[tuple[Placed, ...], ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def steps_ready(self) -> bool:
        return bool(self.steps)


class VersionTree:
    """Append-only set of versions plus a head pointer. Undo/redo move the pointer."""

    def __init__(self, build_id: str) -> None:
        self.build_id = build_id
        self._versions: dict[int, Version] = {}
        self._seq = itertools.count(1)
        self.head: int | None = None
        self._redo: list[int] = []      # versions we undid past, newest last

    def commit(self, build: Build, report: Report, op: Op, *,
               steps: Iterable[Iterable[Placed]] = (), cost: Cost = Cost(),
               notes: Iterable[str] = ()) -> Version:
        n = next(self._seq)
        v = Version(self.build_id, n, build, report, op, self.head, cost,
                    tuple(tuple(g) for g in steps), tuple(notes))
        self._versions[n] = v
        self.head = n
        self._redo.clear()              # a new branch invalidates the redo path
        return v

    def get(self, n: int) -> Version | None:
        return self._versions.get(n)

    def current(self) -> Version | None:
        return self._versions.get(self.head) if self.head is not None else None

    @property
    def can_undo(self) -> bool:
        cur = self.current()
        return cur is not None and cur.parent is not None

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> Version | None:
        cur = self.current()
        if cur is None or cur.parent is None:
            return None
        self._redo.append(cur.version)
        self.head = cur.parent
        return self.current()

    def redo(self) -> Version | None:
        if not self._redo:
            return None
        self.head = self._redo.pop()
        return self.current()

    def all(self) -> list[Version]:
        return [self._versions[k] for k in sorted(self._versions)]


# ---------------------------------------------------------------- build jobs


class BuildRecord:
    """One build request: its version tree and its agent tape.

    The tape is kept in full rather than streamed-and-dropped so a client that connects late (or
    reconnects, or is a judge who wants to scroll back) sees the whole run. Contract 4 events are
    plain dicts; we never invent one -- if a rung did not fire, it does not appear.
    """

    def __init__(self, build_id: str, session_id: str, prompt: str, mode: str, seed: int) -> None:
        self.id = build_id
        self.session_id = session_id
        self.prompt = prompt
        self.mode = mode
        self.seed = seed
        self.status = "running"          # running | ok | failed
        self.tree = VersionTree(build_id)
        self.events: list[dict] = []
        self.error: str | None = None
        self.started = time.monotonic()
        self._waiters: list[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = []

    # -- tape ------------------------------------------------------
    def emit(self, actor: str, kind: str, text: str, *, status: str = "ok",
             ms: int | None = None, tokens: int | None = None) -> dict:
        ev = {"t": int((time.monotonic() - self.started) * 1000),
              "actor": actor, "kind": kind, "text": text, "status": status}
        if ms is not None:
            ev["ms"] = ms
        if tokens is not None:
            ev["tokens"] = tokens
        self.events.append(ev)
        self._wake()
        return ev

    def replay(self, events: Iterable[dict]) -> None:
        """Adopt a canned tape verbatim (DEMO_SAFE serves fixtures/tape.jsonl)."""
        self.events.extend(dict(e) for e in events)
        self._wake()

    def finish(self, status: str, error: str | None = None) -> None:
        self.status = status
        self.error = error
        self._wake()

    @property
    def done(self) -> bool:
        return self.status != "running"

    def _wake(self) -> None:
        """Wake every SSE stream. Safe to call from a worker thread, which is why the loop is
        stored alongside the event -- `asyncio.Event.set()` off-loop is a silent no-op at best."""
        try:
            here = asyncio.get_running_loop()
        except RuntimeError:
            here = None
        for loop, ev in list(self._waiters):
            if loop is here:
                ev.set()
                continue
            try:
                loop.call_soon_threadsafe(ev.set)
            except RuntimeError:                      # the stream's loop is gone; so is the client
                pass

    def subscribe(self) -> asyncio.Event:
        ev = asyncio.Event()
        self._waiters.append((asyncio.get_running_loop(), ev))
        return ev

    def unsubscribe(self, ev: asyncio.Event) -> None:
        self._waiters[:] = [(l, e) for l, e in self._waiters if e is not ev]


# ---------------------------------------------------------------- sessions


def _now() -> float:
    return time.time()


@dataclass
class Session:
    id: str
    items: list[dict] = field(default_factory=list)
    created: float = field(default_factory=_now)
    color_mode: str = "similar"        # exact | similar | ignore (Contract 1)
    _seq: itertools.count = field(default_factory=lambda: itertools.count(1))

    def new_item_id(self) -> str:
        return f"inv_{next(self._seq):03d}"

    def to_dict(self) -> dict:
        return {"session_id": self.id, "items": self.items,
                "color_mode": self.color_mode, "totals": self.totals()}

    def totals(self) -> dict:
        pieces = sum(int(i.get("qty", 0)) for i in self.items)
        unknown = sum(int(i.get("qty", 0)) for i in self.items
                      if i.get("status") == "unknown")
        return {"pieces": pieces, "distinct": len(self.items), "unknown": unknown}

    def inventory(self) -> Inventory:
        """Core `Inventory` for the solver. `status: unknown` rows are excluded (Contract 1)."""
        return Inventory.from_pairs(
            (str(i["part"]), int(i["color"]), int(i.get("qty", 0)))
            for i in self.items if i.get("status") != "unknown"
        )


class Store:
    """The only thing that holds mutable server state. Swap this for Postgres, change nothing else."""

    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}
        self.builds: dict[str, BuildRecord] = {}
        self._idempotency: dict[str, str] = {}      # Idempotency-Key -> build_id

    # -- sessions --------------------------------------------------
    def create_session(self, items: Iterable[dict] = ()) -> Session:
        s = Session(id=f"ses_{uuid.uuid4().hex[:10]}")
        for item in items:
            self.add_item(s, dict(item))
        self.sessions[s.id] = s
        return s

    def session(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

    # -- inventory -------------------------------------------------
    def add_item(self, session: Session, item: dict) -> dict:
        item = dict(item)
        item.setdefault("id", session.new_item_id())
        item.setdefault("source", "typed")
        item.setdefault("status", "confirmed")
        item["part"] = str(item["part"])
        item["color"] = int(item["color"])
        item["qty"] = int(item.get("qty", 1))
        # Same element twice is a quantity change, not a duplicate row: the grid is the user's
        # data and two rows for "red 2x4" is the kind of mess they came here to escape.
        for row in session.items:
            if row["part"] == item["part"] and row["color"] == item["color"]:
                row["qty"] += item["qty"]
                return row
        session.items.append(item)
        return item

    def patch_item(self, session: Session, item_id: str, patch: dict) -> dict | None:
        for row in session.items:
            if row["id"] == item_id:
                for k, v in patch.items():
                    if v is None or k == "id":
                        continue
                    row[k] = int(v) if k in ("qty", "color") else v
                return row
        return None

    def delete_item(self, session: Session, item_id: str) -> bool:
        before = len(session.items)
        session.items[:] = [r for r in session.items if r["id"] != item_id]
        return len(session.items) != before

    # -- builds ----------------------------------------------------
    def create_build(self, session_id: str, prompt: str, mode: str, seed: int) -> BuildRecord:
        rec = BuildRecord(f"bld_{uuid.uuid4().hex[:10]}", session_id, prompt, mode, seed)
        self.builds[rec.id] = rec
        return rec

    def build(self, build_id: str) -> BuildRecord | None:
        return self.builds.get(build_id)

    def idempotent(self, key: str | None) -> BuildRecord | None:
        if not key:
            return None
        bid = self._idempotency.get(key)
        return self.builds.get(bid) if bid else None

    def remember_idempotency(self, key: str | None, build_id: str) -> None:
        if key:
            self._idempotency[key] = build_id


# ---------------------------------------------------------------- serialization
# Contract 2 / Contract 3 wire shapes. These match scripts/make_fixtures.py exactly -- the
# frontend develops against those fixtures, so any drift here is a broken contract, not a detail.


def build_to_json(build: Build) -> dict:
    return {
        "id": build.id,
        "name": build.name,
        "version": build.version,
        "parts": [part_to_json(p) for p in build.parts],
        "subassemblies": {
            s.id: {"parent": s.parent,
                   "attach": [{"at": list(a.at), "face": a.face,
                               "studs": [list(x) for x in a.studs]} for a in s.attach]}
            for s in build.subassemblies
        },
        "provenance": build.provenance,
    }


def part_to_json(p: Placed) -> dict:
    return {"id": p.id, "part": p.part, "color": p.color,
            "pos": list(p.pos), "rot": p.rot, "sub": p.sub}


def steps_to_json(steps: Iterable[Iterable[Placed]]) -> dict:
    from core import meta

    out = []
    for i, group in enumerate(steps, 1):
        group = list(group)
        counts: dict[tuple[str, int], int] = {}
        for p in group:
            counts[(p.part, p.color)] = counts.get((p.part, p.color), 0) + 1
        out.append({
            "index": i,
            "parts": [part_to_json(p) for p in group],
            "callout": [{"part": k[0], "name": meta.get(k[0]).name, "color": k[1], "qty": n}
                        for k, n in sorted(counts.items())],
        })
    return {"steps": out, "total": len(out)}


def version_to_json(v: Version, tree: VersionTree) -> dict:
    return {
        "build_id": v.build_id,
        "version": v.version,
        "parent": v.parent,
        "op": v.op.to_dict(),
        "cost": v.cost.to_dict(),
        "steps_ready": v.steps_ready,
        "can_undo": tree.can_undo,
        "can_redo": tree.can_redo,
        "notes": list(v.notes),
    }
