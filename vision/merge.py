"""Merge several photos' inventories into one Contract 1 inventory.

    python -m vision.merge data/real/*.json -o merged.json --mode same_pile

Why this exists
---------------
One photo of a real bin is never the whole bin. The user shoots a handful, spreads another
handful, shoots again. But a shoot is ALSO how you re-photograph the same bricks from a second
angle to catch what the first frame missed. Those two situations need opposite arithmetic:

    distinct_piles   different handfuls    -> quantities ADD
    same_pile        re-shoots of one pile -> quantities take the MAX, evidence merges

and getting it backwards is not a rounding error. Telling someone they own twelve 2x4s when they
own six produces a build that cannot be built, discovered by the user with the manual already
printed. **Inflating a bin is the worst failure in this file**, so the merge always runs the
duplicate detector and always says what it concluded, even when it was told the mode outright.

The detector has two signals and is careful to say which one fired, because they are not equally
strong. Identical detection boxes PROVE two inputs are the same photograph (segmentation is
deterministic). A matching part histogram only SUSPECTS it -- measured on the real bin, two
different handfuls scooped from one box score 0.90-0.95 and two re-shoots of one pile score 0.98+,
so counts alone genuinely cannot decide it. Colour is pooled out of the histogram by default,
because colour is our weakest stage at 0.70 accuracy and two photos of one pile disagree about hue
long before they disagree about shape. Either way the detector is a hint, never a silent override:
`mode="auto"` asks to be overridden, the two explicit modes are obeyed and warned about.

Confidence merges upward. A brick caught side-on in photo 3 and dead-on in photo 7 is the same
brick, and the good view is what we know about it -- a bad angle is not evidence against a good
one. This is deliberately the opposite of `to_inventory`, which is pessimistic WITHIN one photo
(it has no second opinion to prefer); across photos we have one, so we use it.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
from collections import Counter
from dataclasses import dataclass

from .pipeline import COLOUR_TRUSTED_AT, CONFIRM_AT, MIN_PIECES_TO_BUILD

MODES = ("distinct_piles", "same_pile", "auto")
DEFAULT_MODE = "distinct_piles"

# Cosine over part histograms above which two photos are called the same bricks twice.
#
# MEASURED on the real 9-photo bin (1,296 detections, 102 distinct parts), and the measurement is
# uncomfortable, so it is written down rather than hidden:
#
#     two re-shoots of one pile, each missing 10-40% of it     0.976 .. 0.998
#     two different handfuls scooped from the same bin         0.898 .. 0.952
#     two disjoint slices of the element list                  0.565 .. 0.862
#
# The middle row is the problem. Two handfuls out of ONE bin have, by construction, the same part
# mix, and a scale-invariant cosine cannot see the difference. So the histogram is a SUSPICION and
# nothing more, and 0.96 is set where it separates the two measured clusters with the least
# damage: below it we add (and warn), above it we ask. Identical bounding boxes, below, are the
# only signal in this file that PROVES two inputs are the same photograph.
SAME_PILE_AT = 0.96

# Fraction of the smaller photo's detection boxes that must land on identical coordinates before
# two inputs are called the same photograph rather than merely the same kind of pile -- and a
# floor, because one or two coincidentally equal boxes in a tiny inventory prove nothing.
SAME_PHOTO_BOXES = 0.5
SAME_PHOTO_MIN_BOXES = 3


@dataclass(frozen=True)
class Overlap:
    """Two sources that look like the same bricks twice.

    `kind` is the strength of the claim, and the distinction matters to the user:
        "same_photo"  identical detection boxes -- the same frame, or one input contains the
                      other. Certain: segmentation is deterministic.
        "same_mix"    the part histograms agree. Suspicious, and provably not decidable from
                      counts alone: two handfuls from one bin look exactly like this.
    """

    a: str
    b: str
    similarity: float
    kind: str = "same_mix"
    shared_boxes: float = 0.0

    @property
    def human(self) -> str:
        if self.kind == "same_photo":
            # Covers equality AND containment -- a one-photo inventory merged with the run over
            # all nine photos hits this, and adding them would double-count that photo.
            return (f"{self.a} and {self.b} share a photograph "
                    f"({self.shared_boxes:.0%} of the smaller one's detections are in identical "
                    f"positions, so one is the same frame or is contained in the other)")
        return (f"{self.a} and {self.b} have the same mix of parts "
                f"({self.similarity:.0%} match) -- they may be the same bricks twice")

    def to_dict(self) -> dict:
        return {"a": self.a, "b": self.b, "kind": self.kind,
                "similarity": round(self.similarity, 3),
                "shared_boxes": round(self.shared_boxes, 3), "human": self.human}


@dataclass(frozen=True)
class MergeReport:
    """What the merge did and what it suspected. Rendered verbatim by the UI."""

    requested_mode: str
    mode: str
    sources: tuple[str, ...] = ()
    likely_same_pile: bool = False
    overlaps: tuple[Overlap, ...] = ()
    capped: tuple[str, ...] = ()
    warning: str | None = None

    def to_dict(self) -> dict:
        return {
            "requested_mode": self.requested_mode,
            "mode": self.mode,
            "sources": list(self.sources),
            "likely_same_pile": self.likely_same_pile,
            "overlaps": [o.to_dict() for o in self.overlaps],
            "capped": list(self.capped),
            "warning": self.warning,
        }


# ---------------------------------------------------------------- histograms


def part_histogram(inventory: dict, *, by_colour: bool = False) -> Counter:
    """Counts keyed by part (or by part+colour). Unknown rows have no part, so they drop out.

    Pooling colour out is the default because colour is the stage we trust least: the same bin
    read twice agrees about shape long before it agrees about hue.
    """
    hist: Counter = Counter()
    for item in inventory.get("items", ()):
        part = item.get("part")
        if not part:
            continue
        key = (part, item.get("color")) if by_colour else part
        hist[key] += int(item.get("qty", 0))
    return hist


def cosine(a, b) -> float:
    """Cosine similarity of two count mappings. 1.0 = identical mix, 0.0 = nothing in common.

    Scale-invariant on purpose: half a pile photographed twice has the same *mix* as the whole,
    and the mix is the signal we want.
    """
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def histogram_similarity(inv_a: dict, inv_b: dict, *, by_colour: bool = False) -> float:
    """How alike two inventories' part mixes are. The duplicate detector's whole basis."""
    return cosine(part_histogram(inv_a, by_colour=by_colour),
                  part_histogram(inv_b, by_colour=by_colour))


def detection_boxes(inventory: dict) -> set[tuple]:
    """Every detection box in an inventory, as hashable tuples. The identity signal."""
    boxes: set[tuple] = set()
    for item in inventory.get("items", ()):
        ev = item.get("evidence") or {}
        for box in ev.get("bboxes") or ([ev["bbox"]] if ev.get("bbox") else []):
            boxes.add(tuple(box))
    return boxes


def box_overlap(inv_a: dict, inv_b: dict) -> float:
    """Fraction of the smaller photo's boxes that appear, pixel-identical, in the other.

    Segmentation is deterministic, so the same photograph analysed twice produces the same boxes
    and two different photographs essentially never do. This is the only claim in this file that
    is evidence rather than inference.
    """
    a, b = detection_boxes(inv_a), detection_boxes(inv_b)
    shared = len(a & b)
    if not a or not b or shared < SAME_PHOTO_MIN_BOXES:
        return 0.0
    return shared / min(len(a), len(b))


def detect_duplicates(inventories: list[dict], labels: list[str] | None = None,
                      *, threshold: float = SAME_PILE_AT,
                      by_colour: bool = False) -> list[Overlap]:
    """Every pair of sources that may be the same bricks twice, strongest evidence first."""
    labels = list(labels or [])
    labels += [f"photo_{i + 1}" for i in range(len(labels), len(inventories))]
    hists = [part_histogram(inv, by_colour=by_colour) for inv in inventories]

    found = []
    for i in range(len(hists)):
        for j in range(i + 1, len(hists)):
            shared = box_overlap(inventories[i], inventories[j])
            sim = cosine(hists[i], hists[j])
            if shared >= SAME_PHOTO_BOXES:
                found.append(Overlap(labels[i], labels[j], sim, "same_photo", shared))
            elif sim >= threshold:
                found.append(Overlap(labels[i], labels[j], sim, "same_mix", shared))
    # Proof before suspicion, then strongest suspicion first.
    return sorted(found, key=lambda o: (o.kind != "same_photo", -o.similarity))


# ---------------------------------------------------------------- merging


def _sightings(item: dict, fallback_photo: str) -> list[dict]:
    """Every place this element was seen, tagged with which photo saw it.

    `evidence.bboxes` is one entry per detected instance (Contract 1). Once several photos are in
    play a bare box is useless -- "where are my six red 2x4s" needs to name the frame.
    """
    ev = item.get("evidence") or {}
    photo = ev.get("photo") or fallback_photo
    boxes = ev.get("bboxes")
    if not boxes:
        boxes = [ev["bbox"]] if ev.get("bbox") else []
    out = [{"photo": photo, "bbox": list(b)} for b in boxes]
    # An inventory that has already been merged carries richer sightings; keep their photo names.
    for s in ev.get("sightings") or []:
        if s.get("bbox") is not None:
            entry = {"photo": s.get("photo") or photo, "bbox": list(s["bbox"])}
            if entry not in out:
                out.append(entry)
    return out


def _conf(item: dict, field_name: str) -> float:
    return float((item.get("confidence") or {}).get(field_name, 0.0) or 0.0)


def _merge_alternatives(items: list[dict]) -> list[dict]:
    """Union of runner-up candidates, best score per part, top 3. The UI shows three."""
    best: dict[str, dict] = {}
    for item in items:
        for alt in (item.get("evidence") or {}).get("alternatives") or []:
            part = alt.get("part")
            if not part:
                continue
            if part not in best or float(alt.get("score", 0)) > float(best[part].get("score", 0)):
                best[part] = dict(alt)
    return sorted(best.values(), key=lambda a: -float(a.get("score", 0)))[:3]


def _merge_one_element(items: list[dict], qty: int, photos: list[str]) -> dict:
    """Collapse the same (part, colour) seen in several photos into one Contract 1 item."""
    best = max(items, key=lambda it: _conf(it, "part"))
    part_conf = max(_conf(it, "part") for it in items)
    colour_conf = max(_conf(it, "color") for it in items)

    # A human confirmation outranks any score: never demote a row the user already fixed.
    confirmed = any(it.get("status") == "confirmed" for it in items) or part_conf >= CONFIRM_AT

    # Dedupe on (photo, box): the same box in the same frame is the same brick seen twice by the
    # merge, not two bricks. Without this a self-merge reports qty 1 with two locations.
    sightings: list[dict] = []
    seen: set[tuple[str, tuple]] = set()
    for item, photo in zip(items, photos):
        for s in _sightings(item, photo):
            key = (s["photo"], tuple(s["bbox"]))
            if key not in seen:
                seen.add(key)
                sightings.append(s)

    return {
        "id": "",                                     # renumbered by the caller
        "part": best.get("part"),
        "name": best.get("name") or next((it.get("name") for it in items if it.get("name")), ""),
        "color": best.get("color"),
        "color_name": best.get("color_name") or next(
            (it.get("color_name") for it in items if it.get("color_name")), ""),
        "qty": qty,
        # A typed row is a human statement about the bin; a photo row is a guess. If the user
        # typed this element anywhere, the merged row inherits that standing.
        "source": "typed" if any(it.get("source") == "typed" for it in items) else
                  (best.get("source") or "photo"),
        "confidence": {"part": round(part_conf, 3), "color": round(colour_conf, 3)},
        "status": "confirmed" if confirmed else "needs_review",
        "placeable": any(bool(it.get("placeable")) for it in items),
        "color_mode": "exact" if colour_conf >= COLOUR_TRUSTED_AT else "similar",
        "evidence": {
            "photos": sorted({s["photo"] for s in sightings}),
            "photo": sightings[0]["photo"] if sightings else (photos[0] if photos else ""),
            "bbox": sightings[0]["bbox"] if sightings else None,
            # Flat boxes stay for Contract 1 compatibility; `sightings` is the same list with
            # the frame name attached, which is what a multi-photo UI actually needs.
            "bboxes": [s["bbox"] for s in sightings],
            "sightings": sightings,
            "alternatives": _merge_alternatives(items),
        },
    }


def _cap_by_part(merged: list[dict], per_part_ceiling: dict[str, int]) -> tuple[list[dict], list[str]]:
    """same_pile only: no part may exceed the most any single photo saw of it, colour pooled out.

    Taking the max per (part, colour) is not enough, because colour is our weakest stage: one
    re-shoot reading a red 2x4 as dark red turns one brick into two under two different keys, and
    the max never notices. Pooling across colour is exactly the fix the real bin argued for --
    49 part+colour combinations collapse to 29 parts, and twelve of them are 2x4s.

    Shrinking is applied to the least-confident colour first, because that is the row most likely
    to be the misread one.
    """
    by_part: dict[str, list[dict]] = {}
    for item in merged:
        by_part.setdefault(item["part"], []).append(item)

    capped: list[str] = []
    for part, rows in by_part.items():
        excess = sum(r["qty"] for r in rows) - per_part_ceiling.get(part, 0)
        if excess <= 0:
            continue
        removed = 0
        for row in sorted(rows, key=lambda r: (_conf(r, "color"), _conf(r, "part"))):
            if excess <= 0:
                break
            take = min(excess, row["qty"] - 1)      # never delete an element entirely: we did
            row["qty"] -= take                      # see it, we are only unsure about its colour
            excess -= take
            removed += take
        # Report only what actually moved. When every colour is down to one brick there is
        # nothing left to take, and claiming a cap we did not apply would be a lie in the UI.
        if removed:
            capped.append(part)
    return merged, capped


def merge_inventories(inventories: list[dict], mode: str = DEFAULT_MODE, *,
                      labels: list[str] | None = None,
                      session_id: str = "ses_merged",
                      threshold: float = SAME_PILE_AT) -> dict:
    """Several Contract 1 inventories -> one, plus a `merge` block saying what was assumed.

    `mode`:
        "distinct_piles" (default) each inventory is a different handful; quantities add.
        "same_pile"                re-shoots of one pile; quantities take the max and are then
                                   capped per part with colour pooled out.
        "auto"                     obey the duplicate detector.

    The two explicit modes are always obeyed -- guessing against an instruction is how you get a
    bug nobody can reproduce -- but a disagreement always lands in `merge.warning`.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, not {mode!r}")

    labels = list(labels or [])
    labels += [f"photo_{i + 1}" for i in range(len(labels), len(inventories))]
    labels = labels[:len(inventories)]

    if not inventories:
        return _empty(session_id, MergeReport(requested_mode=mode, mode=mode))

    overlaps = detect_duplicates(inventories, labels, threshold=threshold)
    likely_same = bool(overlaps)

    effective = mode
    warning = None
    if mode == "auto":
        # Erring toward same_pile: under-counting produces a smaller model, over-counting produces
        # a manual for a model the user cannot finish. Only one of those is discovered too late.
        effective = "same_pile" if likely_same else "distinct_piles"
        if likely_same:
            warning = ("Merged as one pile rather than separate handfuls: " + overlaps[0].human
                       + ". Re-run with --mode distinct_piles if they really are different bricks.")
    elif mode == "distinct_piles" and likely_same:
        warning = ("Quantities were ADDED, but " + overlaps[0].human + ". If these are the same "
                   "bricks twice, this inventory is double-counted -- re-run with "
                   "--mode same_pile.")
    elif mode == "same_pile" and not likely_same and len(inventories) > 1:
        warning = ("Quantities were capped as re-shoots of one pile, but these photos show "
                   "different part mixes. If they are separate handfuls, re-run with "
                   "--mode distinct_piles or you will under-count the bin.")

    add = effective == "distinct_piles"

    buckets: dict[tuple[str, object], dict] = {}
    for inv, label in zip(inventories, labels):
        for item in inv.get("items", ()):
            part = item.get("part")
            if not part:
                continue                              # unknown rows live in totals, not items
            b = buckets.setdefault((part, item.get("color")),
                                   {"items": [], "photos": [], "qtys": []})
            b["items"].append(item)
            b["photos"].append(label)
            b["qtys"].append(int(item.get("qty", 0)))

    merged = [_merge_one_element(b["items"],
                                 sum(b["qtys"]) if add else max(b["qtys"]),
                                 b["photos"])
              for b in buckets.values()]
    merged.sort(key=lambda it: (it["part"], it["color"] if it["color"] is not None else -1))

    capped: list[str] = []
    if not add:
        ceilings: dict[str, int] = {}
        for inv in inventories:
            for part, n in part_histogram(inv).items():
                ceilings[part] = max(ceilings.get(part, 0), n)
        merged, capped = _cap_by_part(merged, ceilings)

    for i, item in enumerate(merged, 1):
        item["id"] = f"inv_{i:03d}"

    unknowns = [int((inv.get("totals") or {}).get("unknown", 0)) for inv in inventories]
    unknown = sum(unknowns) if add else (max(unknowns) if unknowns else 0)

    report = MergeReport(requested_mode=mode, mode=effective, sources=tuple(labels),
                         likely_same_pile=likely_same, overlaps=tuple(overlaps),
                         capped=tuple(sorted(capped)), warning=warning)
    return _assemble(merged, unknown, session_id, report)


