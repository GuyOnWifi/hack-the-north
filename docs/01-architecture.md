# 01 — Architecture

The core of this project is **not** the renderer and **not** the LLM. It is a strict, integer,
checkable model of a brick build. Build that first. Everything else is a consumer of it.

---

## 1. The build model (the thing everything depends on)

### 1.1 Coordinates: integers only, forever

| Axis | Unit | Real size | LDraw |
|---|---|---|---|
| X, Z | **1 stud** | 8 mm | 20 LDU |
| Y | **1 plate** | 3.2 mm | 8 LDU (brick = 3 plates = 24 LDU) |
| Rotation | **90° steps about Y** only | — | 4 discrete matrices |

No floats anywhere in the build model. No arbitrary rotation. `pos: [x, y, z]` are integers; `rot ∈
{0, 90, 180, 270}`. Floats appear exactly once, in `ldraw/write.py`, at export time.

> Everything good about this project comes from this constraint. Overlap becomes set intersection.
> Connection becomes integer adjacency. Diffs become meaningful. Undo becomes free. The LLM never
> touches a coordinate, so the LLM can never produce an invalid one.

### 1.2 The Build

```jsonc
{
  "id": "bld_01J...",
  "name": "Desk Rover",
  "version": 7,                      // every mutation bumps this; see 04-loop.md
  "parts": [
    { "id": "p12", "part": "3001", "color": 4, "pos": [2, 3, 0], "rot": 90, "sub": "chassis" }
  ],
  "subassemblies": {
    "chassis": { "parent": null,      "origin": [0,0,0], "attach": [ {"at":[2,3,1],"face":"top","studs":[[2,1],[3,1]]} ] },
    "cabin":   { "parent": "chassis", "origin": [2,3,0], "attach": [ ... ] }
  },
  "provenance": { "backend": "compose", "prompt": "a little rover", "seed": 41, "generators": ["chassis(10,4)","axle_pair(wheel_s)","cabin(open)"] }
}
```

- `3001` is Brick 2×4; `4` is red in LDraw color numbering. Part IDs are **LDraw part numbers**,
  which mostly coincide with BrickLink and Rebrickable IDs — that's why we use them everywhere.
- `sub` assigns every part to exactly one subassembly node. The tree is what makes editing and
  manual callouts possible (§6, `04-loop.md` §3).
- `provenance` is what lets you regenerate deterministically and what you show a judge when they
  ask "did the AI actually do this?".

### 1.3 Part metadata — generated once, at build time

For each of the ~200 whitelisted parts, from its LDraw `.dat` geometry:

```jsonc
{
  "part": "3001", "name": "Brick 2 x 4",
  "size": {"w": 2, "d": 4, "h": 3},              // studs, studs, plates
  "voxels": [[0,0,0],[1,0,0], ... ],             // cells filled, per plate layer
  "studs":      [[0,0],[1,0],[0,1],[1,1], ...],  // male connectors, top face, (x,z)
  "antistuds":  [[0,0],[1,0], ...],              // female, bottom face
  "insertion": "down",                           // v1: always "down"
  "rotations": [0, 90],                          // distinct results (2x4 has 2, 2x2 has 1)
  "ldraw_origin_offset": [ ... ]                 // grid-cell → LDraw part origin, computed once
}
```

Computed by `scripts/build_part_meta.py` by parsing each `.dat`, taking the bbox in LDU, dividing
by (20, 8, 20), and snapping. **Hand-verify all ~200 rows in a spreadsheet** — this table is the
foundation and a wrong row is a bug you will chase for three hours at 2am. It's 20 minutes of
tedium that buys a night of sleep.

*(For v2: LDCad's "shadow library" ships real snap metadata — `!LDCAD SNAP_CYL` and friends — for
most LDraw parts, which is how you'd get hinges, clips, axles and Technic without hand-authoring
connection data. Out of scope for v1; mention it when a judge asks "how would you extend this?")*

### 1.4 The whitelist

