# 06 — Training the vision model

**The short version:** you don't photograph thousands of bricks. You *render* them from the LDraw
geometry you already need for the rest of the project, and you take ~200 real photos for
evaluation and a small fine-tune.

This is not a guess — it's the published result for this exact task.

> **Brickognize** (Vidal, Vallicrosa, Martí, Barnada — *Sensors* 23(4):1898, 2023) trained a
> Mask R-CNN on photo-realistic synthetic renders, then few-shot fine-tuned on **20 real images**
> from a controlled environment. Result: **AP50 91.33% uncontrolled, 98.70% controlled.**
> That's the same service the plan currently calls as an API. You're reproducing a known-good recipe.

---

## 1. Architecture: two stages, not one

Do **not** train a 200-class detector. Train a class-agnostic segmenter and a separate classifier.

```
photo of a pile
      │
      ▼
┌─────────────────────────┐   ONE class: "brick".
│  Stage 1: segmenter     │   Finds and masks every piece. Easy, generalizes, ~2h to train.
│  YOLO-seg / Mask R-CNN  │   Output: N instance masks + boxes
└───────────┬─────────────┘
            │ crop + mask each instance
            ▼
┌─────────────────────────┐   200-way part ID on a clean, centered, background-removed crop.
│  Stage 2: classifier    │   Much easier than detection-with-classification.
│  or embedding + kNN     │   Output: top-5 part candidates + scores
└───────────┬─────────────┘
            │
            ▼
  colour: NOT learned — computed from pixels (median LAB → nearest of ~40 common colours)
```

**Why split it:**
- A 200-class detector needs balanced boxes per class in cluttered scenes. A 1-class segmenter needs
  only "is this a brick" — it trains fast, tolerates fewer images, and generalizes to parts it never saw.
- The classifier sees a centered, background-subtracted crop. That's a dramatically easier problem
  than classifying a 40-pixel object in the corner of a pile.
- The two stages fail independently and observably, which matters for the confidence policy in
  `01-architecture.md` §6.2 — a good mask with a low-confidence class is a *different* UI state
  from a bad mask.
- Colour is a solved geometry/photometry problem. Learning it wastes capacity and breaks under
  new lighting.

### Stage 2 upgrade: embedding + gallery instead of a softmax

Train with **ArcFace / triplet loss** to an embedding space, then build a *gallery* of rendered
views per part and do k-NN at inference.

Why it's worth the extra hour: **adding a new part = rendering it and appending to the gallery.
No retraining.** Going from 200 parts to 2,000 is a render job, not a training job. That is a
genuinely strong answer to "how does this scale?" at the judging table, and it's roughly how the
commercial systems work.

Start with a plain 200-way softmax. Swap to ArcFace only if stage 1 is already solid.

---

## 2. Data: render it

### 2.1 Why renders beat photos here

| | Renders | Photos |
|---|---|---|
| Label cost | **zero** — the renderer knows every part, mask, pose, colour | ~30–60 s per image, by hand |
| Volume | 50k in an afternoon | 200 if you're dedicated |
| Instance masks on piles | perfect, free | brutal to label |
| Rare parts | as many as common ones | whatever's in your bin |
| Realism gap | **this is the one real cost** | none |

The whole game is closing the realism gap, and that's what domain randomization + a 20-image
fine-tune are for.

### 2.2 The renderer

