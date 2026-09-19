# What to photograph — read this on your phone

> Everything else is done. 314 tests pass, the backend runs end to end offline, and every
> dependency is installed. This is the last thing only you can do.

## STAGE 1 — do this now. 5 minutes, 5 photos, no labelling.

1. Tip out **30–40 bricks** onto a **plain light surface** (white paper, a plain table).
2. **Spread them into a single layer.** Nothing on top of anything else. Gaps between bricks.
3. Remove anything huge (baseplates, big plates) and anything Technic.
4. Phone **directly overhead**, fill the frame, keep the edges of the photo clear of bricks.
5. Take **5 photos**, moving the bricks around a bit between each.

Put them in: `data/real/spread/`

Then tell me, and I run the pipeline and show you the overlays. **This is the moment we find out
if it works on your bricks.**

---

## STAGE 2 — 20 minutes, after stage 1 looks sane.

**10 more spread photos** into `data/real/spread/`, varying:
- lighting: desk lamp · overhead room light · near a window
- surface: white paper · wood · whatever your demo table will be
- density: ~20 bricks, ~40 bricks, ~60 bricks
- **2 deliberately bad ones**: harsh shadow, cluttered background

**5 heaped photos** into `data/real/heaped/` — bricks piled on top of each other.
These are to *document the limit*, not to make it work. We expect these to score badly and we
will say so on stage.

---

## STAGE 3 — 45 minutes, only if we want hard numbers.

Label **boxes** (not masks — masks are discarded) around each brick in ~10 of the spread photos.

- Roboflow Annotate or CVAT, one class: `brick`
- Export **COCO**
- Then: `python -m eval.import_coco <export>.json --images data/real/labelled/ --map-categories`

Set a 45-minute timer and stop when it rings.

---

## Rules that actually matter

| Do | Why |
|---|---|
| **Single layer, gaps between bricks** | This is what Brickit tells its own users. Stacked bricks are invisible to the camera. |
| **Plain background, clear photo edges** | The segmenter learns the background from the border of the frame. |
| **NOT on a LEGO baseplate** | Measured: on a studded grey baseplate SAM 2 returned **155 detections for 12 parts** — it boxed every stud in the background. Paper, a plain table, a tea towel. Anything but studs. |
| **Good light, no harsh shadow** | Shadows read as bricks. |
| **Fill the frame** | A 1x1 plate in a wide shot is a handful of pixels. |

Don't bother with: a scale card, masks, or counting what's in each photo. Not needed.
