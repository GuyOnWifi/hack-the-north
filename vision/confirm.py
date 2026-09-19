"""The confirm loop: one human correction propagates to every row that looks like it.

Why this exists
---------------
Brickognize is confident on some crops and genuinely unsure on others. The unsure ones are not
random: a pile contains MANY COPIES of the same part, photographed at different angles. So when
the user confirms one ambiguous crop, they have not told us about one brick -- they have told us
about every similar-looking crop in the batch.

Two signals, both bounded and both auditable:

  1. SIZE SIMILARITY  the same mould photographed by the same camera at the same distance gives
                      crops of similar area and aspect ratio. A candidate that matches a confirmed
                      anchor of similar geometry gets boosted.
  2. OWNERSHIP PRIOR  people own multiples. A part confirmed once is more likely to recur in the
                      same pile than a part never seen.

Guardrails, because this must never invent data:
  * a row can only be re-ranked toward a candidate ALREADY in its top-k. We never introduce a part
    the classifier did not propose.
  * confirmed rows are frozen. Propagation never overwrites a human.
  * every change records WHY, and the UI shows it. A silent re-rank would be worse than no re-rank.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SIZE_TOL = 0.35          # relative area difference still counted as "the same size"
ASPECT_TOL = 0.30
SIZE_BOOST = 0.22
PRIOR_BOOST = 0.08
MAX_BOOST = 0.30


@dataclass
class Anchor:
    part: str
    color: int
    area: float
    aspect: float


@dataclass
class Change:
    row_index: int
    from_part: str | None
    to_part: str
    from_score: float
    to_score: float
    reason: str


@dataclass
class ConfirmState:
    """Detections plus everything the human has told us about them."""

    rows: list[dict]
    anchors: list[Anchor] = field(default_factory=list)
    confirmed: set[int] = field(default_factory=set)

    def confirm(self, row_index: int, part: str | None = None,
                color: int | None = None) -> list[Change]:
        """Record a human decision and propagate it. Returns what changed, for the UI."""
        row = self.rows[row_index]
        if part is not None:
            row["part"] = part
        if color is not None:
            row["color"] = color
        row["status"] = "confirmed"
        row["confidence"] = dict(row.get("confidence", {}), part=1.0)
        self.confirmed.add(row_index)

        if row.get("part"):
            self.anchors.append(Anchor(row["part"], row.get("color", 0),
                                       *_geometry(row)))
        return self.propagate()

    def propagate(self) -> list[Change]:
        if not self.anchors:
            return []
        owned = {a.part for a in self.anchors}
        changes: list[Change] = []

        for i, row in enumerate(self.rows):
            if i in self.confirmed or row.get("status") == "confirmed":
                continue
            area, aspect = _geometry(row)
            options = _candidates(row)
            if not options:
                continue

            best_part, best_score, best_reason = row.get("part"), _score(row), ""
            for part, score in options:
                boost, reason = 0.0, []
                for a in self.anchors:
                    if a.part != part:
                        continue
                    if _similar(area, aspect, a.area, a.aspect):
                        boost += SIZE_BOOST
                        reason.append("same size as a brick you confirmed")
                        break
                if part in owned:
                    boost += PRIOR_BOOST
                    reason.append("you own others of this part")
                if not boost:
                    continue
                new = min(1.0, score + min(boost, MAX_BOOST))
                if new > best_score + 1e-9:
                    best_part, best_score, best_reason = part, new, "; ".join(reason)

            if best_part and best_part != row.get("part"):
                changes.append(Change(i, row.get("part"), best_part,
                                      _score(row), best_score, best_reason))
                row["part"] = best_part
            elif best_reason and best_score > _score(row):
                changes.append(Change(i, row.get("part"), best_part or "",
                                      _score(row), best_score, best_reason))

            if best_reason:
                row["confidence"] = dict(row.get("confidence", {}), part=round(best_score, 3))
                row["propagated"] = best_reason
                if best_score >= 0.85:
                    row["status"] = "confirmed"

        return changes


def _geometry(row: dict) -> tuple[float, float]:
    x, y, w, h = row.get("bbox", [0, 0, 1, 1])
    w, h = max(1, w), max(1, h)
    return float(w * h), float(max(w, h) / min(w, h))


def _score(row: dict) -> float:
    return float(row.get("confidence", {}).get("part", 0.0))


def _candidates(row: dict) -> list[tuple[str, float]]:
    out = []
    if row.get("part"):
        out.append((row["part"], _score(row)))
    for a in row.get("alternatives", []):
        part = a.get("part")
        if part:
            out.append((part, float(a.get("score", 0.0))))
    return out


def _similar(a1: float, r1: float, a2: float, r2: float) -> bool:
    if a2 <= 0 or r2 <= 0:
        return False
    return (abs(a1 - a2) / a2 <= SIZE_TOL) and (abs(r1 - r2) / r2 <= ASPECT_TOL)
