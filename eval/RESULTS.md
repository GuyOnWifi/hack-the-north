# Bricolage — measured on nine real phone photos

Nine 4000x3000 phone photos of one household brick bin, spread on a patterned blanket: `data/real/spread/`. Regenerate this file with `python -m eval.real_report` (instant, reads `eval/real_cache.json`) or `python -m eval.real_report --measure` (re-segments every photo, ~70 s).

## What works

- **The pipeline runs end to end on real phone photos with no network.** SAM 2 on MPS, 6.6 s per 4000x3000 photo including crop, colour and a cached classify; the OpenCV fallback does the same in 0.32 s with no model at all.
- **1296 detections across all nine photos**, of which 641 were identified into 261 part+colour rows.
- **Pooling across colour turns 261 rows into 102 parts** and takes the pieces that live in a group of four or more from 346 to 550. That is the whole argument for colour pooling, in one line.
- **655 of 1296 detections (51%) came back unknown.** They stay in the bin and stay out of the solver. Nothing is silently dropped and nothing is invented.

## What these numbers are not

**There is no ground truth for these photos.** Nobody has drawn a box round each brick in them, so recall and precision are not computable here, and nothing in this file reports either for them. Every number below is a count, a distribution or a duration — the things that need no labels.

The labelled recall/precision numbers we do have were measured on a different, published dataset and live in their own section at the bottom. They are not measurements of these photos.

## The shape of the bin

A real household bin is long-tailed: almost every row is quantity one. Our generators ask for runs of the same part, so that tail is what makes "build me a rover" collapse into a three-part build. Ignoring colour is the cheapest fix available, and colour is also our least reliable stage — so the constraint we are least sure of is the one doing the most damage.

### `data/real/inventory_all.json` — all nine photos

Produced by `python -m vision.pipeline data/real/spread -o data/real/inventory_all.json`.

|  | counting colour | ignoring colour |
|---|---|---|
| distinct entries | 261 | 102 |
| entries with qty >= 2 | 123 | 54 |
| largest single entry | 21x | 79x |
| **pieces in a group of 4+** | **346** | **550** |

261 part+colour combinations, 102 distinct parts, 641 identified pieces. Pooling colour gives the generators 1.6x more to work with.

| part | qty (colour pooled) | name |
|---|---|---|
| 3001 | 79 | brick 2x4 |
| 3003 | 61 | brick 2x2 |
| 3004 | 54 | brick 1x2 |
| 3039 | 33 | slope brick 45 2x2 |
| 3010 | 29 | brick 1x4 |
| 60481a | 20 | slope brick 65 2x1x2 with symmetric stud holder |
| 3002 | 17 | brick 2x3 |
| 3022 | 17 | plate 2x2 |
| 3020 | 16 | plate 2x4 |
| 3034 | 16 | plate 2x8 |

### `data/real/inventory.json` — lego.jpg only

Produced by `python -m vision.pipeline data/real/spread/lego.jpg -o data/real/inventory.json`.

|  | counting colour | ignoring colour |
|---|---|---|
| distinct entries | 49 | 29 |
| entries with qty >= 2 | 6 | 9 |
| largest single entry | 4x | 12x |
| **pieces in a group of 4+** | **4** | **23** |

49 part+colour combinations, 29 distinct parts, 57 identified pieces. Pooling colour gives the generators 5.8x more to work with.

| part | qty (colour pooled) | name |
|---|---|---|
| 3001 | 12 | brick 2x4 |
| 3003 | 6 | brick 2x2 |
| 3004 | 5 | brick 1x2 |
| 2431 | 3 | tile 1x4 with groove |
| 3039 | 3 | slope brick 45 2x2 |
| 3010 | 2 | brick 1x4 |
| 3666 | 2 | plate 1x6 |
| 3795 | 2 | plate 2x6 |
| 60481a | 2 | slope brick 65 2x1x2 with symmetric stud holder |
| 18980 | 1 | plate 2x6 with two rounded corners |

## Detections per photo, per backend and setting

| photo | opencv | opencv +filter | sam2 | sam2 +filter |
|---|---|---|---|---|
| lego.jpg | 48 | 19 | 89 | 74 |
| lego1.jpg | 23 | 14 | 108 | 93 |
| lego2.jpg | 19 | 9 | 81 | 75 |
| lego3.jpg | 186 | 151 | 200 (capped) | 188 |
| lego4.jpg | 28 | 22 | 178 | 168 |
| lego5.jpg | 36 | 22 | 184 | 178 |
| lego6.jpg | 57 | 34 | 168 | 158 |
| lego7.jpg | 161 | 82 | 200 (capped) | 189 |
| lego8.jpg | 36 | 26 | 164 | 157 |
| **total** | 594 | 379 | 1372 | 1280 |

`+filter` is `VISION_SHAPE_FILTER=1`: four arithmetic gates on area, aspect, solidity and bbox fill. It is scored from the cached geometry using the same `plausible_brick` predicate the pipeline calls; that filter runs strictly after containment suppression, so scoring it from the survivors is the same computation as a second segmentation pass, and `tests/test_real_report.py::test_shape_filter_matches_the_shipped_pipeline` pins the two together.

