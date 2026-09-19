# 07 — Tooling decisions (post-research)

Eight researchers + a completeness critic swept the LEGO software ecosystem: 90 findings, 87
verified by actually fetching the page. The critic then established that those 90 are really ~30
distinct items — three.js LDrawLoader appears 5×, LDCad shadow library 3×, LPub3D 3×, BrickGPT 3×.
**Weight accordingly: five entries agreeing about LDrawLoader is one fact, not five.**

Two foundation claims I verified myself, not via an agent:
- `bricknet` — **MIT, `requires_python >=3.10`**, 487 KB wheel, v0.1.0 uploaded 2026-06-13.
- `https://library.ldraw.org/library.csv` — live, real rows, columns
  `part_number, part_description, part_url, image_url, image_last_modified, category`.

---

## The headline: our differentiator is confirmed novel

The sweep found generative LEGO systems (BrickGPT/LegoGPT, legolization, BrickNet, Brick-by-Brick),
mature instruction generators (LPub3D, LeoCAD, Web Lic), and connection-metadata databases. It found
**nothing that generates a build constrained to a specific inventory of bricks you own.**

BrickNet's own paper states that generation "conditioned on a specified part set" is **future work**.

> **This reframes the pitch.** BrickGPT generates physically-stable LEGO from text — but it assumes
> an infinite supply of bricks. The constraint *"use only these 412 pieces"* is the entire problem,
> and it's the one nobody has solved. Say exactly that at the judging table.

Corollary, and it's uncomfortable: the components with no library are precisely the ones that matter
— inventory-constrained solving, step **computation** (every tool *reads* `0 STEP`; none computes
it), and the parametric subassembly generators, for which 90 findings produced **zero** prior art.
The research frees up about a day; that day belongs to those three, not to new scope.

---

## Verdict

### ADOPT — all MIT / Apache / BSD, no licence contamination

| What | Licence | Deletes | Verified |
|---|---|---|---|
| **`bricknet`** — bundled `labels.json.xz`: stud/anti-stud/pin/axle connector poses for **14,603 LDraw parts** | **MIT**, ≥3.10 | `build_part_meta.py` **entirely** | ✅ me, + 2 agents |
| **`library.ldraw.org/library.csv`** — official catalog: descriptions, categories, a hosted PNG per part | CCAL 2.0 | the parts.lst/mklist problem, the whitelist category filter, **and the parts-callout thumbnails** | ✅ me |
| **SAM 2** (`facebookresearch/sam2`) — pretrained class-agnostic segmenter, automatic mask generator | **Apache-2.0** | stage-1 training **and the entire BlenderProc synthetic pipeline** | ✅ critic |
| **BrickGPT** vendored files — `brick_structure.py` (236 lines), `brick_library.json`, `connectivity_analysis.py` (pure networkx, **no solver**), `mesh2brick/` | **MIT** | integer-grid model, overlap/support/connectivity checks, LDraw I/O, a voxel→brick tiler | ✅ agent |
| **three.js LDrawLoader** + `packLDrawModel` | MIT | the web viewer and step playback (already planned) | ✅ 5 agents |
| **LeoCAD CLI** — `-i -f -t --highlight --camera-angles --orthographic` | GPL-2 (**subprocess, not linked**) | per-step isometric renders with new-part highlighting | ✅ critic read the docs |
| **WeasyPrint** | BSD | PDF page assembly — no Qt, no OpenGL | ✅ critic |
| **OR-Tools CP-SAT** | Apache-2.0 | makes inventory a **hard solver constraint** instead of a post-hoc validator rule | ✅ critic |
| **PuLP + CBC** | MIT | the Gurobi escape hatch for stability | ✅ critic |
| **Brickognize API** | free service | part classification — **but see the warning below** | ✅ live-tested |

### REJECT — and the reason is cumulative, not individual

| What | Why not |
|---|---|
| `pyldraw3`, `legolization`, `hbmartin/rebrickable` | All three: **GPL-3.0-or-later + Python ≥3.12 + one author, 6 GitHub stars combined.** Adopting them in hour one means a forced runtime migration, a viral backend licence, and a critical path on unproven code — simultaneously, irreversibly, with no time budgeted to back out at hour 24. Individually defensible; together, disqualifying. Also: one agent *tested* pyldraw3 and found two identical 2×4 bricks at identical coordinates produced **zero** diagnostics — it does no solid overlap detection, so it doesn't replace the validator, only the easy third of it. And `legolization` explicitly has **no inventory constraints** — it accelerates everything except the thing we're making |
| **LPub3D as the primary manual path** | Rated "strong-accelerator" three times, and in all three the researcher admitted they **could not confirm headless operation**. A Qt/OpenGL desktop app nobody ran is not a foundation. Time-box it to 30 minutes as an experiment; LeoCAD + WeasyPrint is the default |
| **LegoSorterServer weights** | **No licence at all** on the repo, plus YOLOv5's AGPL-3.0 lineage. Download to benchmark against; never bundle |
| **Ultralytics YOLO** | AGPL-3.0 network copyleft. SAM 2 (Apache) does the job we actually need |
| **Training a 200-way classifier** | Deleted. See below |
| **B200C as a training set** | Doesn't survive arithmetic: 800k images in 1.19 GB is ~1.5 KB each — 64×64 thumbnails, not the "high quality" the title claims. Open one file before planning anything on it |

### BUILD OURSELVES — no library exists, verified

