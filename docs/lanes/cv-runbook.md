# CV lane — runbook (you own this)

**Status: the pipeline is BUILT and tested.** 43 tests pass. What remains is your photos, your
eval numbers, and the decisions that follow from them.

```bash
# it works right now:
.venv/bin/python scripts/make_test_pile.py -n 14 -o data/test/pile01   # synthetic pile w/ truth
.venv/bin/python -m vision.pipeline data/test/pile01.png -o inv.json --debug /tmp/dbg
.venv/bin/python -m eval.pile_eval data/test/pile01.png --tag baseline
```

## Measured numbers — read the caveats, they matter more than the numbers

### ✅ SETTLED: nobody segments a heap, and the market leader says so out loud

Researched across Brickit, Rebrickable, BrickLink Studio, the sorting-machine builders and the
bin-picking literature. The verdict is unambiguous:

- **Brickit** — the closest product to ours — tells its own users to **spread**. Its classroom
  page (written for teachers who must get it right first time) reads verbatim: *"Simply spread the
  bricks over a table and let your class scan them."* A hands-on review states the preparation step
  even more plainly: *"level it all out so it is a one-brick-thick layer."*
- **Every LEGO sorting machine** pays for separation **in hardware** — vibrating feeders, step
  feeders, two-speed belts — precisely so bricks never sit on top of each other. Their vision
  stacks are consequently *simpler* than ours (Daniel West's is background subtraction plus
  `findContours`).
- **Our own classifier assumes it.** Brickognize's OpenAPI description reads *"Identify a LEGO®
  item from one or more images"* — one item per request, multiple views as an accuracy lever. It
  is a single-item API by contract.

> **So single-layer is not a compromise. It is the industry-standard operating condition, it is
> what the market leader instructs, and it is what our classifier's contract assumes.** Make it the
> documented happy path and say so on stage.

**Never shoot on a baseplate.** Measured on a CC-licensed photo of 12 parts laid on a grey
studded baseplate: SAM 2 returned **155 detections** — the real parts were found correctly, plus
~140 background studs. Containment suppression cannot help, because baseplate studs sit inside
nothing. A studded surface is the single worst background you can choose.

Copy the market leader's verb: **"scatter"**, not "dump". And copy its pre-steps — remove oversized
pieces, and refuse to generate below a minimum piece count (both now implemented).

### ⚠️ Heaped piles still break both backends (which is now a stated limit, not a bug)

An annotated dataset said SAM 2 scored **0.92 recall**. One *unlabelled* Wikimedia photo of a real
heaped pile showed it returning **82 masks for ~14 bricks** — it had boxed every individual stud,
including the moulded "LEGO" text on top of them. OpenCV was worse: 13 boxes, mostly studs plus one
giant box around the whole heap.

Why the dataset lied: its bricks are *scattered with clear gaps* (measured: only 1.59% of brick
pairs overlap anywhere in it). A heap is a different problem and nothing online contains one.

**Fix applied** — containment suppression (`suppress_parts`). IoU-based NMS cannot catch this: a
stud inside a 2×4 brick has IoU ≈ 0.02 with it, so every threshold keeps both. Testing *containment*
instead ("is most of this mask inside a bigger mask?") drops it. Heaped: 82 → 34 masks. Scattered
precision improved too (SAM 2 0.82 → 0.88, OpenCV 0.46 → 0.52) with no recall cost.

**But 34 masks for 14 bricks is still wrong.** Occluded bricks fragment. So:

> **Spreading the bricks out is LOAD-BEARING, not a nicety.** The capture UX must insist on a
> single layer with visible gaps, and the demo should show you tipping the bin out and spreading
> it — which is a better shot anyway. Heaped-pile support is a stated limit, not a bug to hide.

### Segmentation backends, measured on 20 real photos

| backend | recall | precision | per image |
|---|---|---|---|
| opencv | 0.52 | 0.52 | 0.09 s |
| **sam 2** (hiera_small, MPS) | **0.87** | **0.88** | 10.2 s |

