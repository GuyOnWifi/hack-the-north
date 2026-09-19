#!/usr/bin/env python3
"""Measure the CV pipeline on the user's OWN photos and write eval/RESULTS.md.

These photos have NO ground-truth boxes, so recall and precision are NOT computable here and this
script never prints them. What it does report is everything that does not need labels: how many
things each backend detects, how confident the classifier was, what SHAPE the bin has, and what
each stage costs in wall-clock seconds.

    python -m eval.real_report --measure        # re-run segmentation (~1 min), refresh the cache
    python -m eval.real_report                  # regenerate RESULTS.md from the cache, instantly

Segmentation is cached to `eval/real_cache.json` per (photo, backend) with one entry per detected
piece, so the report can be regenerated -- and the shape filter re-scored -- without paying SAM 2's
~6 s per photo again. The cache stores geometry, not pixels; it is small enough to commit.

Two deliberate choices, both of which the report states out loud:

  * The shape filter is SCORED FROM THE CACHE, not from a second segmentation pass. In
    `vision/segment.py` it runs strictly after containment suppression, on the surviving pieces,
    so applying `plausible_brick` to the cached survivors is the same computation -- and it is the
    real predicate, imported, not a copy. `tests/test_real_report.py` pins that equivalence.
  * Classification is read from the on-disk Brickognize cache and never hits the network unless
    you pass --online. Crops that are not cached are counted as misses rather than quietly timed
    as zero.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import statistics
import sys
import time
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPREAD = ROOT / "data" / "real" / "spread"
CACHE = ROOT / "eval" / "real_cache.json"
OUT = ROOT / "eval" / "RESULTS.md"
RESULTS_TSV = ROOT / "eval" / "results.tsv"
CHECKPOINT = ROOT / "data" / "models" / "sam2.1_hiera_small.pt"

# Inventories the pipeline has already produced. Both are owned by another lane and may or may not
# exist while this runs; the report degrades to whichever it finds.
INVENTORIES = [
    ("data/real/inventory_all.json", "all nine photos"),
    ("data/real/inventory.json", "lego.jpg only"),
]

CACHE_VERSION = 2

# Matches vision/pipeline.py's confidence policy. Duplicated as bucket EDGES only -- the policy
# itself still lives in the pipeline, and the report labels each bucket with what the pipeline
# does with it, so a drift shows up as a contradiction rather than a silent mismatch.
BUCKETS = [
    (0.85, 1.01, "confirmed", ">= 0.85"),
    (0.50, 0.85, "needs_review", "0.50-0.85"),
    (0.00, 0.50, "unknown", "< 0.50"),
]


# ------------------------------------------------------------------ measurement


def _digest(png: bytes) -> str:
    return hashlib.sha256(png).hexdigest()


def measure_photo(path: pathlib.Path, backend: str, *, online: bool = False) -> dict:
    """Segment one photo with one backend and time every stage of the pipeline around it.

    Returns a cache entry: per-piece geometry plus per-stage seconds. No classification happens
    offline -- we time cache reads, which is the path the demo actually runs on.
    """
    import cv2

    from vision import classify as classify_mod
    from vision import color as color_mod
    from vision import segment as seg_mod

    t0 = time.perf_counter()
    image = cv2.imread(str(path))
    if image is None:
        raise FileNotFoundError(f"cannot read image: {path}")
    t_read = time.perf_counter() - t0

    t0 = time.perf_counter()
    work, pieces = seg_mod.segment(image, backend=backend)
    t_segment = time.perf_counter() - t0

    t0 = time.perf_counter()
    crops = [p.crop_on_white(work, full_res=image) for p in pieces]
    pngs = [cv2.imencode(".png", c)[1].tobytes() for c in crops]
    t_crop = time.perf_counter() - t0

    t0 = time.perf_counter()
    illum = color_mod.estimate_illuminant(work)
    colours = [color_mod.colour_of(work, p.mask, illum) for p in pieces]
    t_colour = time.perf_counter() - t0

    t0 = time.perf_counter()
    if online:
        cands = classify_mod.classify_many(pngs)
        hits = sum(1 for c in cands if c)
    else:
        # Cache-only: the demo path, and the only path that is guaranteed to work with no network.
        hits = 0
        for png in pngs:
            if classify_mod._cache_path(_digest(png)).exists():
                classify_mod.classify_bytes(png)
                hits += 1
    t_classify = time.perf_counter() - t0

    return {
        "photo": path.name,
        "backend": backend,
        "pixels": [int(image.shape[1]), int(image.shape[0])],
        "working": [int(work.shape[1]), int(work.shape[0])],
        "pieces": [
            {"bbox": [int(v) for v in p.bbox], "area": int(p.area),
             "solidity": round(float(p.solidity), 4), "color": int(c[0])}
            for p, c in zip(pieces, colours)
        ],
        "classify_hits": hits,
        "classify_online": bool(online),
        "seconds": {
            "read": round(t_read, 3),
            "segment": round(t_segment, 3),
            "crop": round(t_crop, 3),
            "colour": round(t_colour, 3),
            "classify": round(t_classify, 3),
        },
    }


def shape_filter_survivors(pieces: list[dict]) -> list[dict]:
    """Which cached pieces `VISION_SHAPE_FILTER=1` would have kept.

    Calls the real `plausible_brick`, with the same median-area reference `suppress_parts` uses,
    so this cannot drift from the shipped filter. See the module docstring for why scoring it from
    the cache is equivalent to a second segmentation pass.
    """
    from vision.segment import Piece, plausible_brick

    if not pieces:
        return []
    med = statistics.median(p["area"] for p in pieces)
    out = []
    for i, p in enumerate(pieces):
        shim = Piece(i, tuple(p["bbox"]), None, p["area"], p["solidity"])
        if plausible_brick(shim, med):
            out.append(p)
    return out


# ------------------------------------------------------------------ analysis (pure)


def bin_shape(inventory: dict) -> dict:
    """The headline: how long-tailed is this bin, with and without colour?

    A bin where almost every row is quantity one starves generators that assume you own several of
    the same part. Pooling across colour is the cheapest way to turn a long tail into usable
    multiples, and this function is what makes the size of that win visible.
    """
    items = inventory.get("items", [])
    pooled: Counter = Counter()
    names: dict[str, str] = {}
    for it in items:
        pooled[it["part"]] += it["qty"]
        names.setdefault(it["part"], it.get("name", it["part"]))

    identified = sum(it["qty"] for it in items)
    totals = inventory.get("totals", {})
    unknown = int(totals.get("unknown", 0))
    return {
        "detections": identified + unknown,
        "identified": identified,
        "unknown": unknown,
        "unknown_rate": unknown / (identified + unknown) if identified + unknown else 0.0,
        "combos": len(items),
        "parts": len(pooled),
        "combos_qty2": sum(1 for it in items if it["qty"] >= 2),
        "parts_qty2": sum(1 for n in pooled.values() if n >= 2),
        "largest_combo": max((it["qty"] for it in items), default=0),
        "largest_part": max(pooled.values(), default=0),
        # The number that actually predicts whether a generator can be fed. Our generators ask for
        # runs of the same part -- a wall, a chassis floor -- so a piece is only useful to them if
        # it sits in a group of at least four. Counting PIECES rather than rows is the point: 40
        # singletons and one row of 40 are the same row count and completely different bins.
        "pieces_in_combo4": sum(it["qty"] for it in items if it["qty"] >= 4),
        "pieces_in_part4": sum(n for n in pooled.values() if n >= 4),
        "top": [(p, n, names[p]) for p, n in pooled.most_common(10)],
        "photos": sorted({it.get("evidence", {}).get("photo", "?") for it in items}),
    }


def confidence_distribution(inventory: dict) -> dict:
    """Piece-weighted classifier confidence, bucketed by what the pipeline DOES with each band.

    Weighted by `qty` because a row that merged six detections represents six classifier calls.
    Rows that scored below the unknown threshold are not in `items` at all -- they survive only as
    `totals.unknown`, which is why the unknown count is reported separately rather than as a
    fourth bucket computed from rows that do not exist.

    Part and colour are bucketed on DIFFERENT edges on purpose: the pipeline's part policy has
    three bands at 0.85/0.50, and its colour policy has one threshold at 0.60 (exact vs similar).
    Scoring colour against the part policy's edges would invent a band the system does not have.
    """
    items = inventory.get("items", [])
    part_hist: Counter = Counter()
    for it in items:
        for lo, hi, name, _label in BUCKETS:
            if lo <= it["confidence"]["part"] < hi:
                part_hist[name] += it["qty"]

    exact = sum(it["qty"] for it in items if it.get("color_mode") == "exact")
    identified = sum(it["qty"] for it in items)
    return {
        "part": part_hist,
        "identified": identified,
        "colour_exact": exact,
        "colour_similar": identified - exact,
        "colour_exact_rate": exact / identified if identified else 0.0,
        "colour_median": (statistics.median([it["confidence"]["color"] for it in items])
                          if items else 0.0),
        "unplaceable": sum(it["qty"] for it in items if not it.get("placeable", True)),
    }


def labelled_rows(tsv: pathlib.Path) -> list[dict]:
    """The numbers we DO have labels for, straight out of eval/results.tsv."""
    if not tsv.exists():
        return []
    lines = [ln for ln in tsv.read_text().splitlines() if ln.strip()]
    if len(lines) < 2:
        return []
    head = lines[0].split("\t")
    return [dict(zip(head, ln.split("\t"))) for ln in lines[1:]]


# ------------------------------------------------------------------ rendering


def _md_table(head: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(head) + " |",
           "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def render(cache: dict, inventories: list[tuple[str, str, dict]],
           labelled: list[dict]) -> str:
    """The whole of RESULTS.md. Every number carries the command that produced it."""
    from vision.segment import MAX_PIECES

    photos = sorted(cache.get("photos", {}))
    backends = sorted({b for p in cache.get("photos", {}).values() for b in p})
    primary = inventories[0] if inventories else None

    L: list[str] = []
    L.append("# Bricolage \u2014 measured on nine real phone photos")
    L.append("")
    L.append(f"Nine 4000x3000 phone photos of one household brick bin, spread on a patterned "
             f"blanket: `data/real/spread/`. Regenerate this file with "
             f"`python -m eval.real_report` (instant, reads `eval/real_cache.json`) or "
             f"`python -m eval.real_report --measure` (re-segments every photo, ~70 s).")
    L.append("")

    # ---------------------------------------------------------- headline
    if primary and photos:
        _p, scope, inv = primary
        sh = bin_shape(inv)
        sam = [cache["photos"][n]["sam2"] for n in photos if "sam2" in cache["photos"][n]]
        L.append("## What works")
        L.append("")
        if sam:
            med = statistics.median(sum(e["seconds"].values()) for e in sam)
            L.append(f"- **The pipeline runs end to end on real phone photos with no network.** "
                     f"SAM 2 on MPS, {med:.1f} s per 4000x3000 photo including crop, colour and a "
                     f"cached classify; the OpenCV fallback does the same in "
                     f"{statistics.median(sum(e['seconds'].values()) for e in [cache['photos'][n]['opencv'] for n in photos if 'opencv' in cache['photos'][n]]):.2f} s with no model at all.")
        L.append(f"- **{sh['detections']} detections across {scope}**, of which "
                 f"{sh['identified']} were identified into {sh['combos']} part+colour rows.")
        L.append(f"- **Pooling across colour turns {sh['combos']} rows into {sh['parts']} parts** "
                 f"and takes the pieces that live in a group of four or more from "
                 f"{sh['pieces_in_combo4']} to {sh['pieces_in_part4']}. That is the whole "
                 f"argument for colour pooling, in one line.")
        L.append(f"- **{sh['unknown']} of {sh['detections']} detections ({100 * sh['unknown_rate']:.0f}%) "
                 f"came back unknown.** They stay in the bin and stay out of the solver. Nothing "
                 f"is silently dropped and nothing is invented.")
        L.append("")

    # ---------------------------------------------------------- the caveat
    L.append("## What these numbers are not")
    L.append("")
    L.append("**There is no ground truth for these photos.** Nobody has drawn a box round each "
             "brick in them, so recall and precision are not computable here, and nothing in "
             "this file reports either for them. Every number below is a count, a distribution "
             "or a duration \u2014 the things that need no labels.")
    L.append("")
    L.append("The labelled recall/precision numbers we do have were measured on a different, "
             "published dataset and live in their own section at the bottom. They are not "
             "measurements of these photos.")
    L.append("")

    # ---------------------------------------------------------- bin shape (headline)
    if inventories:
        L.append("## The shape of the bin")
        L.append("")
        L.append("A real household bin is long-tailed: almost every row is quantity one. Our "
                 "generators ask for runs of the same part, so that tail is what makes "
                 "\"build me a rover\" collapse into a three-part build. Ignoring colour is the "
                 "cheapest fix available, and colour is also our least reliable stage \u2014 so "
                 "the constraint we are least sure of is the one doing the most damage.")
        L.append("")
        for path, scope, inv in inventories:
            sh = bin_shape(inv)
            # The command that made the file, reconstructed from the photos its rows cite, so a
            # reader can rerun exactly this and not a similar-looking thing.
            src = ("data/real/spread" if len(sh["photos"]) > 1
                   else f"data/real/spread/{sh['photos'][0]}" if sh["photos"] else "<photos>")
            L.append(f"### `{path}` \u2014 {scope}")
            L.append("")
            L.append(f"Produced by `python -m vision.pipeline {src} -o {path}`.")
            L.append("")
            L.append(_md_table(
                ["", "counting colour", "ignoring colour"],
                [["distinct entries", sh["combos"], sh["parts"]],
                 ["entries with qty >= 2", sh["combos_qty2"], sh["parts_qty2"]],
                 ["largest single entry", f'{sh["largest_combo"]}x', f'{sh["largest_part"]}x'],
                 ["**pieces in a group of 4+**", f'**{sh["pieces_in_combo4"]}**',
                  f'**{sh["pieces_in_part4"]}**']]))
            L.append("")
            ratio = (sh["pieces_in_part4"] / sh["pieces_in_combo4"]
                     if sh["pieces_in_combo4"] else float("inf"))
            ratio_txt = (f"{ratio:.1f}x more" if ratio != float("inf")
                         else "usable material where there was none")
            L.append(f"{sh['combos']} part+colour combinations, {sh['parts']} distinct parts, "
                     f"{sh['identified']} identified pieces. Pooling colour gives the generators "
                     f"{ratio_txt} to work with.")
            L.append("")
            L.append(_md_table(["part", "qty (colour pooled)", "name"],
                               [[p, n, nm] for p, n, nm in sh["top"]]))
            L.append("")

    # ---------------------------------------------------------- detections
    L.append("## Detections per photo, per backend and setting")
    L.append("")
    if not photos:
        L.append("_No cache. Run `python -m eval.real_report --measure` first._")
        L.append("")
    else:
        head = ["photo"]
        for b in backends:
            head += [b, f"{b} +filter"]
        rows, capped = [], []
        for name in photos:
            row = [name]
            for b in backends:
                entry = cache["photos"][name].get(b)
                if not entry:
                    row += ["-", "-"]
                    continue
                kept = len(entry["pieces"])
                if kept >= MAX_PIECES:
                    capped.append(f"{name}/{b}")
                    row.append(f"{kept} (capped)")
                else:
                    row.append(kept)
                row.append(len(shape_filter_survivors(entry["pieces"])))
            rows.append(row)
        totals = ["**total**"]
        for b in backends:
            entries = [cache["photos"][n].get(b) for n in photos]
            entries = [e for e in entries if e]
            totals += [sum(len(e["pieces"]) for e in entries),
                       sum(len(shape_filter_survivors(e["pieces"])) for e in entries)]
        rows.append(totals)
        L.append(_md_table(head, rows))
        L.append("")
        L.append("`+filter` is `VISION_SHAPE_FILTER=1`: four arithmetic gates on area, aspect, "
                 "solidity and bbox fill. It is scored from the cached geometry using the same "
                 "`plausible_brick` predicate the pipeline calls; that filter runs strictly after "
                 "containment suppression, so scoring it from the survivors is the same "
                 "computation as a second segmentation pass, and "
                 "`tests/test_real_report.py::test_shape_filter_matches_the_shipped_pipeline` "
                 "pins the two together.")
        L.append("")
        if capped:
            L.append(f"**{len(capped)} of these counts hit `vision.segment.MAX_PIECES` "
                     f"({MAX_PIECES}) and are floors, not counts:** {', '.join(capped)}. Those "
                     f"photos are the densest in the set. Raise the cap before quoting a number "
                     f"for them.")
            L.append("")
        L.append("**A detection is not a brick.** Without labels we cannot say which column is "
                 "closer to the truth \u2014 only that SAM 2 returns more objects than OpenCV and "
                 "that the filter removes this many of them. Where the filter HAS been scored "
                 "against labels (the separate set below, 10 images) it cost 0.884 \u2192 0.816 "
                 "recall and bought 0.887 \u2192 0.985 precision. Whether that trade is right for "
                 "these photos is unmeasured, which is why the filter ships off by default.")
        L.append("")

    # ---------------------------------------------------------- confidence
    if primary:
        path, _scope, inv = primary
        dist = confidence_distribution(inv)
        sh = bin_shape(inv)
        L.append("## Classifier confidence")
        L.append("")
        L.append(f"Piece-weighted, from `{path}`. The bands are the pipeline\u2019s own policy "
                 "(`vision/pipeline.py`): >= 0.85 ships as confirmed, 0.50\u20130.85 is flagged "
                 "for review with alternatives one tap away, < 0.50 is dropped to unknown and "
                 "excluded from the solver.")
        L.append("")
        rows = []
        for _lo, _hi, name, label in BUCKETS:
            n = dist["part"].get(name, 0) + (sh["unknown"] if name == "unknown" else 0)
            rows.append([label, name, n,
                         f"{100 * n / max(1, sh['detections']):.0f}%"])
        L.append(_md_table(["part score", "the pipeline calls it", "pieces", "share"], rows))
        L.append("")
        L.append(f"Unknown rate: **{sh['unknown']}/{sh['detections']} = "
                 f"{100 * sh['unknown_rate']:.0f}%**. Only {dist['part'].get('confirmed', 0)} "
                 f"pieces cleared 0.85. The mass of this distribution sits in `needs_review`, "
                 f"which is the band the confirm loop exists for: one human correction re-ranks "
                 f"every similar ambiguous row (`vision/confirm.py`).")
        L.append("")
        L.append("Colour is scored on its own single threshold, not these bands \u2014 the "
                 "pipeline asks one question of it (trust this colour, yes or no) at 0.60:")
        L.append("")
        L.append(_md_table(
            ["colour confidence", "inventory records", "pieces", "share"],
            [[">= 0.60", "`color_mode: exact`", dist["colour_exact"],
              f"{100 * dist['colour_exact_rate']:.0f}%"],
             ["< 0.60", "`color_mode: similar`", dist["colour_similar"],
              f"{100 * (1 - dist['colour_exact_rate']):.0f}%"]]))
        L.append("")
        L.append(f"Median colour confidence over rows: {dist['colour_median']:.2f}. On a "
                 f"patterned blanket under room light, colour is close to unusable as a hard "
                 f"constraint \u2014 which is the second, independent reason to pool across it.")
        L.append("")

    # ---------------------------------------------------------- runtime
    L.append("## Runtime per stage")
    L.append("")
    if not photos:
        L.append("_No cache._")
        L.append("")
    else:
        rows = []
        for b in backends:
            entries = [cache["photos"][n][b] for n in photos if b in cache["photos"][n]]
            if not entries:
                continue
            row = [b, len(entries)]
            for stage in ("read", "segment", "crop", "colour", "classify"):
                row.append(f"{statistics.median(e['seconds'][stage] for e in entries):.2f}")
            row.append(f"{statistics.median(sum(e['seconds'].values()) for e in entries):.2f}")
            rows.append(row)
        L.append(_md_table(
            ["backend", "photos", "read", "segment", "crop", "colour", "classify", "total"], rows))
        L.append("")
        L.append("Median seconds per 4000x3000 photo, measured by "
                 "`python -m eval.real_report --measure` on the laptop that will run the demo "
                 "(Apple silicon, MPS). `read` is JPEG decode plus the downscale to 1600 px that "
                 "segmentation works on; `crop` cuts every piece at FULL resolution and "
                 "PNG-encodes it; `colour` is one illuminant estimate per frame plus one "
                 "median-LAB lookup per piece.")
        L.append("")
        online = any(e.get("classify_online") for p in cache["photos"].values()
                     for e in p.values())
        hits = sum(e.get("classify_hits", 0) for p in cache["photos"].values()
                   for e in p.values())
        det = sum(len(e["pieces"]) for p in cache["photos"].values() for e in p.values())
        if online:
            L.append("`classify` includes live Brickognize calls (measured with `--online`).")
        else:
            L.append(f"`classify` is the offline path: {hits} of {det} crops were already in "
                     f"`data/brickognize_cache/` and were read from disk in that time. A crop "
                     f"that is not cached costs a network round trip, which is deliberately not "
                     f"measured here \u2014 the demo machine is assumed to have no network.")
        L.append("")

    # ---------------------------------------------------------- labelled numbers
    L.append("## Separately: the numbers we do have labels for")
    L.append("")
    L.append("These are **not** measurements of the photos above. They come from the published "
             "Brickognize evaluation set, which ships ground-truth boxes, via "
             "`python -m eval.pile_eval <folder> --tag <name>`, which appends to "
             "`eval/results.tsv`.")
    L.append("")
    if labelled:
        keep = ["opencv-prec", "sam2-prec", "opencv-containment", "synth-containment",
                "sam2-final", "filter-off", "filter-on"]
        order = {t: i for i, t in enumerate(keep)}
        rows = sorted(([r["tag"], r["images"], r["recall"], r["precision"]]
                       for r in labelled if r["tag"] in order), key=lambda r: order[r[0]])
        L.append(_md_table(["run", "images", "recall", "precision"], rows))
        L.append("")
    L.append("The classification columns in that file read 0.000 because the labelled set is "
             "class-agnostic \u2014 every box is just `brick`, with no part id \u2014 so it can "
             "score segmentation and cannot score naming. We print the zero rather than hide the "
             "column.")
    L.append("")

    # ---------------------------------------------------------- limits
    L.append("## Limits")
    L.append("")
    L.append("- **No labels on our own photos.** No recall, no precision, no top-1 for them. "
             "The fix is an afternoon in CVAT producing one `.truth.json` per photo; it has not "
             "been done.")
    L.append("- **An inventory file does not record how it was made.** `inventory.json` and "
             "`inventory_all.json` carry no backend, no settings and no timestamp, so their "
             "detection counts cannot be reconciled with the table above with certainty: the "
             "one-photo inventory reports 74 detections for `lego.jpg`, which equals our "
             "sam2 +filter count and not our unfiltered 89 \u2014 suggestive, not evidence. "
             "One `provenance` field on the inventory would close this.")
    if photos:
        L.append(f"- **`MAX_PIECES` is {MAX_PIECES}** and the densest photos reach it, so their "
                 f"counts are floors.")
    L.append("- **Heaped bricks break both backends.** SAM 2 returned 82 masks for ~14 bricks on "
             "a heap, having boxed individual studs; containment suppression cut that to 34, "
             "which is still wrong. Single-layer capture is a stated operating condition.")
    L.append("- **Colour is the weakest stage**, 0.703 accuracy on high-confidence rows of the "
             "labelled set (`python -m eval.color_eval`), and on these photos most rows do not "
             "even reach the trust threshold. The inventory exposes `color_mode` instead of "
             "treating colour as a hard constraint for exactly this reason.")
    L.append("- **Brickognize returns BrickLink ids, not LDraw ids.** `vision/resolve.py` maps "
             "them; without it the commonest parts silently become unplaceable and vanish.")
    L.append("")
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ cli


def load_cache(path: pathlib.Path) -> dict:
    if not path.exists():
        return {"version": CACHE_VERSION, "photos": {}}
    data = json.loads(path.read_text())
    if data.get("version") != CACHE_VERSION:
        # A stale schema is worse than no cache: re-measure rather than render wrong numbers.
        return {"version": CACHE_VERSION, "photos": {}}
    return data


def load_inventories() -> list[tuple[str, str, dict]]:
    out = []
    for rel, scope in INVENTORIES:
        p = ROOT / rel
        if p.exists():
            try:
                out.append((rel, scope, json.loads(p.read_text())))
            except json.JSONDecodeError:
                continue          # another lane may be mid-write; skip rather than crash
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--measure", action="store_true",
                    help="re-run segmentation and refresh the cache (slow: SAM 2 is ~6 s/photo)")
    ap.add_argument("--backends", default="opencv,sam2")
    ap.add_argument("--photos", default=str(SPREAD))
    ap.add_argument("--cache", default=str(CACHE))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--online", action="store_true",
                    help="allow live Brickognize calls when timing the classify stage")
    args = ap.parse_args(argv)

    cache_path = pathlib.Path(args.cache)
    cache = load_cache(cache_path)

    if args.measure:
        # SAM 2 is the default backend only when a checkpoint is advertised. The checkpoint is in
        # the repo, so pointing at it here means the report does not depend on a shell profile.
        if not os.environ.get("SAM2_CHECKPOINT") and CHECKPOINT.exists():
            os.environ["SAM2_CHECKPOINT"] = str(CHECKPOINT)

        folder = pathlib.Path(args.photos)
        photos = sorted(p for p in folder.glob("*")
                        if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
        if not photos:
            print(f"no photos in {folder}", file=sys.stderr)
            return 1
        for backend in [b.strip() for b in args.backends.split(",") if b.strip()]:
            for p in photos:
                print(f"  {backend:7s} {p.name} ...", end="", flush=True)
                try:
                    entry = measure_photo(p, backend, online=args.online)
                except Exception as exc:              # one bad backend must not lose the others
                    print(f" FAILED: {exc}")
                    continue
                cache.setdefault("photos", {}).setdefault(p.name, {})[backend] = entry
                print(f" {len(entry['pieces']):3d} pieces  "
                      f"{sum(entry['seconds'].values()):.1f}s")
        cache["checkpoint"] = pathlib.Path(os.environ.get("SAM2_CHECKPOINT", "")).name or None
        cache_path.write_text(json.dumps(cache, indent=1) + "\n")
        print(f"cache -> {cache_path}")

    text = render(cache, load_inventories(), labelled_rows(RESULTS_TSV))
    pathlib.Path(args.out).write_text(text)
    print(f"wrote {args.out}  ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