**2 of these counts hit `vision.segment.MAX_PIECES` (200) and are floors, not counts:** lego3.jpg/sam2, lego7.jpg/sam2. Those photos are the densest in the set. Raise the cap before quoting a number for them.

**A detection is not a brick.** Without labels we cannot say which column is closer to the truth — only that SAM 2 returns more objects than OpenCV and that the filter removes this many of them. Where the filter HAS been scored against labels (the separate set below, 10 images) it cost 0.884 → 0.816 recall and bought 0.887 → 0.985 precision. Whether that trade is right for these photos is unmeasured, which is why the filter ships off by default.

## Classifier confidence

Piece-weighted, from `data/real/inventory_all.json`. The bands are the pipeline’s own policy (`vision/pipeline.py`): >= 0.85 ships as confirmed, 0.50–0.85 is flagged for review with alternatives one tap away, < 0.50 is dropped to unknown and excluded from the solver.

| part score | the pipeline calls it | pieces | share |
|---|---|---|---|
| >= 0.85 | confirmed | 15 | 1% |
| 0.50-0.85 | needs_review | 626 | 48% |
| < 0.50 | unknown | 655 | 51% |

Unknown rate: **655/1296 = 51%**. Only 15 pieces cleared 0.85. The mass of this distribution sits in `needs_review`, which is the band the confirm loop exists for: one human correction re-ranks every similar ambiguous row (`vision/confirm.py`).

Colour is scored on its own single threshold, not these bands — the pipeline asks one question of it (trust this colour, yes or no) at 0.60:

| colour confidence | inventory records | pieces | share |
|---|---|---|---|
| >= 0.60 | `color_mode: exact` | 23 | 4% |
| < 0.60 | `color_mode: similar` | 618 | 96% |

Median colour confidence over rows: 0.18. On a patterned blanket under room light, colour is close to unusable as a hard constraint — which is the second, independent reason to pool across it.

## Runtime per stage

| backend | photos | read | segment | crop | colour | classify | total |
|---|---|---|---|---|---|---|---|
| opencv | 9 | 0.01 | 0.14 | 0.05 | 0.15 | 0.00 | 0.32 |
| sam2 | 9 | 0.01 | 5.68 | 0.12 | 0.71 | 0.02 | 6.58 |

Median seconds per 4000x3000 photo, measured by `python -m eval.real_report --measure` on the laptop that will run the demo (Apple silicon, MPS). `read` is JPEG decode plus the downscale to 1600 px that segmentation works on; `crop` cuts every piece at FULL resolution and PNG-encodes it; `colour` is one illuminant estimate per frame plus one median-LAB lookup per piece.

`classify` is the offline path: 1107 of 1966 crops were already in `data/brickognize_cache/` and were read from disk in that time. A crop that is not cached costs a network round trip, which is deliberately not measured here — the demo machine is assumed to have no network.

## Separately: the numbers we do have labels for

These are **not** measurements of the photos above. They come from the published Brickognize evaluation set, which ships ground-truth boxes, via `python -m eval.pile_eval <folder> --tag <name>`, which appends to `eval/results.tsv`.

| run | images | recall | precision |
|---|---|---|---|
| opencv-prec | 20 | 0.469 | 0.462 |
| sam2-prec | 20 | 0.905 | 0.822 |
| opencv-containment | 12 | 0.517 | 0.524 |
| synth-containment | 4 | 0.857 | 0.881 |
| sam2-final | 10 | 0.884 | 0.887 |
| filter-off | 10 | 0.884 | 0.887 |
| filter-on | 10 | 0.816 | 0.985 |

The classification columns in that file read 0.000 because the labelled set is class-agnostic — every box is just `brick`, with no part id — so it can score segmentation and cannot score naming. We print the zero rather than hide the column.

## Limits

- **No labels on our own photos.** No recall, no precision, no top-1 for them. The fix is an afternoon in CVAT producing one `.truth.json` per photo; it has not been done.
- **An inventory file does not record how it was made.** `inventory.json` and `inventory_all.json` carry no backend, no settings and no timestamp, so their detection counts cannot be reconciled with the table above with certainty: the one-photo inventory reports 74 detections for `lego.jpg`, which equals our sam2 +filter count and not our unfiltered 89 — suggestive, not evidence. One `provenance` field on the inventory would close this.
- **`MAX_PIECES` is 200** and the densest photos reach it, so their counts are floors.
- **Heaped bricks break both backends.** SAM 2 returned 82 masks for ~14 bricks on a heap, having boxed individual studs; containment suppression cut that to 34, which is still wrong. Single-layer capture is a stated operating condition.
- **Colour is the weakest stage**, 0.703 accuracy on high-confidence rows of the labelled set (`python -m eval.color_eval`), and on these photos most rows do not even reach the trust threshold. The inventory exposes `color_mode` instead of treating colour as a hard constraint for exactly this reason.
- **Brickognize returns BrickLink ids, not LDraw ids.** `vision/resolve.py` maps them; without it the commonest parts silently become unplaceable and vanish.