def _assemble(items: list[dict], unknown: int, session_id: str, report: MergeReport) -> dict:
    pieces = sum(int(i["qty"]) for i in items) + unknown
    return {
        "session_id": session_id,
        "items": items,
        "totals": {
            "pieces": pieces,
            "distinct": len(items),
            "unknown": unknown,
            "unplaceable": sum(1 for i in items if not i.get("placeable")),
        },
        "sufficient": pieces >= MIN_PIECES_TO_BUILD,
        "guidance": (None if pieces >= MIN_PIECES_TO_BUILD else
                     f"Found {pieces} pieces across {len(report.sources) or 1} photo(s). Spread "
                     f"more bricks out in a single layer and scan again -- we need about "
                     f"{MIN_PIECES_TO_BUILD} to design something worth building."),
        "merge": report.to_dict(),
    }


def _empty(session_id: str, report: MergeReport) -> dict:
    return _assemble([], 0, session_id, report)


# ---------------------------------------------------------------- CLI


def _load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="merge several inventory.json into one")
    ap.add_argument("inputs", nargs="+", help="inventory json files (shell glob is fine)")
    ap.add_argument("-o", "--out", default="merged.json")
    ap.add_argument("--mode", default=DEFAULT_MODE, choices=MODES,
                    help="distinct_piles: quantities add · same_pile: quantities take the max "
                         "· auto: let the duplicate detector decide")
    ap.add_argument("--threshold", type=float, default=SAME_PILE_AT,
                    help="part-histogram cosine above which two photos are called the same pile")
    ap.add_argument("--session", default="ses_merged")
    args = ap.parse_args(argv)

    paths = [pathlib.Path(p) for p in args.inputs]
    missing = [p for p in paths if not p.exists()]
    for p in missing:
        print(f"  ! missing, skipped: {p}", file=sys.stderr)
    paths = [p for p in paths if p not in missing]
    if not paths:
        print("no readable inventories", file=sys.stderr)
        return 2

    invs, labels = [], []
    for p in paths:
        try:
            invs.append(_load(p))
            labels.append(p.stem)
        except Exception as exc:                      # one bad file must not kill the merge
            print(f"  ! {p.name}: {exc}", file=sys.stderr)

    inv = merge_inventories(invs, args.mode, labels=labels,
                            session_id=args.session, threshold=args.threshold)
    pathlib.Path(args.out).write_text(json.dumps(inv, indent=2) + "\n")

    t, m = inv["totals"], inv["merge"]
    print(f"{len(labels)} inventories -> {t['pieces']} pieces · {t['distinct']} distinct "
          f"· {t['unknown']} unknown   [mode: {m['mode']}]")
    for o in m["overlaps"]:
        print(f"  ~ {o['human']}")
    if m["capped"]:
        print(f"  capped by part (colour pooled): {', '.join(m['capped'])}")
    if m["warning"]:
        print(f"  ! {m['warning']}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
