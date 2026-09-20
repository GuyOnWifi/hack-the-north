---
marp: true
theme: default
paginate: true
backgroundColor: "#F2F3F2"
color: "#05131D"
style: |
  section {
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    padding: 70px 80px;
  }
  h1 { color: #05131D; font-size: 62px; letter-spacing: -1.5px; margin-bottom: 8px; }
  h2 { color: #05131D; font-size: 40px; letter-spacing: -0.8px; }
  strong { color: #C91A09; }
  code { background: #DFDFDF; padding: 2px 6px; border-radius: 3px; }
  table { font-size: 26px; }
  th { background: #FFD500; }
  blockquote {
    border-left: 10px solid #C91A09;
    padding-left: 24px; font-size: 32px; font-style: normal;
  }
  .studs { letter-spacing: 6px; font-size: 30px; }
  footer { color: #6C6E68; }
---

<!-- _paginate: false -->

<span class="studs">● ● ● ●</span>

# BRICOLAGE

## Build anything from the LEGO you already own

<br>

Point a phone at a pile of loose bricks.
Ask for something. Get a **real instruction manual**
for a model made of **exactly those bricks**.

<br><br>

`Hack the North` · Lane A: computer vision

---

## Everyone has this bin

<span class="studs">● ● ● ● ● ● ● ●</span>

A thousand orphaned bricks. No sets. No manuals.
Nobody knows what to do with it.

<br>

**Rebrickable** tells you which official sets you could *almost* build.
**Brickit** suggests models from a scan.

Neither answers the actual question:

> What can I build **right now**, from **exactly this pile**?

---

## Nobody solves the constraint

Generative LEGO systems exist. We checked — properly.

| system | generates | constrained to your bricks? |
|---|---|---|
| BrickGPT / LegoGPT (CMU) | text → stable model | **no** |
| BrickNet (CVPR 2026) | 3D → brick model | **no** |
| legolization | mesh → bricks | **no** |
| Brickit | scan → ideas | partial, closed |

<br>

BrickNet lists this as **its own limitation**:

> *"our model … was effectively allowed an **infinite library of parts**"*

<br>

**That constraint is the entire problem. It's what we built.**

---

## The one idea everything follows from

<br>

> ## The LLM decides **what** to build.
> ## It never places a brick.

<br>

Builds live on an **integer stud grid** — X/Z in studs, Y in plates, 90° rotations.
A **deterministic validator** checks overlap, support, connectivity, and your inventory.

The model only ever picks: *which generator, which argument, which substitution.*
**Coordinates are computed by code.**

---

## The designer is creative. The inspector is infallible.

```
  prompt + your bin  ──►  DESIGNER (llm)  ──►  Build on the grid
                              ▲                      │
                              │                      ▼
                          repair  ◄────────  INSPECTOR (pure code)
                                                     │
                                                     ▼
                                       step sequencer ──► manual + PDF
```

<br>

**The verifier in this system is not a model.**

Most repairs never reach the LLM — they're arithmetic.

---

## Then we photographed real bricks

<span class="studs">● ● ● ●</span>

And everything broke.

<br>

**51% of detections came back unknown.**

<br>

The interesting part is *why*.

---

## The classifier was fine. The blanket wasn't.

Brickognize **never** returned nothing. **Never** scored below 0.50.
So the unknowns weren't bad classification at all.

461 of 505 failures were **two answers**:

<br>

### 🥖 "Bread / Baguette" ×282 · "Technic Axle 2L" ×179

<br>

We looked at the crops. **They weren't LEGO.**
They were the pattern woven into the blanket.

We hand-labelled **all 1,296 crops** to be sure:
**43% of detections were not bricks.**

---

## Four fixes. None of them a model.

| problem | cause | fix |
|---|---|---|
| 43% fake detections | patterned blanket, pegboard | **plain table** |
| 47% no answer | chat-compressed to 91px crops | **full-res originals** |
| 14% no answer | oblique viewing angles | **retry ladder** |
| 93% "needs review" | **our threshold, not the model** | **recalibrate** |

<br>

That last one stings: Brickognize scores **12/12 correct**, median **0.83**.
Our confirm bar was **0.85** — *above the typical correct answer*.

**We were flagging right answers for review.**

---

## 51% → 13% unknown

<span class="studs">● ● ● ● ● ● ● ● ● ●</span>

| surface | resolution | unknown |
|---|---|---|
| blanket / pegboard | full-res | **51%** |
| plain table | compressed | **53%** |
| **plain table** | **full-res** | **19%** |
| plain table + retry ladder | full-res | **13%** |

<br>

**Zero model training. Zero GPU hours.**

---

## What it does today

<br>

```
COLLECTION   1,219 pieces · 141 distinct parts · 118× brick 2x4

rover        20 parts   valid   6 steps
house        35 parts   valid   8 steps
tower        24 parts   valid   7 steps
             over-spend: 0
```

<br>

Every build uses **only bricks we actually hold** — verified against the
collection independently of the solver.

→ `manual.pdf` · `model.ldr` · 391 tests passing

---

## What we'd tell you before you ask

<span class="studs">● ● ● ●</span>

**We find about 85 bricks per photo — not all of them.**
Misses cluster where bricks touch. Recall is the open problem.

**~0 false positives.** That's the error that matters:
a phantom brick produces instructions you *cannot follow*.
A missed brick just makes the model smaller.

**We say when we're unsure.** Every row carries its confidence,
the crop it came from, and its runner-up guesses.

**No Technic, no hinges, ~200-part whitelist.** Stated, not hidden.

---

## The pattern

<br>

Four times tonight something looked like *"we need a better model."*

<br>

Four times it was **a blanket, a compression setting, a missing retry,
and a wrong constant.**

<br>

> The only honest model finding ran the other way —
> the classifier was right more often than we were giving it credit for.

---

<!-- _paginate: false -->

<span class="studs">● ● ● ● ● ● ● ●</span>

# Tip out your bin.

## Take one photo.

<br>

**Build something tonight.**

<br><br>

`bricolage` · Hack the North
