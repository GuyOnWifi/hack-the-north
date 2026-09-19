# Real photos

Drop phone photos here. Run `python scripts/check_photos.py data/real/` before you pack up.

**The shot list shrank after the ecosystem research.** You are no longer training a classifier
(Brickognize does it) or a segmenter (SAM 2 does it), so the 240 single-brick photos are gone.
What remains is evaluation data — the numbers that tell you whether any of this works.

| Folder | Target | What | Labelling |
|---|---|---|---|
| `known_piles/` | **20** | A pile you counted before photographing. Put a `contents.csv` next to each image: `part,color,qty` | ~1 min each |
| `labelled_piles/` | **20–30** | Piles to hand-mask in CVAT or Roboflow, one class: `brick`. Export as `<image>.truth.json` | 45 min total, set a timer |

`.truth.json` format (same as `scripts/make_test_pile.py` emits, so the eval harness reads both):

```json
{"image": "pile01.jpg", "pieces": [{"part": "3001", "bbox": [120, 340, 88, 52]}]}
```

## Shooting rules

1. **Plain background** — white paper, a plain table. The segmenter learns the background from the
   border of the frame, so a clean border matters more than a clean centre.
2. **Spread the bricks out.** Touching bricks are failure mode #1.
3. **Include the scale card** (a printed 40mm square). Scale is what turns "a rectangle" into "a 1×2".
4. **Vary the lighting deliberately**: desk lamp, overhead, near a window — and **at least three
   deliberately bad shots** (harsh shadow, cluttered background, slightly soft). A pipeline that
   has never seen bad input will meet it first at the judging table.

Then: `python -m eval.pile_eval data/real/labelled_piles/ --tag real-baseline`