~200 parts: bricks 1×1…1×8 / 2×2…2×8, plates (same range + 4×4, 6×6, 6×8), tiles 1×1/1×2/2×2,
slopes 45° and inverted, 1×1 round, arch 1×4, wheels + axle holders, windscreen, a couple of SNOT
bricks. Stored in `data/core_parts.yaml`.

**No hinges, no Technic, no gears, no flex.** Insertion is always straight down. Say this limit out
loud in the demo — a stated limit reads as engineering judgment; an unstated one reads as a bug.

---

## 2. Validator — `core/validate.py`

Pure function, no I/O, no LLM, runs in microseconds on a few hundred parts. **Every** mutation from
**every** source goes through it. Generators, LLM edits, substitutions, and manual UI edits all call
the same function.

```python
def validate(build: Build, inventory: Inventory, meta: PartMeta) -> Report:
```

| # | Check | How | Failure mode it prevents |
|---|---|---|---|
| 1 | **No overlap** | occupy a `dict[(x,y,z)] -> part_id`; any collision is a fail, and the report names both parts | two bricks in the same space |
| 2 | **Supported** | every part needs ≥1 stud↔anti-stud contact with an already-placed part, or it rests on the ground plane (`y == 0`) | bricks floating in midair |
| 3 | **Connected** | union-find over the stud-contact graph; exactly one component | the model is secretly three separate objects |
| 4 | **In budget** | multiset of (part, color) ⊆ inventory | instructions that need bricks the user doesn't have |
| 5 | **Stable** *(optional, cheap)* | centre of mass over the support polygon; flag overhangs longer than 2 studs with no support below | it builds, then tips over |
| 6 | **Bonded** *(warn only)* | fraction of seams directly stacked on seams below; warn > 0.4 | it builds, then snaps in half when lifted |

The report is structured, not a boolean:

```jsonc
{ "ok": false,
  "errors": [ {"code":"OVERLAP","parts":["p12","p31"],"cell":[2,3,0],
               "human":"Brick 2x4 'p12' overlaps Brick 1x2 'p31' at stud (2,0), plate layer 3"} ],
  "warnings": [ {"code":"WEAK_BOND","sub":"wing","seam_score":0.62,"human":"The wing's seams stack; it will snap along that line"} ],
  "stats": {"parts":147,"studs_used":312,"inventory_remaining":265} }
```

That `human` field is not decoration — it's the message the fixer loop feeds back to the LLM
(`04-loop.md` §2), and it's what you show in the UI's "Structural check" panel. Write it well once.

**Test this harder than anything else.** Three hand-written bad builds (overlap / floating /
disconnected) and one good one, as unit tests, in the first two hours. If the validator is right,
nothing downstream can produce a model that doesn't exist.

---

## 3. LDraw I/O — `ldraw/`

We use LDraw as the interchange format because it's an open standard, its part IDs line up with
Rebrickable and BrickLink, three.js ships a loader for it, BrickLink Studio opens it, and it's
plain text.

### 3.1 The facts you need

- `1 LDU = 0.4 mm`; stud pitch 20 LDU; plate 8 LDU; brick 24 LDU.
- **−Y is up.** Stacking means *subtracting* from Y. This will bite someone; put it in a comment.
- Part reference (line type 1):
  `1 <color> <x> <y> <z> <a> <b> <c> <d> <e> <f> <g> <h> <i> <part>.dat`
  with the 3×3 matrix `[a b c; d e f; g h i]` applied before the translation. Identity is
  `1 0 0 0 1 0 0 0 1`; 90° about Y is `0 0 -1 0 1 0 1 0 0`.
- A standard brick's origin is at the **centre of its TOP face**; its body spans `y ∈ [0, +24]`,
  downward, because −Y is up. **Verified** against the real `3001.dat`, which contains
  `4 16 -40 0 -20 -40 24 -20 40 24 -20 40 0 -20`. bricknet agrees — studs at y=0, anti-studs at
  y=24. *(An earlier draft of this doc said "bottom face, y ∈ [−24, 0]". It was wrong, and this is
  exactly the class of assumption that costs three hours at 2am — which is why it got checked.)*