1. **Inventory-constrained generation.** Nobody has done it. It's the contribution.
2. **Class-agnostic pile segmentation.** Brickognize returns a **singular** `bounding_box` — confirmed
   in the live OpenAPI spec — so it's single-object recognition and cannot parse a pile. SAM 2 makes
   this cheap; it doesn't make it disappear.
3. **Step ordering.** Every tool reads `0 STEP`; none computes it. The lone exception, Web Lic, is
   not open source. Cheap on a stud grid — keep it.
4. **Parametric subassembly generators.** Zero candidates in 90 findings. This is where
   "build me a rover" either looks designed or looks like a blob. **Absorb the freed time here.**
5. **Overlap / support / stability.** Partly from BrickGPT's MIT files; the rest stays ours.

---

## Decide in the first 30 minutes, write it in the README

**Licence posture: MIT/Apache path.** (Runtime turned out to be Python 3.14 — the system one — so
the "forced 3.12 migration" objection to the GPL packages is moot. The copyleft and single-author
risks are not.) After this critique, a clean-licence option
exists at nearly every layer. Most hackathons require publishing the repo for judging, so this is
not deferrable. One line in the README; then never think about it again.

**⚠️ Brickognize warning the sweep buried:** every `predict/*` endpoint in its live OpenAPI spec is
marked `deprecated: true` — only `GET /health/` isn't. It's a free hobby service we'd hit ~60 times
live on stage. **Cache every response to disk from call one**, and keep a local fallback. It's still
the right call (it returns a part id *and* a colour id in ~0.4s with no key), but go in knowing this.

---

## What this does to the plan

### Deleted outright (~14–18 hours of work)

| Component | Replaced by |
|---|---|
| `build_part_meta.py` + hand-verifying 200 rows | `bricknet` labels.json |
| `render_dataset.py` (BlenderProc, physics piles, domain randomization) | SAM 2, pretrained |
| `convert_parts.py` GLB bake for training | not needed for training |
| Stage-1 segmenter training (~3 GPU-h) | SAM 2, pretrained |
| Stage-2 classifier training (~1 GPU-h) | Brickognize API |
| Custom instruction-page renderer, parts panel, PDF writer | LeoCAD → PNG → WeasyPrint → PDF |
| Custom LDraw parse/write | BrickGPT's MIT files |
| Part thumbnail rendering | `library.csv`'s hosted PNGs |

### Your Lambda credits

Honestly: **you now barely need them.** SAM 2 inference runs on a laptop; there's nothing left to
train. Keep them for (a) serving SAM 2 if laptop inference is too slow, which doubles as the Baseten
prize entry, and (b) TRELLIS (text→3D, MIT) if you chase the "voxelize an arbitrary mesh" path.
Don't invent work to justify them.

### The photo shoot shrinks

You no longer need 240 single-brick photos to fine-tune a classifier. You still want **~20 hand-
masked pile photos** as an eval set for the segmenter, and **20 known-contents piles** for
end-to-end accuracy. That's 40 photos and ~1 hour, down from ~2.5.

### Where the freed day goes

1. **Parametric subassembly generators** — 12 instead of 6–8, and better ones. No library exists;
   this is what makes the output look designed.
2. **Inventory-constrained tiling as a CP-SAT model**, so "uses only bricks you own" is a constraint
   the solver *cannot* violate rather than a check applied afterwards. This is the contribution;
   make it rigorous.
3. **The edit loop** — the best 20 seconds of the demo.

---

## Hour-one spike (90 minutes, before committing to any of this)

Run these four in parallel and let the results decide. Any that fails, fall back to the plan as written.

```bash
# 1. bricknet — does 3001 give sane studs?         (15 min)  ← everything hinges on this
pip install bricknet
python -c "import bricknet, lzma, json, importlib.resources as r; \
  d=json.loads(lzma.open(r.files('bricknet')/'_data/v1/labels.json.xz').read()); \
  print(list(d)[:5]); print(json.dumps(d.get('3001.dat') or d.get('3001'), indent=1)[:600])"

# 2. LeoCAD CLI — and find the output filename pattern for a step range  (20 min)
#    The docs do NOT document it. This is a known 20-minute trap — hit it in minute 5, not hour 20.
leocad -i out.png -f 1 -t 5 --highlight --orthographic --camera-angles 30 45 -w 1200 -h 900 test.ldr

# 3. SAM 2 automatic mask generator on one real pile photo  (30 min)
#    Expect over-segmentation: separate masks for a brick's top face, its studs, its shadow.
#    Post-filter on area bounds, aspect ratio, mask solidity, IoU NMS. Budget 2-3h for that filter.

# 4. BrickGPT vendoring — clone, copy 4 files, run their validator on a hand-built structure (25 min)
git clone https://github.com/AvaLovelace1/BrickGPT
#    Take: data/brick_structure.py, data/brick_library.json, stability_analysis/connectivity_analysis.py, mesh2brick/
#    Do NOT take stability_analysis/stability_analysis.py — it imports gurobipy at module top level
#    and the free pip Gurobi licence is size-capped; it will fail on a few-hundred-brick model at the
#    worst possible moment. Use PuLP+CBC if you need force analysis at all.
```

---

## Competitive awareness

**`ralco-max/brickwork`** (github) — AI-generated custom sets from an owned-parts inventory. Closest
thing to our premise that exists. Ten days old, 0 stars, no licence, TypeScript. Zero value as a
dependency; read the README for 10 minutes before the pitch so you're not surprised by a judge who
saw it. Our differentiation is the validator and the generated manual, not the idea.
