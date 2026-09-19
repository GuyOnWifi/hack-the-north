# 05 — Instructions & rendering

Turning a validated `Build` into something that looks like it fell out of a LEGO box.

Two distinct render setups, and keeping them separate is the whole discipline:

| | **Manual look** | **Display look** |
|---|---|---|
| Where | instruction pages, PDF | the hero viewer, the landing page |
| Camera | orthographic (or FOV ≈ 20°), isometric-ish | slight perspective, slow orbit |
| Material | flat / soft-shaded, **black LDraw edge lines** | physical, studio env map, roughness ≈ 0.25, light clearcoat |
| Ground | flat pale blue `#CFE3F4` (modern manuals; older ones sit nearer `#9EC4E8` — sample a real scan and use that exact value) | soft contact shadow (`<ContactShadows>` from drei) |
| Motion | new pieces drop in once when the step opens, then **stop** — the page should look printed | slow Y rotation ≈ 0.15 rad/s, pauses while dragging, resumes after |

**The black edge lines are most of the effect.** `LDrawLoader` gives you them for free, including
LDraw's *conditional* lines (the outlines that appear only on silhouettes). If you do nothing else
on this doc, do the edge lines — it's the single highest wow-per-hour item in the project.

---

## 1. Step sequencing — `core/sequence.py`

Input: a validated `Build`. Output: an ordered list of steps.

### 1.1 Order within a subassembly

Topological sort over the stud-contact graph with three constraints:

1. **Support:** a piece may only be placed after every piece it connects *down* to.
2. **Insertion sweep (the one people forget):** sweep the piece's voxel volume along its insertion
   direction (v1: straight down, from its final Y up to the top of the model). If any cell along
   that sweep is already occupied by a placed piece, the placement is physically impossible — the
   blocking piece must come later, or this piece earlier. This is what stops you telling someone to
   slide a brick *under* something they already built.
3. **Locality:** among the legal candidates, prefer the one with the most stud contacts to
   already-placed pieces, tie-break by proximity to the last piece placed. This produces the natural
   "keep building outward from what you just did" feel of a real manual.

```python
def order(parts, meta) -> list[Part]:
    placed, out = set(), []
    while remaining:
        legal = [p for p in remaining
                 if supports_placed(p, placed) and sweep_clear(p, placed, meta)]
        if not legal:                        # should be impossible on a valid build
            raise Unbuildable(remaining)     # ← if this ever fires, the validator has a hole
        out.append(max(legal, key=lambda p: (contacts(p, placed), -dist(p, out[-1] if out else p))))
    return out
```

That `raise Unbuildable` is a free extra validator. If it fires, you learned something real about
your model — don't paper over it.

### 1.2 Grouping into steps

- **1–6 pieces per step**, from the same subassembly and the same plate layer.
- Prefer grouping **identical parts** so the parts panel can say "**2×**", the way real manuals do.
- First three steps: keep them small (1–3 pieces). Gentle starts feel professional.
- Never leave a single orphan piece as the last step of a layer — merge it backwards.

### 1.3 Subassemblies

Each subassembly gets its **own framed callout box with its own step numbers** (1, 2, 3… inside the
frame), then a step in the main sequence showing it being attached as one unit. This is exactly what
real manuals do and it's the detail that makes people say "wait, that's a real manual".

Order: build subassemblies in dependency order (children before parents), main body last.

---

## 2. Camera per step

Naive fixed isometric works and is the fallback. The good version costs about an hour:

```
for each step:
  render the model-so-far to a 256×256 offscreen ID buffer from ~16 candidate angles
    (8 azimuths × 2 elevations), every piece a unique flat colour, no lighting
  score(angle) = visible_pixels(new pieces) / unoccluded_pixels(new pieces)
                 - 0.35 * angular_distance(angle, previous step's angle)
  pick the max
```

The penalty term matters as much as the visibility term: a manual that spins wildly between steps is
unreadable. When the chosen angle *does* jump a long way, draw the **rotate icon** in the corner —
again, exactly like real manuals.

Cache the ID-buffer renders; they're the same scene the step render uses.

---

## 3. Arrows — only when genuinely needed

Real manuals mostly just show new pieces in place. Draw an arrow only when the placement is
ambiguous, which is decidable:

```
ambiguous if:  visible_fraction(new piece) < 0.35        # it's hidden behind something
            or its final position is interior (no free face toward the camera)
```

Then: pull the piece back along its insertion direction by ~3 plates ("exploded" offset) and draw a
2D arrow from the offset position to the final one. Draw it as a **flat, slightly thick 2D overlay**
in screen space, not a 3D cone — it should read as manual art, not as geometry.

---

## 4. Parts panel

Top-left of each step page: a rounded panel in a slightly lighter blue than the background, listing
each distinct (part, colour) in the step with a small render and a "2×" count.

- Render thumbnails with the **same renderer**, fixed camera, transparent background, cached per
  (part, colour). Bake the common ones at build time.
- For long pieces (beams, plates 1×8+), add the **1:1 length ruler** real manuals print, so the
  builder can hold the piece against the page. Cheap, and it is a detail nobody else will have.

Big bold **step number** top-left above the panel; page-turn navigation at the bottom.

---

## 5. Performance (this is where a 3D hackathon project dies)

- **Pre-bake parts to GLB at build time.** `packLDrawModel` in the three.js examples does exactly
  this. Parsing raw `.dat` files at runtime is slow and gets slower with every part you add.
  Runtime `LDrawLoader` is fine for the dev loop with 12 parts on screen; ship the pack.
- **Cache geometry per part and material per colour.** One `BufferGeometry` per part, shared.
- **Instance the studs.** Studs are the majority of the triangle count in any brick model.
  `InstancedMesh` for stud geometry across the whole scene is the single biggest win available.
- Target: a 300-piece model at 60fps on a laptop with the projector plugged in. Test *with* the
  projector plugged in — external displays halve your framerate and always at the worst moment.
- Service-worker cache the GLB pack so the second load (and a wifi outage) is instant.

---

## 6. PDF export

**Client-side.** For each step: set the manual-look camera to the step's chosen angle, white or pale
blue background, render, `renderer.domElement.toDataURL('image/png')`, lay out with `jsPDF`.

```
┌──────────────────────────────────────────────┐
│  ┏━━━┓   ┌──────────────┐                    │
│  ┃ 7 ┃   │ ▪2×  ▪1×  ▪2×│   ← parts panel    │
│  ┗━━━┛   └──────────────┘                    │
│                                              │
│            ( isometric render )              │
│                                              │
│                              page 8 of 24    │
└──────────────────────────────────────────────┘
```

Plus a cover page (hero render, model name, total piece count, "built from your bricks") and a final
parts-list page. ~45 minutes of work for a wildly disproportionate payoff: **a PDF is a thing a
judge can hold.** If there's a printer at the event, print one and put it on the table.

Server-side rendering (Playwright against a headless viewer route) is the fallback if canvas capture
fights you over tainted textures. Decide by hour 26 and build exactly one of the two.

---

## 7. Branding note

Style the app as its own thing. Don't use the LEGO wordmark, logo or corporate font in your UI, your
name, or your slides, and put *"LEGO® is a trademark of the LEGO Group, which does not sponsor,
authorize or endorse this project"* in the footer. LDraw does ship logo-embossed stud variants for
realism — using them inside the 3D render is a deliberate choice you can make, but keep the marks
out of your own branding either way. Two minutes of care, zero downside.