**SAM 2 is now the default** when `SAM2_CHECKPOINT` is set; OpenCV is the automatic fallback.
Nearly double on both metrics. 10 s behind a progress bar is acceptable; 0.47 recall at a judging
table is not. *(An earlier version of this runbook said "if OpenCV recall is ≥0.8, don't install
SAM 2." OpenCV measured 0.47 on real photos, so that advice inverted.)*

### End-to-end

| dataset | n | recall | precision | top-1 | top-5 | set acc |
|---|---|---|---|---|---|---|
| synthetic piles (varied bg, colours, noise) | 4 | 0.86 | 0.88 | — | — | — |
| Brickognize "uncontrolled" (**real photos**), opencv | 20 | 0.47 | 0.46 | — | — | — |
| Brickognize "uncontrolled" (**real photos**), sam 2 | 20 | **0.90** | **0.82** | — | — | — |
| colour, real photos, high-confidence only | 723 | — | — | 0.703 | — | — |

**The synthetic row is one image.** It is a plumbing check, not a baseline, and treating it as one
is exactly how you walk into judging with a broken pipeline. The real-photo row is the honest
signal — and even it is not your scenario (see below).

### What the real-photo eval bought us

Running against real photos immediately exposed a bug the synthetic set completely hid:

- **Per-component watershed seeding.** The old code thresholded watershed seeds at
  `0.45 * dist.max()` **globally**, so one large brick raised the bar above every small brick's
  distance peak and they never got a seed. Real-photo recall **0.149 → 0.462**; synthetic recall
  also rose 0.86 → 1.00. A 3× improvement that no amount of synthetic testing would have surfaced.
- **White balance.** Colour confusions on real photos were all *warm* shifts (Black→Dark Brown
  132×, Light Bluish Grey→Medium Nougat 119×). Grey-world illuminant estimation on the full frame
  moved high-confidence colour accuracy **0.605 → 0.703** and turned the residual errors into
  *lightness* errors instead of hue errors. Headline colour accuracy stayed flat (0.364 → 0.356) —
  stated plainly because it is true.
- **Confidence is well calibrated.** High-confidence colour predictions are right 0.70 of the time
  versus 0.24 for low-confidence. That is the empirical justification for the confirm loop.

### Why you still cannot skip your own photos

The dataset above is `data/external/` (CC BY-NC-ND — evaluate locally, **never commit**). Its limits:

- **Nothing online has heaped bricks.** Measured across the two best real-photo LEGO datasets:
  only **1.59%** of brick pairs overlap at all. Both are *scattered* bricks with clear gaps. Our
  watershed stage exists specifically to split *touching* bricks, and nothing online exercises it.
- 800×600, median brick **33 px** across — a phone photo gives 300–600 px crops.
- All 71 part ids are **Technic** axles, pins and liftarms. Not one System brick like 3001 or 3023b.
- The Gdańsk "tagged images" set is 81.6% single-brick photos (2,392 of 2,933), and every box is
  the generic class `lego` with no part id.

So: **download to de-risk segmentation, shoot anyway.** Online data cannot test touching bricks,
System parts at real scale, your colour stage on real plastic, or your background estimator under
the venue's lights.

---

## What is built

| File | What it does |
|---|---|
| `vision/segment.py` | OpenCV pile segmentation: learns the background from the frame border (so it works on wood/carpet, not just white), Otsu threshold, morphology, watershed to split touching bricks, solidity filter. Plus a **SAM 2 backend** behind the same interface (`VISION_SEG=sam2`). |
| `vision/classify.py` | Brickognize client. **Every response cached to disk by crop hash** — the demo runs from cache. Concurrent, polite, never raises; failures degrade to `unknown`. |
| `vision/resolve.py` | **Brickognize (BrickLink) ids → LDraw ids.** See the trap below. |
| `vision/color.py` | LDraw palette from `LDConfig.ldr`, restricted to ~41 colours people own. Median LAB with specular highlights and shadow removed. Confidence = `1 − d₁/d₂`. |
| `vision/pipeline.py` | Photo(s) → Contract 1 `inventory.json`, with the confidence policy and per-row evidence. CLI with `--debug` overlays. |
| `eval/pile_eval.py` | The three numbers, appended to `eval/results.tsv` every run. |
| `scripts/make_test_pile.py` | Synthetic piles from real LDraw renders **with ground truth** — so you can measure before you own a single photo. |
| `scripts/check_photos.py` | Blur / resolution / busy-background check. Run it before you pack up. |

## The trap that would have cost you hours

**Brickognize returns BrickLink part ids; everything downstream speaks LDraw.** Measured against
known renders:

```
brickognize   ldraw     part
3023      ->  3023b     Plate 1 x 2      <- one of the commonest parts there is
3040      ->  3040b     Slope 45 2 x 1
3068      ->  3068b     Tile 2 x 2
```

Without `vision/resolve.py` those rows silently become unplaceable and vanish from the solver —
nothing errors, the inventory is just quietly wrong. The resolver also prefers the **plain** mould:
`3023a` is "plate 1×2 with flat pin", `3023b` is the plain plate, and naive alphabetical order
picks the wrong one.

---

## What you do next, in order

### 1. Shoot the photos (~1 hour, at home, good light)

The shot list **shrank**: no classifier to fine-tune means no 240 single-brick photos.

| Folder | Target | Labelling |
|---|---|---|
| `data/real/labelled_piles/` | **25** piles at 30+ bricks, **box-labelled** | ~3 min each |
| `data/real/known_piles/` | **15** piles you counted, each with a `contents.csv` | ~1 min each |

**Shoot them SPREAD OUT, in a single layer with gaps** — see the heaped-pile finding above. Shoot
5–10 heaped ones too, labelled as such, so you can state the limit with evidence instead of hedging.

**Draw BOXES, not masks.** `eval/pile_eval.py` matches at bbox IoU 0.30 and its `iou()` only ever
touches x/y/w/h — polygons are discarded on import. Drawing them wastes about 90 minutes. *(An
earlier version of this runbook said to hand-mask in CVAT. That was wrong.)*

25 piles × 30 bricks ≈ 750 labelled instances, which pins recall to roughly ±2.5pp. Total ~2 hours.

**Shoot them HEAPED, on your demo surface, under your demo light.** Touching bricks are the thing
no online dataset can test and the thing the judge will be watching. Then run
`python scripts/check_photos.py data/real/`, and import with:

```bash
python -m eval.import_coco <cvat-export>.json --images data/real/labelled_piles/ --map-categories
python -m eval.pile_eval data/real/labelled_piles/ --tag real-baseline
```

### 2. Get your real baseline

```bash
.venv/bin/python -m eval.pile_eval data/real/labelled_piles/ --tag real-baseline
```

**This number is the one that counts.** The synthetic 0.86 means the plumbing works, nothing more.

### 3. SAM 2 is already installed and is already the default

Nothing to do — `torch`, `sam2` and the `hiera_small` checkpoint are in place, and
`vision/segment.py` picks SAM 2 automatically whenever `SAM2_CHECKPOINT` is set:

```bash
export SAM2_CHECKPOINT="$PWD/data/models/sam2.1_hiera_small.pt"
export SAM2_CONFIG=configs/sam2.1/sam2.1_hiera_s.yaml
python -m eval.pile_eval data/real/labelled_piles/ --tag real-sam2      # uses sam 2
VISION_SEG=opencv python -m eval.pile_eval data/real/labelled_piles/ --tag real-opencv   # A/B
```

Run both against your photos. If SAM 2 wins there too, ship it and keep OpenCV for demo-safe mode.

### 4. The confirm loop is BUILT — `vision/confirm.py`

Confirm one ambiguous row and every similar-looking ambiguous row follows. Two bounded signals:
size similarity (the same mould at the same camera distance gives similar crops) and an ownership
prior (people own multiples). Guardrails: it can only re-rank toward a candidate the classifier
ALREADY proposed, it never overwrites a human confirmation, and every change records a reason the
UI can show. Five tests cover exactly those guarantees.

What is left is wiring it to the UI — which is lane C's side of the seam.

---

## Bail conditions

| Signal | Do |
|---|---|
| Real-photo recall < 0.6 | Fix the **capture UX** first — background, spacing, scale card. Not the model. |
| >40% of a photo comes back `unknown` | Same. Then check the debug overlay: are the masks wrong, or the classifications? |
| Brickognize starts failing | You already have a disk cache. Check `classify.cache_stats()`. Every `predict/*` endpoint is formally `deprecated: true` — this is a known risk, not a surprise. |
| T+20 and still tuning | Freeze. Go help the demo. |

## Prize hook

This lane is half the evidence for **Rox ($10K)**: noisy real-world input, conflicting sources
(mould guess vs colour estimate vs the user), incomplete data (the `unknown` bucket), and a
confidence policy that routes uncertainty to a human instead of guessing. The `--debug` overlay and
the per-row evidence are the exhibits.
