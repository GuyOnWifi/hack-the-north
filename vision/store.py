"""Your brick collection, tracked over time.

A scan is a moment; a COLLECTION is what you own. This is the difference:

  * you photograph your bin over several sessions and the collection accumulates, without
    double-counting the same bricks when you re-shoot the same pile;
  * when you correct a misidentification, the correction STICKS -- and it is applied to future
    scans as a prior, so the same brick stops being wrong every time you photograph it;
  * when a build uses bricks, they are reserved; when you take the build apart, they come back.

Everything is JSON on disk. At the scale of one person's LEGO bin that is the right answer, and
it means the file is inspectable, diffable and trivially backed up.
"""

from __future__ import annotations

import json
import pathlib
import time
from dataclasses import dataclass, field, asdict

from core.model import Inventory
from vision.merge import merge_inventories, detect_duplicates

SCHEMA = 1


@dataclass
class Correction:
    """A human decision, kept forever. The most valuable data in the system."""

    part: str
    color: int
    was_part: str | None = None
    was_color: int | None = None
    at: float = 0.0
    note: str = ""


@dataclass
class Reservation:
    """Bricks currently inside a build. Owned but not available."""

    build_id: str
    counts: dict[str, int] = field(default_factory=dict)   # "part:color" -> qty
    at: float = 0.0
    name: str = ""