- `0 STEP` ends a build step, and `LDrawLoader` reads it natively: `group.userData.numBuildingSteps`
  and `child.userData.buildingStep` on every mesh. Your step viewer is ~15 lines because of this.
- Colors: parse `LDConfig.ldr` into a table at build time. Don't hardcode (`4` red, `15` white,
  `71` light bluish gray are the ones you'll type by hand while debugging).

### 3.2 Export

```python
def to_ldraw(build: Build, steps: list[Step], meta: PartMeta) -> str:
    # grid → LDU:  x_ldu = x*20 + meta.origin_off_x
    #              y_ldu = -(y*8) - meta.height_ldu     # remember: −Y is up
    #              z_ldu = z*20 + meta.origin_off_z
    # emit subassembly callouts as separate 0 FILE sections in an .mpd
```

Round-trip test (`parse → write → compare part refs`) is one of the three tests worth writing.

### 3.3 Import (for the `recall` backend)

Parse OMR `.mpd` files → snap every part reference to the integer grid → reject any model with a
part outside the whitelist or a rotation that isn't a multiple of 90°. You'll lose some models.
Fine. What survives is a corpus of real official sets, **with their real step data**, already in
your own build model and therefore editable and substitutable like anything else.

---

## 4. Where builds come from — three backends, one output type

All three emit a `Build` and all three are validated identically.

```
prompt + inventory ──► router ──┬──► recall()   real official sets that fit your bin
                                ├──► compose()  parametric generators, LLM-directed
                                └──► sculpt()   freeform voxel shape, LLM-designed
                                          │
                                          ▼
                                    validate() ──► fix loop (04-loop.md)
```

### 4.1 `recall` — retrieve a real set that fits (the floor; build this first)

Corpus: LDraw **OMR** (`omr.ldraw.org`) — official sets as `.mpd` with step data. Offline, embed
`name + theme + an LLM-written visual description` per model. At query time: embed the prompt, take
top 50 by cosine, then rank by **fit score**:

```python
def fit(model_parts, bin, rules) -> float:
    # greedy allocation, rarest-required-part first
    #   exact part + exact color           cost 0.00
    #   exact part, different color        cost 0.35   (0.05 if the part is internal — see below)
    #   substitution rule → N pieces       cost 0.20 * (N-1)
    #   nothing                            cost 1.00   → 'missing'
    # return 1 - total_cost / total_qty
```

The **internal-part discount** is worth the 20 minutes: a part fully enclosed by other parts is
invisible, so recoloring it is free. Computable straight from the occupancy grid. Without it,
colour substitution makes every model look like confetti; with it, the substitutions look deliberate.

Rank by `0.7 * fit + 0.3 * semantic_similarity`, return the top 3. Even with an empty LLM budget and
a broken camera, this path alone produces: "here are three real LEGO sets you can build tonight
from that pile, with manuals." That is already a demo.

### 4.2 `compose` — parametric generators (the reliable generator)

A library of hand-written Python generators. Each one returns valid placements on the grid and
declares its attachment points.

```python
@generator(tags=["vehicle", "base"])
def chassis(length: int, width: int, *, style: Literal["flat","lowered"]="flat") -> SubAssembly:
    """A rectangular plate-and-brick base. length/width in studs. Emits attach points on top."""
```

Ship ~12 of them: `chassis`, `axle_pair`, `cabin`, `wing`, `tower`, `wall`, `roof_gable`, `arch`,
`slab`, `fin`, `cockpit`, `turret`. Each: valid by construction, parameterised, inventory-aware
(it asks the allocator for parts and degrades — 2×4 → two 2×2 → four 1×2 — before giving up).

The LLM's entire job here is to emit a **composition**, never a coordinate:

```jsonc
{ "root": "chassis", "nodes": [
    {"id":"chassis","gen":"chassis","args":{"length":10,"width":4}},
    {"id":"axles", "gen":"axle_pair","args":{"wheel":"small"},"attach_to":"chassis","at":"bottom_front"},
    {"id":"cabin", "gen":"cabin","args":{"style":"open"},   "attach_to":"chassis","at":"top_rear"} ] }
```

Composition is a tool call with a strict schema. Invalid generator name or arg → schema rejection,
not a broken model.

### 4.3 `sculpt` — freeform voxel (the surprising generator)

For "a dog", "a dragon", "my initials" — things no parametric generator covers. The LLM emits the
shape as **layer-by-layer ASCII maps**, bottom to top:

```jsonc
{ "grid": {"w":12,"d":12}, "palette": {"R":4,"K":0,"W":15},
  "layers": ["....RRRR....\n...RRRRRR...\n...", "..."] }   // '.' = empty, bottom → top
```

Text in, text out — no coordinates, trivially parseable, human-inspectable, and it renders as a
preview *before* you tile it, so a wrong shape is caught in 200ms instead of after a full solve.

Then **legalize** it (`sculpt/tile.py`): per layer, per same-colour connected region, greedily place
the largest whitelisted part that fits and is still in the inventory; 20 randomized restarts; keep
the best by `-(pieces) - 3*(aligned seams below) + 2*(large pieces)`. Offset the scan origin on odd
layers so seams stagger like masonry. Greedy + restarts is milliseconds and good enough; OR-Tools
CP-SAT for exact minimum-piece tiling is a stretch goal, never a starting point.

### 4.4 The router

Cheap LLM call, or honestly just a keyword heuristic to start: structured noun ("car", "house",
"plane", "robot") → `compose`; organic/abstract → `sculpt`; "what can I build?" with no target →
`recall`. Always offer all three results in the UI if time allows — "here's a real set, here's one
we designed, here's one we sculpted" is a great screen.

---

## 5. Substitution — `core/substitute.py`

Used by every backend and by the fixer. Rules are declarative, hand-written once:

```yaml
- id: brick_1x4_to_2x_1x2
  from: {part: "3010"}                                  # Brick 1 x 4
  to: [ {part: "3004", dx: -1, dy: 0, dz: 0},           # offsets in GRID units, not LDU
        {part: "3004", dx:  1, dy: 0, dz: 0} ]
  penalty: 0.20
  weakens: true          # creates a seam; the bond check will notice and may warn
- id: brick_1x2_to_3x_plate_1x2
  from: {part: "3004"}
  to: [ {part:"3023",dy:0}, {part:"3023",dy:1}, {part:"3023",dy:2} ]
  penalty: 0.25
```

~40–60 rules covers realistic need. Applying one is integer arithmetic under the parent's rotation —
no matrices, because we're on the grid. The LLM may only *choose a rule id*; it never writes offsets.

---

## 6. Inventory

### 6.1 Sources, in the order you should build them

1. **Typed entry** — typeahead over the parts catalog. *Build this first.* The whole pipeline is
   developed against typed inventories, so CV is never on the critical path.
2. **Set import** — `POST /inventory/import-set {set_num}` joins Rebrickable's `inventories` +
   `inventory_parts` CSVs. Instant, offline, exact. "I have set 60321" → 300 parts.
3. **Seed script** — `scripts/seed_demo_inventory.py`, a canned realistic 500-piece home bin used by
   every test and by demo-safe mode.
4. **Photo recognition** — §6.2. Owned by one person, parallel, never blocking.

### 6.2 Photo recognition pipeline