**Use [BlenderProc](https://github.com/DLR-RM/BlenderProc)** — it's built for exactly this and writes
COCO-format instance annotations directly (`bproc.writer.write_coco_annotations`), so you skip the
worst part of the plumbing.

```
scripts/render_dataset.py   (BlenderProc)
├── import the ~200 whitelist parts from LDraw .dat   (ImportLDraw addon, or pre-convert to .obj/.glb)
├── assign a random official LEGO colour from LDConfig.ldr, with correct-ish plastic:
│     roughness ~0.25, slight clearcoat, ~5% of parts get transparent/pearl variants
├── PILE SIMULATION  ← the single most important realism trick
│     drop 15–60 parts onto a plane with rigid-body physics, bake ~60 frames, render the rest pose.
│     This produces the contact, occlusion and stacking of a real spilled pile.
│     Random scenes WITHOUT physics look obviously fake and the model learns the wrong prior.
├── domain randomization, per scene:
│     • HDRI environment lighting (grab ~30 free HDRIs from polyhaven)
│     • background: random photo texture (paper, wood, carpet, tablecloth) — include plain white,
│       since that's your capture UX, but don't ONLY train on white
│     • camera: elevation 45–90°, random azimuth, random distance, slight roll
│     • noise, motion blur, JPEG compression, exposure/white-balance jitter  ← phone-camera realism
└── outputs: image + COCO instance masks + per-instance {part_id, ldraw_colour, visible_fraction}
```

**Render engine: use EEVEE-Next, not Cycles.** ~0.1–0.3 s/image vs 1–3 s. 20k images is then well
under an hour instead of 6–16 GPU-hours. Render a small Cycles subset (~2k) and mix it in for
material realism. Domain randomization matters far more than path-traced accuracy.

Existing pipelines to crib from rather than write from scratch:
[brick-renderer](https://github.com/spencerhhubert/brick-renderer),
[lego-rendering](https://github.com/brianlow/lego-rendering),
[Multi-object-detection-lego](https://github.com/mantyni/Multi-object-detection-lego),
[BrickRegistration](https://github.com/GistNoesis/BrickRegistration).
Full list: [awesome-lego-machine-learning](https://github.com/360er0/awesome-lego-machine-learning).

### 2.3 Public datasets — use them to bootstrap, not as the whole plan

| Dataset | Contents | Annotations | Use it for |
|---|---|---|---|
| [Photos + renders of LEGO bricks](https://www.nature.com/articles/s41597-023-02682-2) (Nature Sci. Data, 2023) | **~155k real photos + ~1.5M renders** | classification | **The best real-photo source that exists.** Pre-train / fine-tune stage 2 |
| [B200C](https://www.kaggle.com/datasets/ronanpickell/b200c-lego-classification-dataset) (2021) | 800k renders, 200 parts | classification only, **64×64** | sanity-check the classifier; too low-res to be your main set |
| [B100/B200 detection](https://www.kaggle.com/datasets/ronanpickell/b100-lego-detection-dataset) (2024) | 2k renders | bounding boxes | quick stage-1 smoke test |
| [Lego Brick Sorting](https://www.kaggle.com/datasets/pacogarciam3/lego-brick-sorting-image-recognition) (2018) | 4,580 real photos, 20 parts | classification | real-domain validation |
| Tagged images with LEGO bricks (Gdańsk, 2021) | 2,933 photos + 2,908 renders | **bounding boxes** | real-domain stage-1 validation |

**Caveat that will bite you:** none of these use *your* 200-part whitelist or your class indices.
Treat them as pre-training and validation, and generate your own data for the classes you actually
place. Check each licence before shipping.

---

## 3. What to actually photograph (~1 hour of work, and worth it)

Three shot types, in descending value per minute:

| # | What | How many | Labelling cost | Purpose |
|---|---|---|---|---|
| 1 | **Single bricks**, one per photo, on white paper, ~6 angles each | 40 parts × 6 = **240** | **one label per photo** — free; name the folder after the part | fine-tune stage 2 on the real domain. This is the cheapest real data that exists |
| 2 | **Piles with known contents** — count out exactly what you drop, then photograph | **20** | a *set* label, not boxes | validates the whole pipeline end-to-end: "we said 47 parts, there were 48" |
| 3 | **Piles, hand-labelled with masks** | **20–30** | ~45 min total in CVAT/Roboflow | the few-shot fine-tune + your real eval set. 20 is the number from the Brickognize paper |

Shoot all three under varied conditions — your desk lamp, overhead room light, near a window, and
deliberately one bad one (harsh shadow, cluttered background). A model that has never seen bad
lighting will meet it for the first time at the judging table.

**Yes, take them yourself, and yes — send them to me.** Drop them in `data/real/` and I'll write the
loader, the fine-tune script, and the eval harness against them. What I can't do is take them.

---

## 4. Training recipe

### Stage 1 — segmenter

```bash
# Ultralytics, the fast path. NOTE: AGPL-3.0 — fine for an open-source hackathon repo,
# check it if you ever want this permissive. Permissive alternatives: torchvision Mask R-CNN (BSD),
# RF-DETR-Seg (Apache-2.0).
yolo segment train model=yolo11s-seg.pt data=bricks.yaml epochs=60 imgsz=768 batch=32 \
     hsv_h=0.02 hsv_s=0.6 hsv_v=0.5 degrees=180 scale=0.5 mosaic=1.0 close_mosaic=10
```

- 20–30k synthetic images is plenty for one class. More than 50k is wasted compute.
- `imgsz=768` — 640 loses 1×1 plates in a wide pile shot. Test both; pick with your real eval set.
- Freeze nothing; a class-agnostic head converges fast.
- **~1.5–3 h on a single A100/H100.** This fits inside the hackathon, which is the point.
- [YOLO26](https://docs.ultralytics.com/compare/yolo26-vs-yolo11)-seg (Jan 2026) is NMS-free with
  crisper mask boundaries and a big CPU-inference win; YOLO11-seg is the safer known quantity.
  Try 26 first, keep 11 as the fallback — same API, one string change.

### Stage 2 — classifier

```bash
# 200-way on 224×224 masked crops. Start here.
timm: convnext_tiny or efficientnet_b0, ImageNet-pretrained, 15 epochs
augment: random rotation (full 360°), scale, colour jitter, random erasing, background swap
```

- Train on **rendered crops produced by stage 1's own masks**, not on ideal isolated renders —
  the classifier must see the same crop distribution it'll get at inference, artefacts included.
- Then fine-tune on shot type #1 (your real single-brick photos). This is the few-shot step and
  it's where most of the real-world accuracy comes from.
- **~30–45 min on one GPU.** Cheap. Iterate here, not on stage 1.

### Evaluation — build this before you train anything

Three numbers, on real photos only:

1. **Recall of stage 1** on your 20–30 hand-labelled piles (are we finding the bricks?)
2. **Top-1 / top-5 of stage 2** on real single-brick photos (do we name them right?)
3. **End-to-end set accuracy** on shot type #2: |predicted multiset ∆ true multiset| / |true|
   — the only number that reflects what the user experiences

Log all three every run in a TSV. Synthetic validation accuracy will be ~99% and it means nothing;
only the real numbers move.

---

## 5. Compute budget

| Job | Cost |
|---|---|
| Render 25k pile images (EEVEE, GPU) | **~1–2 GPU-hours** |
| Render 2k Cycles images for material realism | ~1–2 GPU-hours |
| Stage 1 training, 60 epochs | **~2–3 GPU-hours** |
| Stage 2 training + fine-tune | ~1 GPU-hour |
| Experiments, restarts, the run you kill at epoch 3 | ×2 on all of it |
| **Total** | **~15–20 GPU-hours** |

That's small. Rendering is CPU-bound in Blender's scene setup as much as GPU-bound, so a machine
with many cores matters as much as the GPU tier — an A10G or L4 is plenty; an H100 is wasted here.

**Serve it on Baseten** and the vision lane doubles as a sponsor-prize entry
(`03-prizes-and-demo.md`, Tier 2) — the plan already specifies swapping the OpenCV segmenter for a
hosted model behind the same interface, so this drops straight into that slot.

---

## 6. Keep the fallback

**This does not replace the OpenCV + Brickognize path — it upgrades it.** Same interface:

```python
def segment(image) -> list[Mask]: ...          # opencv_segment  |  model_segment
def classify(crop) -> list[Candidate]: ...     # brickognize     |  model_classify
```

Pick the implementation with an env var. If the model underperforms at hour 30, you flip one
variable and demo the classical path. **Never delete the fallback.** Two implementations behind one
interface is also a much better slide than one.

---

## 7. Before you start: check the rules

Hackathons generally require *project code* to be written during the event, while datasets, public
pretrained weights and libraries are fair game. Training a custom model **beforehand** may count as
pre-existing work — check Hack the North's rules, or ask an organizer directly.

The good news: the numbers in §5 mean **you can render and train during the event**, which sidesteps
the question entirely and is a far better story. Write the render script and the training script at
the event; download the raw LDraw geometry, HDRIs and public datasets beforehand (that's data, not code).