class BrickStore:
    """A persistent brick collection.

    The invariant that matters: `owned` never silently changes. Scans propose, the human
    confirms, and every change is recorded in `history` with what caused it. A tracker that
    quietly revises how many bricks you own is worse than no tracker.
    """

    def __init__(self, path: str | pathlib.Path = "data/real/collection.json"):
        self.path = pathlib.Path(path)
        self.inventory: dict = {"session_id": "collection", "items": [],
                                "totals": {"pieces": 0, "distinct": 0, "unknown": 0}}
        self.corrections: dict[str, Correction] = {}
        self.reservations: dict[str, Reservation] = {}
        self.history: list[dict] = []
        self.scans: list[str] = []
        if self.path.exists():
            self.load()

    # ------------------------------------------------------------------ persistence

    def load(self) -> None:
        d = json.loads(self.path.read_text())
        if d.get("schema") != SCHEMA:
            raise ValueError(f"{self.path} is schema {d.get('schema')}, this code speaks {SCHEMA}")
        self.inventory = d["inventory"]
        self.corrections = {k: Correction(**v) for k, v in d.get("corrections", {}).items()}
        self.reservations = {k: Reservation(**v) for k, v in d.get("reservations", {}).items()}
        self.history = d.get("history", [])
        self.scans = d.get("scans", [])

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({
            "schema": SCHEMA,
            "inventory": self.inventory,
            "corrections": {k: asdict(v) for k, v in self.corrections.items()},
            "reservations": {k: asdict(v) for k, v in self.reservations.items()},
            "history": self.history[-200:],
            "scans": self.scans,
        }, indent=2) + "\n")

    def _log(self, kind: str, **fields) -> None:
        self.history.append({"kind": kind, "at": time.time(), **fields})

    # ------------------------------------------------------------------ scanning

    def add_scan(self, scan: dict, *, label: str = "", mode: str = "auto") -> dict:
        """Merge one photo's detections into the collection.

        `mode="auto"` asks vision.merge whether this scan looks like a re-shoot of bricks we have
        already counted. Getting that wrong in the ADD direction silently inflates someone's
        collection, so when the detector is unsure we keep the larger-count interpretation OUT and
        say so in the returned report -- an undercount is recoverable by scanning again, an
        overcount produces build instructions for bricks that do not exist.
        """
        label = label or scan.get("session_id") or f"scan{len(self.scans) + 1}"
        if not self.inventory["items"]:
            merged, report = self._apply_corrections(scan), None
            self.inventory = merged
        else:
            overlaps = detect_duplicates([self.inventory, scan], ["collection", label])
            same_pile = bool(overlaps) if mode == "auto" else (mode == "same_pile")
            merged = merge_inventories(
                [self.inventory, self._apply_corrections(scan)],
                "same_pile" if same_pile else "distinct_piles",
                labels=["collection", label],
            )
            self.inventory = merged
            report = {"same_pile": same_pile,
                      "overlaps": [o.human for o in overlaps] if overlaps else []}
        self.scans.append(label)
        self._log("scan", label=label, pieces=self.inventory["totals"]["pieces"], report=report)
        return {"label": label, "totals": self.inventory["totals"], "merge": report}

    def _apply_corrections(self, scan: dict) -> dict:
        """Re-apply every past human correction to a fresh scan.

        This is the compounding value of the confirm loop: correct a brick once and it stays
        corrected in every photograph you ever take of it.
        """
        if not self.corrections:
            return scan
        out = json.loads(json.dumps(scan))
        n = 0
        for item in out.get("items", []):
            c = self.corrections.get(_key(item.get("part"), item.get("color")))
            if c is None:
                continue
            item["part"], item["color"] = c.part, c.color
            item["status"] = "confirmed"
            item.setdefault("confidence", {})["part"] = 1.0
            item["corrected_from"] = f"{c.was_part}:{c.was_color}"
            n += 1
        if n:
            self._log("corrections_applied", count=n)
        return out

    # ------------------------------------------------------------------ corrections

    def correct(self, was_part: str, was_color: int, part: str, color: int,
                note: str = "") -> Correction:
        """Record a human decision and apply it to what we already hold."""
        c = Correction(part=part, color=color, was_part=was_part, was_color=was_color,
                       at=time.time(), note=note)
        self.corrections[_key(was_part, was_color)] = c
        for item in self.inventory.get("items", []):
            if item.get("part") == was_part and item.get("color") == was_color:
                item["part"], item["color"] = part, color
                item["status"] = "confirmed"
                item.setdefault("confidence", {})["part"] = 1.0
        self._log("correction", was=f"{was_part}:{was_color}", now=f"{part}:{color}", note=note)
        return c

    # ------------------------------------------------------------------ builds

    def reserve(self, build_id: str, counts: dict[tuple[str, int], int],
                name: str = "") -> Reservation:
        """Mark the bricks a build is using. They stay owned but stop being available."""
        r = Reservation(build_id=build_id, name=name, at=time.time(),
                        counts={_key(p, c): n for (p, c), n in counts.items()})
        self.reservations[build_id] = r
        self._log("reserve", build_id=build_id, name=name, pieces=sum(r.counts.values()))
        return r

    def release(self, build_id: str) -> bool:
        """Take a build apart; its bricks become available again."""
        r = self.reservations.pop(build_id, None)
        if r is None:
            return False
        self._log("release", build_id=build_id, pieces=sum(r.counts.values()))
        return True

    # ------------------------------------------------------------------ views

    def owned(self, *, include_unknown: bool = False) -> Inventory:
        """Everything in the collection, reserved or not."""
        pairs = []
        for item in self.inventory.get("items", []):
            if not include_unknown and item.get("status") == "unknown":
                continue
            if not item.get("part"):
                continue
            pairs.append((item["part"], int(item.get("color", 0)), int(item.get("qty", 0))))
        return Inventory.from_pairs(pairs)

    def available(self) -> Inventory:
        """What you could build with RIGHT NOW -- owned minus everything inside a build."""
        inv = dict(self.owned().items)
        for r in self.reservations.values():
            for key, n in r.counts.items():
                part, color = _unkey(key)
                if (part, color) in inv:
                    inv[(part, color)] = max(0, inv[(part, color)] - n)
        return Inventory({k: v for k, v in inv.items() if v > 0})

    def summary(self) -> dict:
        owned, avail = self.owned(), self.available()
        parts = {}
        for (p, _c), n in owned.items.items():
            parts[p] = parts.get(p, 0) + n
        return {
            "scans": len(self.scans),
            "owned_pieces": owned.total,
            "available_pieces": avail.total,
            "reserved_pieces": owned.total - avail.total,
            "distinct_elements": len(owned.items),
            "distinct_parts": len(parts),
            "corrections": len(self.corrections),
            "builds": [{"id": r.build_id, "name": r.name, "pieces": sum(r.counts.values())}
                       for r in self.reservations.values()],
            "top_parts": sorted(parts.items(), key=lambda kv: -kv[1])[:8],
        }


def _key(part: str | None, color) -> str:
    return f"{part}:{color}"


def _unkey(key: str) -> tuple[str, int]:
    part, _, color = key.rpartition(":")
    return part, int(color)