**Capture UX is 80% of the accuracy.** Overlay with three rules: plain background, spread the bricks
out (touching bricks are failure mode #1), and include the printed scale card (a 40mm square) —
scale is what turns "a rectangle" into "a 1×2".

```
photo → segment (OpenCV)      LAB background estimate from the border ring → threshold →
                              morphology → distance transform + watershed to split touching parts
      → classify (Brickognize) POST api.brickognize.com/predict/parts/ multipart field `query_image`
                              → { items: [{id, name, score, external_sites, ...}] }
                              one call per crop, 8 concurrent, cached by SHA-256 of the crop
      → colorize (ours)        erode mask 3px → drop top 15% luminance (specular) and bottom 10%
                              → median LAB → nearest of ~40 common colors → conf = 1 - d1/d2
      → confirm (the user)     ← this step is mandatory and it is a feature, not a fallback
```

Brickognize identifies the *mold*, not the colour; do colour yourself. Restricting to ~40 common
colours kills the "Dark Azure vs Medium Azure" coin-flips that read as bugs.

**Confidence policy:**

| Part score | Behaviour in the bin |
|---|---|
| ≥ 0.85 | auto-accept, green chip |
| 0.50–0.85 | **Needs review** — amber, top-3 alternatives as one-tap buttons |
| < 0.50 | **Unknown** bucket — counted in the total, excluded from the solver |

Every row keeps its evidence: the crop thumbnail, the top-5 candidates with scores, and its
`source ∈ {photo, typed, set_import}`. Clicking a row shows the crop it came from. **That evidence
panel is a 20-minute build and it is the most convincing thing in the demo** — it's the difference
between "an AI guessed" and "a system that quantifies its own uncertainty".

Even Brickit — a shipped commercial product doing exactly this — needs a confirmation screen. Say
that at the table; it reframes your confirmation UI from weakness to correctness.

### 6.3 Reconciliation (LLM, once per batch)

One call over the whole batch (candidates + estimated sizes, not images) returning *suggestions*:
mold disambiguation by size ("crop 7 called 3004 at 0.51 but its footprint matches 3003"),
implausible colour/mold pairs, and cross-photo duplicate detection. Suggestions **never** auto-apply
— they surface in the UI with their reason string. Human in the loop, explicitly.

---

## 7. Stack

| Layer | Choice | Why |
|---|---|---|
| App | **Next.js 15 (App Router) + TypeScript + Tailwind**, deployed on Vercel | A URL you can hand a judge; phone camera via `getUserMedia` with no install |
| 3D | **react-three-fiber + drei + LDrawLoader**, two render setups (manual look / display look) | §`05-manual-and-render.md` |
| Core model | **Python 3.11 + FastAPI**: grid model, validator, generators, tiler, LDraw I/O, sequencer | OpenCV, OR-Tools and the PDF stack are Python-native |
| Assets | pre-baked **GLB per (part, color)** via `packLDrawModel`, served from `/public/parts/`, cached by a service worker | runtime `.dat` parsing is slow; studs dominate triangle count, so **instance them** |
| DB | Postgres (Neon/Supabase) for sessions + inventories; SQLite catalog file for the static parts/colors/OMR index | the catalog is read-only, ship it as a file |
| Blobs | S3 / R2 — photos, `.ldr`, renders, PDFs | |
| LLM | `claude-opus-5` behind `llm/client.py` (one adapter, `PROVIDER` env var) | see §8 and the prizes doc |

*(Electron was proposed for camera access and offline parts caching. Rejected: at a hackathon, an
installable desktop app is a liability at the judging table. The service worker covers offline;
`getUserMedia` covers the camera.)*

---

## 8. LLM layer — `api/llm/`

**Tool calls, not free text.** The tools *are* the API of the build system:

| Tool | Input | Returns |
|---|---|---|
| `propose_build` | prompt, inventory summary, generator catalog | a composition (§4.2) or a sculpt spec (§4.3) |
| `edit_subassembly` | build_id, node_id, instruction | a replacement composition for that node only |
| `swap_part` | build_id, part_id, reason | a substitution rule id |
| `explain_failure` | validation report | human-readable diagnosis (used in the UI, not in the loop) |

```python
# llm/client.py
client.messages.create(
    model="claude-opus-5",
    max_tokens=16000,
    system=SYSTEM,                       # catalog + generator list + rules; mark cache_control ephemeral
    thinking={"type": "adaptive"},       # NOT budget_tokens — that 400s on Opus 5
    output_config={"effort": "high"},
    tools=TOOLS,
    messages=msgs,
)
```

Gotchas that will otherwise cost you an hour each:
- `thinking={"type":"adaptive"}`; `budget_tokens` returns 400 on Opus 5.
- Structured output is `output_config={"format": ...}`; the old `output_format` param is deprecated.
- Stream (`client.messages.stream(...).get_final_message()`) for `sculpt` — it's a long output.
- Put the catalog + generator list + rule table in the **system** prompt with `cache_control`
  ephemeral. It's identical every call, so the fix loop gets cheap and fast.
- Keep `PROVIDER` switchable inside this one file (see prizes doc — the OpenAI sponsor prize wants
  their API powering the experience; a one-file adapter makes that a 30-minute change).

---

## 9. API surface

```
POST   /sessions                          → {session_id}
GET    /inventory                         → {items:[InventoryItem], totals}
POST   /inventory/items | PATCH | DELETE
POST   /inventory/import-set  {set_num}
POST   /photos  (multipart) → /photos/{id}/analyze → /jobs/{id}
POST   /inventory/reconcile               → {suggestions:[...]}

POST   /builds            {prompt, mode?} → {build_id}            # 04-loop.md owns what happens next
GET    /builds/{id}                       → {build, validation, steps_ready}
POST   /builds/{id}/edit  {node_id?, instruction}  → {build_id, version}
POST   /builds/{id}/undo | /redo
GET    /builds/{id}/model.ldr | /steps | /validation | /manual.pdf
```

---

## 10. Repo layout

```
hack-the-north/
├── PLAN.md  docs/
├── core/                    # ← the part with tests. pure python, no I/O
│   ├── model.py             # Build, Part, SubAssembly, Inventory  (dataclasses, frozen)
│   ├── meta.py              # part metadata table loader
│   ├── validate.py          # §2 — the law
│   ├── substitute.py        # §5
│   ├── generators/          # §4.2  chassis.py, wing.py, ...
│   ├── sculpt/              # §4.3  parse.py, tile.py
│   ├── recall/              # §4.1  corpus.py, fit.py
│   ├── sequence.py          # step ordering + insertion sweep (05-manual-and-render.md)
│   └── ldraw/               # parse.py, write.py
├── api/                     # FastAPI: routes, jobs, llm/, vision/, db
├── web/                     # Next.js: capture, bin, ask, manual, viewer, pdf
├── data/                    # gitignored: rebrickable csvs, ldraw lib, omr, catalog.sqlite
└── scripts/                 # fetch_data.sh, build_catalog.py, build_part_meta.py,
                             # pack_parts_to_glb.mjs, seed_demo_inventory.py
```

`core/` has no network, no database, and no framework imports. That is what makes it testable in a
hackathon, and it's why the validator can be trusted.

---

## 11. Data sources & credits

| Source | Gives you | Note |
|---|---|---|
| **LDraw parts library** (`ldraw.org`, complete.zip ~80MB) | `.dat` geometry, `p/` primitives, `LDConfig.ldr` colours | required by the GLB bake and the metadata script |
| **LDraw OMR** (`omr.ldraw.org`) | official sets as `.mpd` **with step data** | the `recall` corpus |
| **Rebrickable bulk CSVs** | parts, colors, sets, inventories, elements | set import + catalog; also `external_ids.LDraw` via their API v3 for the ID mapping |
| **Brickognize** (`api.brickognize.com`) | image → ranked part candidates, free, no key | be polite: cache aggressively, self-rate-limit, have a fallback |

Put a `CREDITS.md` naming all four, and this line in the footer: *"LEGO® is a trademark of the LEGO
Group, which does not sponsor, authorize or endorse this project."* Use no LEGO wordmark, logo or
font in your own branding — name and style the app as its own thing. Five minutes; judges notice.
