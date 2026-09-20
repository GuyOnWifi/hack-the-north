# EDITING.md — the part-level edit contract (Pipeline C)

Two engineers build against this file in parallel without talking: **BE** (Python) and **FE** (web).
The only shared surface is this document. If something here is wrong, fix the document first.

Goal: every model the user can open is editable like a scene in Unity (tap, move, turn, recolour,
duplicate, delete, add) and in plain language, in seconds, and no edit can ever produce a model that
overlaps, floats or falls over more than it already did.

---

## 0. Facts found in the code that shape this design (verified, do not re-litigate)

1. `check.check_world` only tests collisions **across bodies** (`parts[o].body != p.body`) and has
   **no connectivity check at all**. A loaded `.ldr` has one body, so today's function would find
   nothing. The gate needs an all-pairs mode and a new connectivity check (section C).
2. `kit.G[pid]` raises `KeyError` for any part outside the 50-part kit. `web/public/models/*.mpd`
   (car, lunar, radar-truck) use ~40 parts outside it (4315, 3641 tyre, 4624 wheel, 3823 windscreen…),
   embed their own part geometry as `0 FILE` blocks, and lunar/radar-truck reference **sub-models**
   (`1621 - Vehicle.ldr`). Their main model is the text **before the first `0 FILE`**, preceded by
   an LDConfig colour table.
3. Finished models are **not clean**. Under a strict stud rule `bunny.ldr` has 68 components,
   `horse.ldr` does not stand (margin −16.6), and the car's tyres sit inside their wheels. So the
   gate is **baseline-relative**: an edit may not make anything *worse*; it is not required to fix
   what was already there. `a-fox.ldr` (96), `cat.ldr` (311) and `dog-holding-an-umbrella.ldr` (240)
   are fully connected with 0 collisions — use those for tests (`dog-holding…` does not stand).
4. `Session.tree_ascii()` does `v.op["edit"]` for every non-build op, which is a `KeyError` for
   `edit_c` ops: after any C edit `_payload()` throws and the API answers 500. BE fixes it (F.4).
5. The name `Session.edit_direct(op)` is already taken (engine-A replay). The new method is
   `Session.edit_parts` (D.0).
6. `build_json` ships all of `provenance`, which now includes the LDraw text and an embedded part
   library (up to 560 KB). BE drops `ldr` and `lib` from the serialised provenance.
7. The frontend `PartNode` list is built by walking the loaded scene for top-level `*.dat` groups in
   file order; `web/public/ldraw/parts.pack.ldr` carries every LDraw colour (incl. all `Trans_*`),
   so any colour code in the pack renders.
8. Timing measured on this machine: `check_world` + `stands` on 1642 parts = 0.23 s; a stud graph on
   the same model = 0.06 s. A full gate per dry-run is affordable; a full gate per settle candidate is
   not (section C.3 uses a cheap local test first).

---

## 1. Units, axes, words

| thing | value |
|---|---|
| 1 stud | 20 LDU on X and Z |
| 1 plate | 8 LDU on Y; 1 brick = 3 plates |
| up | LDraw **−Y**. In every op `dy > 0` means **up**; code converts (`y_ldu -= 8*dy`) |
| quarter turn | +1 = 90° about the vertical axis, `kit.rot_y(1)` |
| direction enum | `right=+X  left=−X  up  down  forward=−Z  back=+Z` (forward = toward the default camera, `ISO` in ModelView) |

All op fields are JSON **integers**. A JSON float, a numeric string, or a bool where an int is
expected is a schema error (HTTP 400), never rounded.

**Upright part**: its 3x3 rotation is a pure quarter turn about Y (every entry within 1e-6 of
−1/0/1, `R[1][1] = 1`, det = +1). Everything else (SNOT, hinged, wheels on their side) is **tilted**.

---

## A. Part identity

**A.1 Line index.** `line` = 0-based index of a part among the **type-1 lines of the main model
text**, in file order. Invariant (already true, now a contract): `build.parts[i]` ↔ type-1 line `i`
↔ FE `PreparedModel.parts[i]`. The served model is always flat (sub-models are flattened at load,
D.3), so FE's scene walk yields exactly one `PartNode` per type-1 line.

**A.2 Id.** `id` is a string, stable across versions made by direct edits:

- A model built by brickify, rebuilt from a brief, or loaded by `load_ldr` assigns `p{line}` at that
  moment (as `engine_c.from_result` does today).
- A direct edit keeps the id of every surviving part, whatever happens to its `line`.
- `delete` retires ids; they are never reused.
- `duplicate` and `add` mint `n{k}`; `k` comes from `provenance["next_id"]` (int, starts at 0, +1 per
  new part, copied forward to the child version). New ids of one op are minted in the order of the
  op's `ids` list. Replay repeats the same ops, so it mints the same ids.
- A brief-level rebuild (`edit_c`) resets ids to `p{line}` and `next_id` to 0 (see F.3 for how earlier
  direct edits are carried over).

**A.3 Picked mesh -> id (FE).** Raycast hit -> walk `object.parent` up to the `PartNode.object` ->
its index in `PreparedModel.parts` is `line` -> `table.parts[line].id`. FE must verify after every
load: `model.parts.length === table.count` and `model.parts[i].part === table.parts[i].part` for all
`i`. On mismatch FE disables picking and shows, verbatim: *"I can't line this model up with its
piece list, so tapping is off. Typing a change still works."* (never guess).

**A.4 Line order after an edit** (so `0 STEP` and the manual stay sane):

- Untouched lines keep their text **byte for byte** and their relative order.
- `recolour`: only the colour token of the line changes. `rotate`/`move`: the line is rewritten in
  place **unless** the part now rests on a part that comes later in the file; then the line moves to
  directly after the last such supporter (same step as that supporter).
- `duplicate`/`add`: the new line goes directly after its last supporter; with no supporter
  (resting on the ground) it is appended as a new final step.
- `delete`: the line is removed. A step left with no parts loses its `0 STEP`.
- "Supporter of P" = a part connected to P (C.1) whose body-box centre is lower than P's.
- The text always ends with `0 STEP\n`. Header lines (everything before the first type-1 line) are
  kept verbatim.
- Rewritten lines use: `1 {colour} {x} {y} {z} {a} {b} {c} {d} {e} {f} {g} {h} {i} {ref}` with every
  number formatted `fmt(v) = format(round(v, 3) + 0.0, ".10g")` (so `-0` prints as `0`), and `ref`
  kept verbatim from the source line (`parts/3024.dat` stays `parts/3024.dat`). New `add` lines use
  `{pid}.dat`.

---

## B. The part-level edit core

**B.0 Where it lives, and why.** Two new pure modules in **`brickify/brickify/`**, because all the
geometry they need (`kit.Geom`, `check._samples`, `check.stands`, `PartOut`) lives there, brickify has
no dependency on `bricolage/`, and `bricolage` already imports brickify through `engine_c`. No
network, no model calls, numpy/scipy only.

- `brickify/brickify/partlib.py` — geometry, studs, name and kind for **any** part (B.1).
- `brickify/brickify/edits.py` — parse, ops, gate, settle, cascade, write (B.2–B.4, C).

Natural language is not core: it lives in `bricolage/nl_c.py` (section E).

### B.1 `partlib` — never crash on an unknown part

```python
def load_library(*texts: str) -> dict[str, list[str]]   # "0 FILE name" blocks -> lines; keys lower-cased, '\\'->'/'
def pack() -> dict[str, list[str]]                      # web/public/ldraw/parts.pack.ldr, cached; {} if missing
def pid_of(ref: str) -> str                             # "parts/3024.DAT" -> "3024"
def info(pid: str, lib: dict) -> PartInfo               # cached per (pid, id(lib))

@dataclass(frozen=True)
class PartInfo:
    pid: str; name: str; kind: str        # kind in: brick plate tile slope round wedge hinge bar wheel tyre window minifig other
    size: tuple[int, int, int]            # studs X, plates Y, studs Z (ceil of the body box)
    source: str                           # "kit" | "derived" | "described" | "fallback"
    box: tuple[float, float, float, float, float, float]   # x0,x1,y0,y1,z0,z1 LDU, part-local, studs excluded
    studs: tuple      # ((x,y,z),(ax,ay,az)) stud base + outward axis, part-local
    antistuds: tuple  # ((x,y,z),(ax,ay,az)) receptor point + the axis a stud must have to enter it
```

Resolution order, first hit wins:

1. **kit** — `pid in kit.G`. Box from the Geom exactly as `check._samples` does today. Studs: if
   `studs_on_top`, one per 20-LDU lattice point of the footprint (`x0+10, x0+30, …`) on the top face,
   axis `(0,-1,0)`; plus `kit.SIDE_STUDS[pid]` with axis `(0,0,-1)`. Antistuds: the same lattice on the
   bottom face, axis `(0,-1,0)`; none for `3938` and `30374`.
2. **derived** — the part's file is in `lib` (the model's embedded blocks) or `pack()`. Follow
   `~Moved to X` headers. Walk type-1 refs recursively (depth ≤ 8, ≤ 20 000 vertices, else stop and
   use what was gathered): box = bounds of all type-3/4 vertices **not** under a `stud*.dat` ref;
   studs = origin + local −Y axis of every `stud.dat / stud2.dat / stud2a.dat / studp01.dat / studel.dat`
   ref; antistuds = the 20-LDU lattice on the box's +Y face if the box is within 2 LDU of whole studs
   on X and Z, else none.
3. **described** — no geometry, but the header has `N x M`: a box `N x M` studs, 3 plates high for
   `Brick`, 1 otherwise, origin top; studs/antistuds as for a kit rectangle.
4. **fallback** — a 1x1 brick box (20 x 24 x 20, origin top), no studs. The load tape says, as a
   `warn`: *"I don't know the shape of part {pid}, so I'm treating it as a 1x1 brick."*

`name` = the kit name, else the file's first line with runs of spaces collapsed and a leading `~`/`=`/`_`
stripped, else `Part {pid}`. `kind` = first match on the lower-cased name: `tyre|tire`→tyre,
`wheel`→wheel, `windscreen|window|glass`→window, `minifig`→minifig, `hinge`→hinge, `bar `→bar,
`wedge|wing`→wedge, `slope`→slope, `round`→round, `tile`→tile, `plate`→plate, `brick`→brick, else other.

So that `check_world`/`stands` keep working unchanged, BE makes `check._samples(pid)` consult
`partlib` for pids not in `kit.G` (BE adds optional `y0/y1` to `Geom` or routes `_samples` through
`PartInfo.box`; BE's choice, `kit.G`'s existing entries must not change).

### B.2 `edits` — data and entry points

```python
@dataclass(frozen=True)
class EPart:
    id: str; pid: str; ref: str; colour: int; body: str
    M: tuple            # 16 floats, row-major world transform (tuple so the dataclass stays frozen)
    step: int; text: str | None      # text = the verbatim source line while untouched

@dataclass(frozen=True)
class Model:
    header: tuple[str, ...]; parts: tuple[EPart, ...]; lib: dict; next_id: int

@dataclass(frozen=True)
class Result:
    accepted: bool
    code: str | None; human: str
    model: Model | None; ldr: str | None         # None when rejected
    ops: tuple[dict, ...]                        # RESOLVED ops (F.1); () when rejected
    changed: tuple[str, ...]; added: tuple[str, ...]; removed: tuple[str, ...]
    landed: tuple[dict, ...]; culprits: tuple[str, ...]; offer: dict | None
    stability: dict; events: tuple[dict, ...]    # events = (actor, kind, text, status) for the tape

def parse(ldr: str, ids: list[str] | None = None, bodies: list[str] | None = None,
          lib: dict | None = None, next_id: int = 0) -> Model
def flatten(text: str) -> tuple[str, str, list[str]]   # any .ldr/.mpd -> (main_ldr, lib_text, bodies per line)  (D.3)
def write(model: Model) -> str
def apply(model: Model, ops: list[dict], seed: int = 0) -> Result   # THE one path; runs the gate; never mutates
def gate(before: Model, after: Model, touched: set[str]) -> dict    # C.2
def stability(model: Model) -> dict                                 # D.4 shape
def table(model: Model) -> dict                                     # D.2 shape
```

`apply` is the only way a Model changes. It validates the op list (B.3), applies ops **in order** on
a working copy, settles where asked (C.3), runs `gate(before, after, touched)` **once on the final
state**, and returns either a new `Model` + `ldr` or a rejection that changed nothing. `seed` is
accepted for invariant 9 and is unused today (every search below is ordered, not random).
`check.resolve()` must **never** run on a parsed/edited model: it deletes parts.

### B.3 Ops — exact JSON

Common: `ids` is a non-empty list of 1–256 distinct existing ids. Instead of `ids` a request op may
carry **one** selector; the server expands it to `ids` before applying:

```json
{"body": "head"}      {"colour": 25}      {"part": "3024"}      {"all": true}
```

| op | request JSON | notes |
|---|---|---|
| move | `{"op":"move","ids":["p4","p5"],"d":[2,0,-1],"settle":true}` | `d=[dx,dy,dz]`: studs, plates (**+ up**), studs; each in −60..60, not all 0. `settle` default `true`. |
| rotate | `{"op":"rotate","ids":["p4"],"quarters":1,"settle":true}` | `quarters` in 1..3. |
| recolour | `{"op":"recolour","ids":["p5","p6"],"colour":33}` | `colour` = an LDraw code present in the pack's colour table, not 16/24. |
| delete | `{"op":"delete","ids":["p9"],"cascade":false}` | `cascade` default `false` (C.4). |
| duplicate | `{"op":"duplicate","ids":["p4"],"d":[0,3,0],"settle":true}` | copies, then moves the copies by `d` (default: up by the group's height in plates). |
| add | `{"op":"add","part":"3001","colour":4,"on":"p12","quarters":0,"settle":true}` | `part` must be in `kit.G` **and** in the pack. `on` = an id or `null`. |

Geometry, all computed by code:

- **move, upright parts:** translate by `(20*dx, -8*dy, 20*dz)` LDU in world axes.
  **Tilted parts:** the step is taken along the part's own lattice so it stays on its body's studs:
  for each non-zero world component pick the part-local axis (±x, ±y, ±z) whose world direction has
  the largest dot product with it and step `20` LDU (local x/z) or `8` LDU (local y) per unit along
  it. A group containing both upright and tilted parts moves each by its own rule only if every
  tilted part's chosen axes are within 1° of the world axes; otherwise reject `MIXED_TILT`.
- **rotate:** one part: rotate about its own origin around its local up axis, then re-snap: let `c0`
  be the footprint box min corner (local x,z) before and `c1` after the turn, both in the pre-turn
  frame; translate by `((c0 - c1) mod 20)` mapped into `(-10, 10]` per axis. (A 1x2 turned once
  shifts by (+10,+10) LDU; a 2x4 shifts by 0.) Several parts: rotate the group rigidly about the
  vertical line through the group's body-box centre snapped to the nearest multiple of 10 LDU, then
  apply the same re-snap using the group's first part (by `ids` order) and shift the whole group by
  it. Groups containing tilted parts rotate about world Y with no re-snap and must pass the gate as is.
- **duplicate:** body = the source's body; colour, ref, rotation copied.
- **add:** upright, `kit.rot_y(quarters)`. With `on`: the new footprint's min corner sits on `on`'s
  footprint min corner, bottom face on `on`'s top face; body = `on`'s body. With `on: null`: centred
  (snapped to the 20-LDU lattice of the model's first upright part) over the model's body-box centre,
  bottom one plate above the model's highest point; body = the body of whatever it settles onto.
  `add` always settles.

Budgets: ≤ 16 ops per request, ≤ 256 ids per op, ≤ 5000 parts per model. Over budget = HTTP 400.

### B.4 Rejection codes and their `human` copy (shown verbatim in the UI)

| code | human (template) |
|---|---|
| `COLLIDES` | "That would push it into the {name} next to it. Nothing was changed." |
| `FLOATING` | "There's nothing there for it to click onto, so it would just float. Nothing was changed." |
| `NO_SPOT` | "I looked for a free spot nearby and couldn't find one that holds. Try somewhere else." |
| `WOULD_FALL` | "Removing that would leave {n} pieces with nothing holding them up ({list}). Remove those too?" (for move/rotate: "Moving that would leave …. Nothing was changed.") |
| `TIPS` | "That would make it tip over toward the {side}. Nothing was changed." |
| `TIPS_WORSE` | "It already leans, and that would make it lean more. Nothing was changed." |
| `EMPTY` | "That would remove every piece." |
| `MIXED_TILT` | "Those pieces sit at different angles, so they can't slide together. Move them one group at a time." |
| `UNKNOWN_ID` | "One of those pieces isn't in the model any more." |
| `STALE` | "The model changed while you were doing that. Try again." |
| `NO_MODEL` | "Open a model first." |

`{list}` = up to 3 `"{count} {name}"` groups, largest first. `{side}` = `front/back/left/right` from
`stands()`'s `-z/+z/-x/+x`. Success copy is in D.1.

---

## C. The gate, settle, cascade

### C.1 Connection graph

`edge(A, B)` exists if any of:

- **(s) stud:** a stud of A is within 2 LDU of an antistud of B (world space) and the stud's world
  axis · B's antistud world axis ≥ 0.99 — or the same with A and B swapped;
- **(x) interlock:** `{A.pid, B.pid}` is in `check.EXEMPT` and their sample clouds share a bucket;
- **(c) contact, only if A or B has `source != "kit"`:** their body boxes grown by 1 LDU share ≥ 3
  buckets of the 4-LDU lattice. (We do not know where a windscreen's studs are; touching counts.)

`ground` = the largest world Y over all parts' body samples. A part is **grounded** if its samples
reach within 8 LDU of `ground`. `loose(model)` = ids of parts in a component with no grounded part.

### C.2 `gate(before, after, touched)` — one gate, always, baseline-relative

Run all three; the first failure in this order is the verdict:

1. **Collisions.** All-pairs, same body included: BE adds `check_world(parts, detail=True,
   same_body=True)` (default `False` keeps today's behaviour for brickify). A colliding pair is
   identified by its two ids. Reject `COLLIDES` if `pairs(after) − pairs(before)` is non-empty.
   `culprits` = the untouched parts in the new pairs.
2. **Connectivity.** `new_loose = loose(after) − loose(before)`. If any `touched` id is in
   `new_loose` → `FLOATING`; else if `new_loose` non-empty → `WOULD_FALL` with `culprits = new_loose`.
   A touched part that was loose before and still is → `FLOATING` too (a move must end attached).
3. **Stands.** `s0 = stands(before)`, `s1 = stands(after)`. `s0.stable and not s1.stable` → `TIPS`.
   `not s0.stable and s1.margin < s0.margin − 0.01` → `TIPS_WORSE`.

Returns `{"ok", "code", "culprits", "new_pairs", "new_loose", "stands": s1}`. There is no code path
that commits without calling it: recolour-only op lists run it too.

### C.3 Settle — find where it actually rests (budgeted, deterministic)

Runs for `move`/`duplicate`/`add`/`rotate` with `settle:true`, only when every part in the group is
upright, and only if the requested placement fails the **local test**. Tilted groups never settle.

Local test (cheap; the static parts' buckets and antistud index are built once per `apply`):
`free(pos)` = the group's samples hit no static bucket (≥ 3 hits = collision); `held(pos)` = the group
has an (s)/(x)/(c) edge to a static part, or is grounded.

Search, in this exact order:

1. Columns: stud offsets `(ox, oz)` with `max(|ox|,|oz|) ≤ 2`, sorted by `(|ox|+|oz|, |ox|, ox, oz)`
   — 25 columns, the requested one first.
2. In a column start at the requested height `y`. If not `free`: raise one plate at a time until
   `free` (≤ 36 plates). Then, while the position one plate lower is `free` and not below ground:
   go down (≤ 60 plates). If the resting position is `held`, it is a **candidate**.
3. Run the full `gate` on the candidate. Accept → done. Reject → next column.

Budget: ≤ 25 columns, ≤ 400 local tests, **≤ 3 full gates**, no wall-clock term (wall clocks break
replay). Exhausted → reject `NO_SPOT` (or the first candidate's gate code if one reached the gate).
`landed` reports the result (D.1); `settled` is true when the final placement differs from the
requested one.

### C.4 Delete and cascade

`delete` with `cascade:false`: gate as usual; `WOULD_FALL` carries `culprits` (what would fall) and
`offer: {"cascade": true}`. With `cascade:true`: also remove `loose(after) − loose(before)` (one pass
is a fixpoint: removing loose parts cannot loosen others), then gate the result (it can still be
`TIPS`). `removed` lists everything that went. Removing all parts → `EMPTY`.

---

## D. HTTP API (`bricolage/server.py`)

### D.0 Session

```python
Session.load_ldr(name, text, source=None) -> Version            # new ROOT version (parent None), no model call
Session.edit_parts(ops, dry_run=False, base=None, text=None, path="direct") -> (Version | None, Result)
```

All mutating handlers and `edit_parts` run under one `threading.Lock`. `dry_run` never commits and
never touches `_redo_stack`. A C build's `provenance` gains: `ldr` (main model text), `lib` (embedded
part library text, `""` for brickify models), `next_id`, `source`, `stability`, `edited` (bool).
`Build.id` is unchanged by a direct edit; `version` is `parent.version + 1`. After an accepted edit
`stands`/`collisions` in provenance are recomputed from the gate's numbers.

`GET /api/ldr` returns `provenance["ldr"] + "\n" + provenance["lib"]` for C builds.

Every mutation response is today's `_payload()` **plus one key, `edit`**. Rejections are HTTP 200
with `edit.accepted:false`. HTTP 400 = malformed body/op (`{"error","human"}`), 409 = `NO_MODEL` or
the head is not a C build.

### D.1 `POST /api/edit_direct`

Request:

```json
{"ops": [{"op":"move","ids":["p41"],"d":[2,0,0],"settle":true}], "dry_run": false, "base": "v3"}
```

`base` (required) = the version the client is looking at; if it is not the head → `STALE`.

Accepted response (`…` = the usual payload keys: `version name build report steps tape tree physics head`):

```json
{
  "version": "v4", "head": "v4", "...": "...",
  "edit": {
    "accepted": true, "dry_run": false, "path": "direct", "code": null,
    "human": "Moved 1 piece 2 studs right · it came to rest 1 plate lower · still stands",
    "ops": [{"op":"move","ids":["p41"],"d":[2,-1,0],"settle":false}],
    "changed": ["p41"], "added": [], "removed": [],
    "landed": [{"id":"p41","line":57,"requested":[2,0,0],"d":[2,-1,0],"settled":true,
                "origin":[70,-40,130],"matrix":[1,0,0,0,1,0,0,0,1]}],
    "candidates": [], "culprits": [], "offer": null,
    "tape": [
      {"t":1,"actor":"designer","kind":"edit.apply","text":"Moved 1 Brick 1x2 2 studs right","status":"ok","ms":0,"tokens":0},
      {"t":2,"actor":"repair","kind":"edit.settle","text":"It had nothing under it there, so it came to rest 1 plate lower","status":"ok","ms":0,"tokens":0},
      {"t":3,"actor":"inspector","kind":"edit.gate","text":"Nothing overlaps, everything is still attached, and it still stands","status":"ok","ms":41,"tokens":0},
      {"t":4,"actor":"scribe","kind":"edit.steps","text":"Manual updated: 34 steps","status":"ok","ms":0,"tokens":0}
    ]
  }
}
```

Rejected response (nothing committed; `version` is still the old head):

```json
{
  "version": "v3", "head": "v3", "...": "...",
  "edit": {
    "accepted": false, "dry_run": false, "path": "direct", "code": "WOULD_FALL",
    "human": "Removing that would leave 5 pieces with nothing holding them up (3 Slope Curved 2x1, 2 Plate 1x2). Remove those too?",
    "ops": [], "changed": [], "added": [], "removed": [], "landed": [],
    "candidates": [], "culprits": ["p88","p89","p90","p91","p92"], "offer": {"cascade": true},
    "tape": [
      {"t":1,"actor":"designer","kind":"edit.apply","text":"Tried removing 1 Brick 2x2","status":"ok","ms":0,"tokens":0},
      {"t":2,"actor":"inspector","kind":"edit.gate","text":"5 pieces would be left with nothing holding them up, so nothing was changed","status":"fail","ms":38,"tokens":0}
    ]
  }
}
```

Dry run: identical shape with `"dry_run": true`, the version never changes, and `landed` is filled
whenever a placement exists — **also on reject** — so the ghost can be drawn red where it would go.

Field rules: `landed[].d` is the total integer displacement actually applied (what the resolved op
records); `origin` (3 numbers, LDU) and `matrix` (9 numbers, row-major, as on the LDraw line) are the
part's new line values — read-only floats for the ghost, never sent back. `line` is the part's line
in the **new** text (for `dry_run` and rejects: its current line; `-1` for a part that does not exist
yet). `edit.tape` holds **only this edit's events**; `payload.tape` for a direct-edit version equals
`edit.tape`.

Success `human` = `"{what} · {settle note, if settled} · {stability}"`. `what`: "Moved 2 pieces 1 stud
left", "Turned 1 piece a quarter turn", "8 pieces recoloured Trans Dark Blue", "Removed 1 piece (and 4
it was holding up)", "Copied 3 pieces", "Added a Red Brick 2x4". `stability`: "still stands" /
"it stands now" / "still leans, as it did before".

`POST /api/undo`, `/api/redo` gain `edit` too: `{"accepted":true,"path":"nav","human":"Undid: 8 pieces
recoloured Trans Dark Blue","tape":[{"actor":"router","kind":"edit.nav","text":"Went back one
change","status":"ok",…}], …empty lists}`; nothing to undo/redo → `accepted:false`, `human:"Nothing to
undo."` / `"Nothing to redo."`. `POST /api/try_another` on a direct-edit or loaded head →
`accepted:false`, `"There's only one way to make that change. Try a different change instead."`

### D.2 `GET /api/parts`

```json
{
  "version": "v3", "count": 61, "source": "car",
  "parts": [
    {"id":"p5","line":5,"part":"3024","name":"Plate 1x1","kind":"plate","geometry":"kit",
     "colour":46,"colour_name":"Trans Yellow","trans":true,"body":"model",
     "pos":[1,1,-5],"rot":0,"upright":true,"size":[1,1,1],"origin":[30,-8,-90],
     "step":1,"where":["front","right","bottom"],"tags":["light"],"loose":false}
  ],
  "bodies":  [{"name":"model","count":61,"colours":[4,0,7,46]}],
  "colours": [{"code":4,"name":"Red","count":30,"trans":false}],
  "kit":     [{"part":"3001","name":"Brick 2x4","kind":"brick","size":[4,3,2]}],
  "palette": [{"code":4,"name":"Red","hex":"#B40000","trans":false}],
  "suggestions": ["Make the lights blue", "Make the red pieces yellow", "Remove the top piece"]
}
```

- `parts` is sorted by `line`; `parts[i].line === i`. `pos` = `[round(x/20), round(-y/8), round(z/20)]`,
  `rot` = nearest quarter turn in degrees (as `from_result` today); `origin` = the line's x y z.
- `where`: any of `top bottom left right front back`. `top`/`bottom` = the part's box reaches within
  8 LDU of the model's highest/lowest point; `left/right/front/back` = its centre lies in the outer
  third of the model's extent on that axis (`left=−X`, `front=−Z`).
- `tags` (the words people use): `light` = `trans` and footprint ≤ 2x2 studs and `kind` in
  plate/tile/round/brick/slope; `eye` = pid in `98138 6141 85861 4073` and colour in `0 15`;
  `window` = `kind=="window"` or (`trans` and not `light`); `wheel` = kind wheel or tyre.
- `kit` = the parts `add` accepts. `palette` = the model's own colours first (by count), then
  `4 14 1 2 25 15 0 71 72 70 19 27 5 33 36 46 47 34`, deduplicated; `hex`/`name`/`trans` parsed from the
  pack's `0 !COLOUR` lines (`trans` = has `ALPHA`; name with `_` → space).
- `suggestions`: ≤ 4 strings. BE builds candidates from templates — "Make the lights {c}" (if any
  `light`), "Make the {most common colour} pieces {contrasting colour}", "Make the {body} {c}" (if > 1
  body), "Remove the top piece", "Turn the {smallest body} around" — runs each through the
  **pre-parser and a dry-run gate**, and keeps the first 4 that are accepted. Cached per version. A
  chip that would be rejected is never offered.
- 409 `NO_MODEL` when there is no C build.

### D.3 `POST /api/load_ldr`

```json
{"name": "Car", "ldr": "<the whole .ldr or packed .mpd text>", "source": "car"}
```

No model call, ever. Body ≤ 4 MB. Steps:

1. `edits.flatten(text)`: main model = the text before the first `0 FILE` line if the text does not
   start with one, else the first `0 FILE` block. `0 !COLOUR` lines and everything up to the last of
   them are dropped from the main text (the viewer has its own table). Remaining `0 FILE` blocks =
   `lib`. A type-1 ref whose name (case-insensitive, `\`→`/`) matches a `lib` block ending in `.ldr`
   or `.mpd` is a **sub-model**: expand it in place (depth ≤ 8), composing matrices, colour 16
   inheriting the referencing line's colour, keeping the sub-model's `0 STEP`s, and closing it with a
   `0 STEP`. Every type-1 line in the output references a part.
2. Bodies, first rule that applies per part: a preceding `0 !BODY <name>` line; the outermost
   sub-model's file name without extension and without a leading `"<digits> - "`; else clusters =
   connected components of the (s)-edges between parts of the **same colour**, named
   `"{colour name lower-case}"` (or `"{colour} {k}"`, `k` from 1 in line order, when that colour has
   several clusters).
3. ids `p{line}`, `next_id` 0, provenance `{"backend":"brickify","ldr","lib","source","run":None,
   "round":None,"next_id":0,"edited":False,"stands","collisions","stability"}`; commit as a new root
   with op `{"kind":"load_ldr","name","source","ldr":<the request text>}`.

Response = payload + `edit`:

```json
"edit": {"accepted": true, "path": "load", "code": null,
         "human": "Car is ready to change: 61 pieces",
         "tape": [{"actor":"scribe","kind":"edit.load","text":"Read 61 pieces in 8 steps","status":"ok", "...":"..."},
                  {"actor":"inspector","kind":"edit.gate","text":"It stands. 4 pieces already overlap a little; I'll leave those alone","status":"warn","...":"..."}],
         "ops": [], "changed": [], "added": [], "removed": [], "landed": [], "candidates": [], "culprits": [], "offer": null}
```

Rejected only when the text has no type-1 lines (`EMPTY`, "There are no pieces in that file.") or is
over budget.

### D.4 Stability in the state payload (C builds)

`payload.physics` becomes real for C builds (BE adds `detail=True` to `check.stands`, returning the
centre of mass and the hull it already computes):

```json
"physics": {"stable": true, "margin": 4.27, "direction": "-z",
            "com": [4.6, 7.1], "base": [[0,0],[9,0],[9,10],[0,10]], "ground": 0,
            "backend": "brickify", "studs": 0, "broken": [], "failures": []}
```

`com` = `[x, z]` and `base` = hull vertices `[x, z]`, both in **studs** (LDU/20, 2 decimals, LDraw
model axes); `ground` = the ground plane's LDraw Y in LDU; `margin` in studs (negative = outside);
`failures` = `[{"code":"UNSTABLE","human":"it would tip over toward the front"}]` when not stable.

---

## E. Natural language — `POST /api/edit`

Request: `{"text": "make the lights blue", "selection": ["p5"], "base": "v3", "mode": "auto"}`
(`selection` optional, `mode` = `auto` | `direct` | `brief`, default `auto`). Response = payload + `edit`
(D.1 shape; `path` = `preparse` | `fast` | `brief`).

### E.1 Router (in `bricolage/nl_c.py`; the server just calls `nl_c.handle`)

```
text ─► preparse(text, table, selection)
          ├─ ops            ─► Session.edit_parts(ops, path="preparse")            (instant, offline)
          ├─ nav undo/redo  ─► Session.undo()/redo()
          ├─ needs/ambiguous─► accepted:false + candidates                          (no model call)
          └─ None ─► fast(text, table, selection)      [skipped if offline or mode="brief"]
                       ├─ route "direct"     ─► resolve targets ─► edit_parts(ops, path="fast")
                       ├─ route "unclear"    ─► accepted:false, code AMBIGUOUS/NOT_FOUND + candidates
                       ├─ route "structural" ─► brief path
                       └─ error/timeout/invalid twice ─► accepted:false, code NL_FAILED
brief path: build has provenance.run ─► existing Session.edit (pipeline.edit) + F.3 re-application
            no run (loaded model)     ─► accepted:false, code STRUCTURAL_UNAVAILABLE
mode="direct": never takes the brief path (structural -> STRUCTURAL_UNAVAILABLE copy).
```

Offline = `PROVIDER=mock` or `DEMO_SAFE=1`, or `nl_c.handle(..., ask=None)`. `ask` is an injectable
`callable(prompt:str, system:str) -> str`; the default wraps
`pipeline.claude(prompt, [], system, FAST_MODEL, timeout=20, max_tokens=1500, effort="low")`.
Budget: one call + one retry carrying the validation error; then `NL_FAILED`.

| code | human |
|---|---|
| `NEEDS_SELECTION` | "Tap the pieces you mean first, then say that again." |
| `NOT_FOUND` | "I couldn't find any {phrase} on this model. Tap the pieces you mean and try again." |
| `AMBIGUOUS` | "I found {n} things that could be "{phrase}": {names}. Tap the one you mean." |
| `NL_FAILED` | "I couldn't work that out. Tap the pieces and use the buttons, or try different words." |
| `LLM_COORDINATE` | same copy as `NL_FAILED` (tape says why) |
| `STRUCTURAL_UNAVAILABLE` | "That's a redesign, and this model was loaded from a file, so I can only change its pieces: move, turn, recolour, add or remove them." |

`candidates` = the ids to highlight: for `AMBIGUOUS` the union of the options; for `NOT_FOUND` after a
partial match (e.g. noun found, colour filter emptied it) the noun's set; else `[]`.

### E.2 Target phrases (shared by the pre-parser and by FAST-model target resolution)

`resolve(phrase, table, selection) -> ids | NEEDS_SELECTION | NOT_FOUND | AMBIGUOUS`. Lower-case, strip
punctuation. Grammar: `[the|all|all the|every|both] [POS]* [COLOUR] [NOUN] [piece|pieces|part|parts|brick|bricks|one|ones]`.

- Pronouns: `this these that those them selected "the selection"` → selection (empty → `NEEDS_SELECTION`).
  `it` → selection if non-empty, else all parts. `everything / all / the whole thing / the model` → all.
- `COLOUR`: a pack colour name or alias (`grey=gray`, `light grey`→71 then 7, `dark grey`→72 then 8,
  `clear`→47, `see-through X`/`transparent X`→`Trans X`; when a bare name matches several codes, the
  ones present in the model win). Filters by the part's current colour.
- `NOUN`, first rule with a non-empty result: (1) body name — exact, then token match on names split
  on `_`/space/`-`, singular/plural folded; (2) tag: `light(s) lamp(s) headlight(s) taillight(s)`→`light`,
  `eye(s)`→`eye`, `window(s) windscreen glass`→`window`, `wheel(s) tyre(s) tire(s)`→`wheel`;
  (3) `kind`: `brick plate tile slope round wedge hinge bar`; (4) a size + kind, `2x4`, `2 x 4 brick`,
  `1x2 plate` (dimensions in either order); (5) any token of the part's `name`; (6) an LDraw part number.
- `POS` (`top bottom front back left right upper lower rear`): with a noun, keep the parts of the noun
  set strictly beyond the set's midpoint on that axis (all of them if they tie); without a noun,
  the parts carrying that `where` word — and for `top`/`bottom` + singular, only the single extreme
  layer.
- `AMBIGUOUS`: a **singular** noun that matched > 1 body by rule 1, or > 1 part by rules 2–6 with no
  `all/every/both`. ("delete the wheel" on a car is ambiguous; "delete the wheels" is not.)

### E.3 The deterministic pre-parser (no model, works offline)

Whole-string, case-insensitive, leading "please/can you/could you" and trailing "please/./!" dropped.
`N` = digits or `one…twelve` or `a/an` (=1), `a couple`(=2); 1 ≤ N ≤ 40. `T` = a target phrase (E.2).
`C` = a colour phrase. First matching row wins, tried top to bottom:

| # | pattern | op |
|---|---|---|
| 1 | `undo` \| `go back` \| `revert( that)?` \| `undo that` | nav undo |
| 2 | `redo( that)?` | nav redo |
| 3 | `(make\|paint\|colou?r\|turn\|change) T (to \|into \|in )?C` | recolour |
| 4 | `(delete\|remove\|erase\|get rid of\|take off\|take away\|take out) T` | delete (`cascade:false`) |
| 5 | `(move\|shift\|nudge\|push\|slide) T (DIR)( by)?( N)?( UNIT)?` and `… T (N)( UNIT)? (DIR)` | move |
| 6 | `(raise\|lift) T( by)?( N)?( UNIT)?` / `(lower\|drop) T …` | move up / down |
| 7 | `(rotate\|turn\|spin) T( (around\|round\|180\|half way))?` → 2; `( (left\|anticlockwise\|counter-?clockwise))?` → 3; `( (N) (times\|quarter turns?))?`; `( (90\|270)( degrees)?)?` → 1 / 3; default 1 | rotate |
| 8 | `(duplicate\|copy\|clone) T` | duplicate |
| 9 | `add (N )?(C )?(PART)( on top( of T)?\| on T\| to T)?` | N × add (`on` = first id of T, else null; N ≤ 8) |

`DIR` = `up down left right forward(s) back(wards) forward back front`; `UNIT` = `stud(s)` (left/right/
forward/back only), `plate(s)` or `brick(s)` = 3 plates (up/down only); no unit = studs or plates by
direction; a unit that does not fit the direction → no match (falls to the FAST model). `PART` =
size + kind against `table.kit`. Recolour's trans rule (also applied to FAST-model recolours): if a
target part's current colour is `trans` and `Trans {C}` exists in the pack (`Blue`→33 Trans Dark
Blue, `Red`→36, `Yellow`→46, `Green`→34, `Orange`→57, `Clear/White`→47, `Pink`→45, `Purple`→52), that
part gets the trans code; opaque parts get the plain code. One `recolour` op per resulting code.

If a row matches but `T` resolves to `NOT_FOUND`, the pre-parser returns `None` so the FAST model
gets a try; offline that becomes `NOT_FOUND`. `NEEDS_SELECTION`/`AMBIGUOUS` are returned as is.

**"make the lights blue" on `car.mpd`** → row 3, `T = lights` → tag `light` → the six trans `3024` and
two trans `6141` → all `trans` → `[{"op":"recolour","ids":[…8 ids…],"colour":33}]` → gate → tape:
`router/edit.match` *"“lights” matched 8 see-through pieces"* · `designer/edit.apply` *"Recoloured 8
pieces Trans Dark Blue"* · `inspector/edit.gate` ok · `scribe/edit.steps`; `human`: *"8 pieces
recoloured Trans Dark Blue · still stands"*. No model call.

### E.4 The FAST model I/O

System prompt (BE writes it; it must contain these sentences): *You translate one instruction into
edit ops for a LEGO model. You never give positions, coordinates, offsets, matrices or sizes; code
computes all geometry. Choose only: an op, a target, a direction word, a whole number, a colour name,
a part number from `kit`. If the request changes the design's shape or proportions (bigger ears, a
longer tail, add a hat) answer `structural`. If you cannot tell which pieces are meant, answer
`unclear`. Reply with one JSON object and nothing else.*

User message = one JSON object. **No numbers describing position appear in it:**

```json
{"instruction": "make the lights blue",
 "selection": ["p5"],
 "bodies":  [{"name":"model","pieces":61,"colours":["Red","Black"],"where":["bottom"]}],
 "groups":  [{"g":"g0","part":"3024","name":"Plate 1x1","colour":"Trans Yellow","body":"model",
              "tags":["light"],"where":["front","bottom"],"ids":["p5","p6"],"more":0}],
 "colours": ["Red","Black","Trans Yellow","Blue","Trans Dark Blue"],
 "kit":     [{"part":"3001","name":"Brick 2x4"}]}
```

`groups` = parts grouped by `(part, colour, body, where)`, at most 150 groups (largest first; the rest
are summarised in one `{"g":"rest","pieces":n}` entry), at most 40 ids per group (`more` = how many
were left out; the model can still target the whole group by `g`).

Reply, exactly one of:

```json
{"route":"direct","say":"Making the 8 lights blue",
 "ops":[{"op":"recolour","target":{"groups":["g0","g3"]},"colour":"Blue"}]}
{"route":"structural","why":"bigger ears means reshaping the head"}
{"route":"unclear","ask":"Which ear?","candidates":{"body":"ear_left"}}
```

LLM op shapes (different from B.3 on purpose: the model has **no field that can hold a coordinate**):

```json
{"op":"recolour","target":T,"colour":"<colour name>"}
{"op":"delete","target":T,"cascade":false}
{"op":"move","target":T,"dir":"up|down|left|right|forward|back","n":2,"unit":"stud|plate|brick"}
{"op":"rotate","target":T,"quarters":1}
{"op":"duplicate","target":T}
{"op":"add","part":"3001","colour":"<colour name>","on":T_or_null,"quarters":0}
T = {"ids":[..]} | {"groups":[..]} | {"body":".."} | {"colour":".."} | {"part":".."} | {"selection":true} | {"all":true} | {"phrase":"the front lights"}
```

`{"phrase"}` is resolved by E.2. Code converts `dir/n/unit` → `d`, colour name → code (+ trans rule),
targets → `ids`, then calls `edit_parts` like any other caller.

**Validation (`nl_c.validate_reply`), strict allow-list:** the reply must parse as one JSON object;
every key must be one listed above for its op (any other key — `x y z pos position at d offset
origin matrix coords size` or anything else — refuses the whole reply); every number must be a JSON
integer within `n` 1..40, `quarters` 0..3; every string must be from its enum / the colours list / the
kit / existing ids, groups, bodies; ≤ 8 ops. A refusal is retried once with the reason appended, then
rejected with `LLM_COORDINATE` (a forbidden/unknown key or a non-integer number) or `NL_FAILED`
(anything else), and the tape records `router/edit.route` *fail*: *"The model tried to place a piece
by coordinates, which it isn't allowed to do. Nothing was changed."*

### E.5 Tape for NL edits (plain words; `edit.tape` only)

| actor | kind | when | example text |
|---|---|---|---|
| router | `edit.match` | target resolved | "“lights” matched 8 see-through pieces" / "Using the 2 pieces you selected" |
| router | `edit.route` | path chosen | "That's a quick change, no redesign needed" / "That needs a redesign, so I'm rewriting the plan (1–3 minutes)" |
| designer | `edit.apply` | per op | "Recoloured 8 pieces Trans Dark Blue" |
| repair | `edit.settle` | settled | "It had nothing under it there, so it came to rest 1 plate lower" |
| inspector | `edit.gate` | verdict | ok / `fail` with the reason in words |
| scribe | `edit.steps` | committed | "Manual updated: 8 steps" |
| repair | `edit.reapply` | F.3 | "Kept 3 of your 4 earlier changes" / warn: "Couldn't keep “moved 2 pieces on the head”: those pieces were rebuilt" |

Texts must not contain `->`, a leading `CODE:`, or a `name(arg=…)` call (tapeCopy would rewrite them).
On the brief path the existing brickify events stream into the same per-edit tape after `edit.route`.

---

## F. Persistence and replay

**F.1 The op record.** An accepted direct edit (button, drag, pre-parser or FAST model) commits:

```json
{"kind":"edit_direct_c","seed":0,"path":"preparse","text":"make the lights blue",
 "ops":[{"op":"recolour","ids":["p5","p6","p19","p20","p29","p30","p38","p39"],"colour":33}],
 "new_ids":[]}
```

`ops` are **resolved**: selectors expanded to `ids`; every settled placement baked in (`d` = the landed
`d`, `settle:false`); `add` is recorded as
`{"op":"add","part","colour","on","quarters","d":[dx,dy,dz],"settle":false}` where `d` is the landed
displacement from the nominal B.3 placement; `delete` with cascade lists every removed id and
`cascade:false`; `new_ids` = ids minted, in order. `text`/`path` are labels only.

**F.2 Replay.** `Session.replay()` handles: `load_ldr` → `fresh.load_ldr(op["name"], op["ldr"],
op["source"])`; `edit_direct_c` → `fresh.edit_parts(op["ops"], base=None)` — same `apply`, same gate,
settle off, no model, no clock. The resulting `provenance["ldr"]` must equal the original **byte for
byte**, and so must the part ids. A replayed op that the gate rejects raises (it means non-determinism).

**F.3 Direct edits across a brief-level rebuild.** When `Session.edit` takes the brief path and the
chain from the last brief-built/loaded version to the head contains `edit_direct_c` ops:

1. Rebuild from the revised brief as today → parts with fresh `p{line}` ids.
2. For each earlier direct op, in order, translate its ids by **signature** = `(pid, body, world
   origin rounded to 1 LDU, rotation rounded to 2 decimals)` as the part was in the version that op
   was applied to (colour is not part of the signature). Parts minted by earlier re-applied ops map
   through their new ids.
3. If every id of the op maps, apply it through `edits.apply` (gate on, settle off). Any id missing
   or any rejection → the op is **dropped**.
4. Tape: one `repair/edit.reapply` summary, plus one `warn` per dropped op naming it in words. The
   success `human` ends with "· kept {k} of your {n} earlier changes" when `n > 0`.
5. The committed op is `{"kind":"edit_c","text","recipe", "reapplied":[resolved ops against the new
   ids], "dropped":[{"op":{…},"human":"…"}]}`; replay = `from_recipe(recipe)` then `edit_parts` for
   each of `reapplied`. No model call.

Never silently lost: `dropped` is in the op record, on the tape, and in `edit.human`.

**F.4 `tree_ascii` labels:** `build {prompt}` · `load {name}` · `edit_c "{text}"` ·
`edit_direct_c` → `edit.human`'s first segment · `edit` (engine A) unchanged. No `KeyError` for any kind.

---

## G. Frontend (same look, inside the existing build view)

**G.0 Edit mode = the existing "Change it" panel being open.** The `Sparkles` "Change it" tile is the
Edit toggle; no new entry point, no new layout. While open: `spin = 0`, mode `display`, all steps
shown, the 3D view accepts picks, and a toolbar row appears at the top of the stage.

**G.1 Every build is really editable (the reported bug).** In `view/page.tsx`, when the panel opens
on a non-live build: fetch `build.model` as text → `loadLdr({name: build.name, ldr, source: id})` →
adopt the payload → `router.replace("/build/live/view?edit=1")`. While that runs the panel shows
`BrickLoader` with "Getting it ready to change…" and the input/chips are disabled. If the API is
unreachable or `live.source === "fixture"`: show, verbatim, *"Changing a model needs the builder
running, and I can't reach it right now."* — nothing else happens. Guard the effect with a ref
(strict mode runs it twice). `/lab` gets the same "Change it" tile, seeding from `/lab/{name}.ldr`.

**Delete:** `useFixtureTape` / `useTapePlayback` usage, `sampleRun`, `SAMPLE_CHIPS`, `LIVE_CHIPS`, and
the `events: p?.tape` line. Remove the two hooks from `AgentTape.tsx` (nothing else uses them).

**G.2 Turns.** One turn per action (typed, chip, toolbar button, drag, undo/redo):
`{text, events: payload.edit.tape, result: payload.edit.human, ok: payload.edit.accepted, offer}`.
The `AgentTape` shows **only** `edit.tape`. Accepted → the green-check result row with `edit.human`;
rejected → the existing red error paragraph with `edit.human` verbatim; `offer.cascade` → one
`BrickChip` "Remove those too" that resubmits the same op with `cascade:true`. `candidates`/`culprits`
go to the 3D view (G.4) and stay until the next action. Toolbar/drag turns use a short generated
`text` ("Move right", "Delete") so the log reads as one history. Chips = `table.suggestions`
(none while loading; never hard-coded).

**G.3 New client calls (`lib/bricolage.ts`, `lib/live.ts`).**

```ts
export interface EditOp { op: "move"|"rotate"|"recolour"|"delete"|"duplicate"|"add"; ids?: string[]; d?: [number,number,number];
  quarters?: number; colour?: number; cascade?: boolean; settle?: boolean; part?: string; on?: string|null;
  body?: string; all?: true }
export interface Landed { id: string; line: number; requested: [number,number,number]; d: [number,number,number];
  settled: boolean; origin: [number,number,number]; matrix: number[] }
export interface EditResult { accepted: boolean; dry_run?: boolean; path: "direct"|"preparse"|"fast"|"brief"|"nav"|"load";
  code: string|null; human: string; ops: EditOp[]; changed: string[]; added: string[]; removed: string[];
  landed: Landed[]; candidates: string[]; culprits: string[]; offer: {cascade?: boolean}|null; tape: TapeEvent[] }
export interface Payload { /* …existing… */ edit?: EditResult }
export interface PartRow { id: string; line: number; part: string; name: string; kind: string; geometry: string; colour: number;
  colour_name: string; trans: boolean; body: string; pos: [number,number,number]; rot: number; upright: boolean;
  size: [number,number,number]; origin: [number,number,number]; step: number; where: string[]; tags: string[]; loose: boolean }
export interface PartsTable { version: string; count: number; source: string|null; parts: PartRow[]; bodies: {name:string;count:number;colours:number[]}[];
  colours: {code:number;name:string;count:number;trans:boolean}[]; kit: {part:string;name:string;kind:string;size:[number,number,number]}[];
  palette: {code:number;name:string;hex:string;trans:boolean}[]; suggestions: string[] }

bricolage.editDirect(ops: EditOp[], opts: {dryRun?: boolean; base: string}): Promise<Payload>   // POST /edit_direct, 20 s timeout
bricolage.edit(text: string, selection: string[], base: string): Promise<Payload>              // POST /edit, DESIGN_TIMEOUT
bricolage.parts(): Promise<PartsTable>                                                          // GET /parts
bricolage.loadLdr(body: {name: string; ldr: string; source?: string}): Promise<Payload>         // POST /load_ldr
```

`live.ts`: `applyEdit(p: Payload)` adopts the payload (new `modelUrl`) **only if** `p.edit?.accepted
&& !p.edit.dry_run`, and always returns `p.edit`. `TapeStatus`/`TapeActor` unchanged. `tapeCopy.ts`:
first line of `tapeCopy()` — `if (e.kind.startsWith("edit.")) return { text: e.text };`.

**G.4 `ModelView` — exact new props** (all optional; absent = today's behaviour):

```ts
export interface EditGhost {
  /** PartNode indices whose meshes are cloned for the ghost (the grabbed/duplicated parts). */
  lines: number[];
  /** Where each clone sits, in LDraw model space (from `landed`, or the local optimistic guess). */
  placements: { line: number; origin: [number, number, number]; matrix: number[] }[];
  /** null = waiting for the dry run (neutral translucent ghost); true = green; false = red. */
  valid: boolean | null;
}
type Props = {
  // …existing…
  edit?: {
    enabled: boolean;
    selected: number[];            // lines, outlined with the existing HIGHLIGHT purple (SelectionOutline)
    candidates?: number[];         // same purple outline, pulsing (alpha 0.35..1 at 1.2 Hz)
    culprits?: number[];           // outline in the existing joint red 0xf83b3b
    ghost?: EditGhost | null;
    onPick?: (line: number | null, mods: { additive: boolean; body: boolean }) => void;  // null = empty space
    onDrag?: (phase: "start" | "move" | "end" | "cancel", d: [number, number]) => void;  // [dx, dz] whole studs, world axes
    stability?: { com: [number, number]; base: [number, number][]; ground: number; stable: boolean } | null;
  };
  /** Keep camera, turntable angle and skip the drop-in when `url` changes (an edit landed). */
  preserveView?: boolean;
};
```

Behaviour ModelView owns:

- **Pick:** pointer down→up within 6 px and 300 ms = tap → raycast visible part meshes → `onPick(line,
  {additive: shift/ctrl/meta, body: false})`. A second tap on the same part within 300 ms →
  `body: true`. Pointer held 450 ms without moving on a part → `additive: true` (phones). Tap on
  nothing → `onPick(null, …)`.
- **Drag:** pointer down on a part that is already in `selected`, then > 6 px → OrbitControls is
  disabled for that gesture and `onDrag` fires; the pointer ray is intersected with the horizontal
  plane through the grabbed point, the delta is un-rotated by the turntable angle into LDraw X/Z and
  rounded to whole studs. `move` fires only when `[dx,dz]` changes (one `play("drag")` per change —
  continuous input the user is driving, taste rule 1). Any other drag orbits as today.
- **Ghost:** clones of the `lines` meshes with the existing translucent `ghost` material tinted
  `0x2fd66f` (valid) / `0xf83b3b` (invalid) / untinted (null) — both colours already exist in this
  file. The real parts stay where they are until the server accepts. When `ghost` goes to `null`
  after a reject, the clone eases back to the real part over 180 ms, then is removed ("springs back").
- **Outline:** `SelectionOutline` is mounted whenever `mode === "steps"` **or** `edit?.enabled`; in
  edit mode `rig.selection` = meshes of `selected` (+ candidates/culprits in a second pass with their
  colour). Frameloop stays `always` in display mode, so nothing else changes.
- **Stability:** when `stability` is set and (`!stable` or a ghost is invalid with code `TIPS*`), draw
  the base polygon as a thin line loop on the ground and a small sphere at `com` (green inside, red
  outside), reusing `greenMat`/`redMat`. Coordinates: `(x*20, ground, z*20)` LDU inside the model group.

**G.5 New files and what each owns** (all under `web/src`):

| file | owns |
|---|---|
| `lib/editor.ts` | The editor store (`useSyncExternalStore`, like `live.ts`): `table`, `selection: string[]`, `candidates`, `culprits`, `ghost`, `pending`, `turns`. Actions: `pick`, `selectBody`, `clear`, `nudge(dir)`, `raise(±1)`, `rotate()`, `recolour(code)`, `duplicate()`, `remove(cascade?)`, `add(part, colour)`, `dragMove/dragEnd`, `say(text)`, `undo/redo`. id↔line mapping and the A.3 verification. Dry-run throttle: at most one in flight, latest wins, results for a stale `base` or a superseded drag are ignored. |
| `components/edit/EditPanel.tsx` | The "Change it" sidebar moved out of `view/page.tsx` unchanged in look; renders `turns`, chips from `table.suggestions`, sends `selection` with the text, shows "{n} selected" as a `BrickChip size="sm"` next to the title when `n > 0`. |
| `components/edit/EditToolbar.tsx` | The toolbar row: white `IconTile`s (size 48; 44 in portrait) in a `no-scrollbar` horizontal scroller at the top of the stage, right of the left tile column. With a selection: ◀ ▲ ▼ ▶ nudge (lucide `ArrowLeft/Up/Down/Right`), raise/lower one plate (`ChevronsUp/ChevronsDown`), rotate (`RotateCw`), colour (`Palette`), duplicate (`Copy`), delete (`Trash2`). Always: add (`Plus`). Disabled tiles at 40 % opacity while `pending`. Every tile has `data-sound="off"`. |
| `components/edit/ColourTray.tsx` | Opens under the toolbar: `table.palette` as 36 px rounded-8 squares filled with `hex` (trans ones at 60 % opacity over the blue), name as `aria-label`. |
| `components/edit/PartTray.tsx` | `table.kit` in grey inventory slots (taste rule 7: `#8b8b8b`, bevelled) with `partImageUrl(part, colour)` thumbnails, falling back to the part name. Tap = `add(part, lastColour, on = first selected or null)`. |
| `components/edit/useEditKeys.ts` | Desktop shortcuts, active only in edit mode and when no input is focused: arrows = nudge, `PageUp/PageDown` or `W/S` = raise/lower, `R` = rotate, `Delete/Backspace` = delete, `D` = duplicate, `Cmd/Ctrl+Z` = undo, `Shift+Cmd/Ctrl+Z` = redo, `Esc` = clear selection (or cancel a drag), `Cmd/Ctrl+A` = select all. |

Arrow nudges and the ◀▲▼▶ tiles are **screen-relative**: FE maps the screen direction to the world
axis (`±X`/`±Z`) most aligned with it given the camera azimuth and turntable angle, then sends an
integer world `d`. Only the server decides where it lands.

**G.6 The edit cycle.**

- Button/key: optimistic ghost at the nominal target (`valid:null`) → `editDirect(ops, {base})`
  (commit directly, no dry run) → accepted: `applyEdit`, model swaps with `preserveView`, selection
  follows by id (new parts from `added` become the selection after duplicate/add), one
  `play("connect", {volume: 0.45})`; rejected: ghost springs back, one `play("tick", {volume: 0.4})`,
  turn shows `human`, `culprits` flash red.
- Drag: each `onDrag("move")` updates the ghost locally and queues a `dry_run`; the reply places the
  ghost at `landed[].origin/matrix` and colours it. `"end"` commits the last `d` with `settle:true`
  and then behaves like a button. `"cancel"`/`Esc` drops the ghost.
- One action = one sound (taste rule 1): never the tile tap **and** the result sound.
- While `pending`, further commits are queued, max depth 1 (newest replaces).
- After every adopted version: refetch `parts()`, re-verify A.3, drop ids that no longer exist from
  the selection.
- Phone: toolbar scrolls sideways; long-press = multi-select; trays open as rows inside the stage,
  never over the docked panel (taste rule 12).

---

## H. File ownership (disjoint)

**Backend engineer**

- new: `brickify/brickify/partlib.py`, `brickify/brickify/edits.py`, `bricolage/nl_c.py`
- edit: `brickify/brickify/check.py` (`same_body` kwarg, `stands(detail=True)`, `_samples` via partlib),
  `brickify/brickify/kit.py` (only if `Geom` needs `y0/y1`), `bricolage/engine_c.py` (`physics`, `report`,
  `steps` for edited/loaded builds, `from_ldr`), `bricolage/session.py`, `bricolage/server.py` (+ its dev
  console), `bricolage/serialize.py` (drop `ldr`/`lib` from provenance), `bricolage/tests.py`
- read-only inputs: `web/public/ldraw/parts.pack.ldr`, `web/public/lab/*.ldr`, `web/public/models/*.mpd`

**Frontend engineer**

- new: `web/src/lib/editor.ts`, `web/src/components/edit/{EditPanel,EditToolbar,ColourTray,PartTray}.tsx`,
  `web/src/components/edit/useEditKeys.ts`
- edit: `web/src/lib/bricolage.ts`, `web/src/lib/live.ts`, `web/src/lib/tapeCopy.ts`, `web/src/lib/useBuild.ts`
  (only if needed), `web/src/components/three/ModelView.tsx`, `web/src/components/AgentTape.tsx`,
  `web/src/app/build/[id]/view/page.tsx`, `web/src/app/lab/page.tsx`

Nobody touches: `brickify/brickify/{assembly,pipeline,merge,layout}.py` (the brief path stays as is),
`web/public/**`, `fixtures/`, the other build screens. `docs/EDITING.md` is changed only by agreement.

FE develops against this document's JSON examples (a 30-line mock of `/parts`, `/edit_direct`,
`/load_ldr` is fine locally, never committed as a fallback: nothing fake ships).

---

## I. Test plan (`bricolage/tests.py`, all offline, no model, target < 20 s total)

Fixtures: `LAB = ../web/public/lab`; helper `_load(name)` → `Session.load_ldr(name, text)`. Pick test
parts **by computation** (e.g. "a part with no part above it", "the only supporter of another part"),
never by hard-coded id. `a-fox.ldr` is the default model.

| # | test | asserts |
|---|---|---|
| 1 | `test_c_load` | fox/cat/dog-umbrella load; `count` = number of type-1 lines; ids `p0…`; `loose == []`; 0 baseline collisions; served ldr's type-1 lines equal the source's byte for byte |
| 2 | `test_c_load_mpd` | `models/car.mpd` loads without raising: 61 parts, every part has a `PartInfo`, `geometry` ∈ kit/derived/described/fallback, none skipped; `lunar.mpd` flattens its sub-models (no `.ldr` refs left, bodies include "Vehicle") |
| 3 | `test_gate_overlap` | move a top part down 3 plates with `settle:false` → `COLLIDES`, version unchanged, ldr unchanged, `human` non-empty |
| 4 | `test_gate_floating` | move a top part up 10 plates, `settle:false` → `FLOATING` |
| 5 | `test_gate_tip` | synthetic model via `load_ldr` (one `3003` on the ground, one `3007` 2x8 centred on it): `add` a `3007` on the top part, then `move` it 3 studs along its long axis (`settle:false`, still stud-connected), and repeat stacking outward; the first op after which `stands` would flip is rejected `TIPS` with a side named in `human`, and every op before it is accepted; on `dog-holding-an-umbrella` (already unstable) an op that lowers the margin → `TIPS_WORSE`, a recolour is accepted |
| 6 | `test_move_settles` | same move as #4 with `settle:true` → accepted, `landed[0].settled`, `landed[0].d[1] < 10`, every `d` is an int, origin is on the 20/8 lattice, gate ok |
| 7 | `test_settle_budget` | a move to 60 studs away over empty space with a part that cannot rest on the ground connected → `NO_SPOT` or accepted-on-ground; in both cases ≤ 3 full gates ran (count via a hook) |
| 8 | `test_delete_cascade` | deleting a sole supporter → `WOULD_FALL`, `culprits` non-empty, `offer.cascade`; with `cascade:true` → accepted, `removed` ⊇ culprits, `loose == []` |
| 9 | `test_recolour` | only the colour token of the target lines differs; all other lines byte-identical; step count unchanged |
| 10 | `test_duplicate_add_ids` | duplicate → `n0`; add → `n1`; delete `n0`; add → `n2` (no reuse); `parts[i].line == i`; supporters precede the new lines |
| 11 | `test_rotate_snap` | rotating a 1x2 once keeps it on the stud lattice (footprint min corner ≡ before mod 20) and the gate passes or rejects — never a half-stud placement |
| 12 | `test_dry_run` | `dry_run:true` returns `landed` and leaves `head`, versions and redo stack untouched |
| 13 | `test_stale_base` | wrong `base` → `STALE`, nothing changes |
| 14 | `test_replay_direct` | load → move(settle) → recolour → duplicate → delete(cascade) → undo → redo; `replay()` ldr **byte-identical** and ids equal; a monkey-patched `pipeline.claude` that raises proves no model call |
| 15 | `test_preparse` | table-driven: "make it red", "make the orange pieces blue", "paint these green" (with/without selection → ops / `NEEDS_SELECTION`), "delete these", "remove the top piece", "move this up two", "move them left 3 studs", "raise it by one brick" (=3 plates), "rotate the tail" (unknown body → None/`NOT_FOUND` offline), "turn it around" (=2), "copy this", "add a red 2x4 on top", "undo", "make the ears bigger" → `None` |
| 16 | `test_lights_blue` | on `car.mpd`: "make the lights blue" offline → accepted, 8 parts now colour 33, `edit.tape` kinds are exactly `edit.match, edit.apply, edit.gate, edit.steps`, no build-tape text in it |
| 17 | `test_llm_reply_guard` | `validate_reply` refuses: a `"pos":[1,2,3]` key, `"d":[1,0,0]`, `"n":1.5`, `"x":20` nested in target, an unknown colour, an unknown id; accepts the three E.4 examples; with an injected `ask` returning a coordinate twice → `LLM_COORDINATE`, nothing committed |
| 18 | `test_nl_routes` | injected `ask` returning `structural` on a loaded model → `STRUCTURAL_UNAVAILABLE`; returning `unclear` → `candidates` filled; `ask=None` + unparseable text → `NL_FAILED` |
| 19 | `test_tree_and_payload` | `tree_ascii()` works with `load_ldr`/`edit_direct_c`/`edit_c` ops; `build_json` provenance has no `ldr`/`lib`; `physics.com`/`base` present |
| 20 | `test_reapply` | unit-level: given an old model, recorded direct ops and a "rebuilt" model where one target moved, `reapplied`/`dropped` split is right and the dropped one has a `human` |

The 33 existing tests must still pass. FE gates: `npm run typecheck` (only the known `layout.tsx`
error), `npm run lint`, `npm run build` clean; manual check of the reported bug: open `/build/car`,
"Change it", type "make the lights blue" → eight lights turn blue, the tape shows four edit bricks and
nothing about a rover.

---

## Contract amendments (BE, after implementing A–F and I)

Everything below was found while building it. The frontend contract (sections D, G) is unchanged
except where marked **FE**; the rest is internal to the Python side.

**1. `dog-holding-an-umbrella.ldr` has 21 baseline collision pairs, not 0** (§0.3, test 1). The "0
collisions" in §0 was measured with the old cross-body-only `check_world`; under the all-pairs rule
the gate needs (§C.2), its tilted umbrella overlaps itself in 21 places. That is exactly what
baseline-relative means, so nothing changes in behaviour — but test 1 asserts 0 baseline collisions
for `a-fox` and `cat` only, and simply records the umbrella's baseline.

**2. A recolour is never "touched" for the connectivity rule** (§C.2 step 2). The rule "a touched
part that was loose before and still is → FLOATING" is about *moving* a part, and must not apply to
one that only changed colour: `bunny.ldr` has 68 components under the strict stud rule, so
repainting a piece that was already floating was being refused. `touched` now means "a part whose
placement this op list changed" (move/rotate/duplicate/add). `changed` still reports recolours.

**3. A resolved `move` may record `d = [0,0,0]`** (§B.3 "not all 0"). A settle can land a piece
exactly where it started; the op still has to be recorded (the line is rewritten) and replayed, so
`d = [0,0,0]` is legal when `settle:false`. A *request* with `settle` on (or absent) and an all-zero
`d` is still HTTP 400.

**4. `resolve`, rule 1 — body names that are really colour names** (§E.2). `load_ldr` names its
clusters after their colour ("red", "black 3", "light grey 2"), and the token-match half of rule 1
made "lights" match the body *light grey* instead of the lamp tag. Token matching now skips
auto-generated colour-cluster names; an exact match ("light grey") still selects that body. This is
what makes "make the lights blue" on `car.mpd` reach the eight trans pieces.

**5. "the top piece" is one piece** (§E.2 POS). A singular `top`/`bottom` with no noun now resolves
to the single extreme part (first in file order among the extreme layer), not the whole layer —
"remove the top piece" was removing 18 slopes off `dog.ldr`. "the top pieces" still means the layer.

**6. `preparse` returns a `miss` instead of `None` when the verb parsed but the target didn't**
(§E.3 last paragraph). `{"kind":"miss","code":"NOT_FOUND","phrase":…,"candidates":[…]}` lets the
router try the FAST model online and say `NOT_FOUND` plainly offline, which the plain `None` could
not distinguish from "not a phrase I know". Internal to `nl_c`; **FE** never sees it.

**7. An injected `ask` always runs, even offline** (§E.1). `PROVIDER=mock` only disables the *default*
`ask`. A test double passed as `ask=` is a deliberate choice and runs, otherwise sections E.4/E.5
could not be tested offline. `ask=None` still means "no model call".

**8. NL paths batch big recolours and deletes.** "make it red" on a 1642-part model names far more
than the 256 ids an op allows, so `nl_c.chunk()` splits `recolour`/`delete` into ≤256-id ops (≤16 of
them) before calling `edit_parts`; `move`/`rotate`/`duplicate` stay whole, because they move as a
group. `POST /api/edit_direct` is unchanged: an over-budget op from the client is still HTTP 400.
An `OpError` raised on an NL path becomes a rejected `edit` (`accepted:false` + `human`), not a 400 —
the user typed words, not JSON.

**9. `validate_reply`: any unknown key refuses with `LLM_COORDINATE`** (§E.4), including a stray key
*inside* a target (`{"ids":[…],"x":20}`), which §E.4 lists as a `LLM_COORDINATE` case. Unknown enum
values, colours and ids are still `NL_FAILED`. The `human` copy is identical either way.

**10. `add` accepts every `kit.G` part that has antistuds** — i.e. everything that can rest on
something. `3938` (hinge top) and `30374` (bar 4L) are excluded, and `GET /api/parts` → `kit` lists
exactly the accepted set. **FE**: unchanged in shape, 32 rows for the lab models.

**11. `edits.table()` returns `suggestions: []`; the server fills it.** `brickify/` must not import
`bricolage/`, and the chips need the pre-parser, so `nl_c.suggest()` builds them (still proving each
one with a real dry run, §D.2) and `server._parts` adds `suggestions`, `version` and `source` to the
table. **FE**: the response shape is exactly §D.2.

**12. `check.check_world` / `check.stands` also take an optional `samples` callable**, on top of
`_samples` consulting `partlib` for pids outside `kit.G` (§B.1 last paragraph). A model loaded from
an `.mpd` carries its own embedded part library, and the callable is how `edits` hands that library
to the checker. `kit.G` is untouched; `Geom` did not need `y0`/`y1`.

**13. `edits.EPart.M` is a 4x4 numpy array, not a 16-float tuple** (§B.2). The dataclass is still
frozen (`eq=False`, since an ndarray has no useful `__eq__`); `Model` also carries a `cache` dict
holding that arrangement's collision pairs, connection graph and `stands`, which is what makes the
baseline half of every gate free. Internal; nothing crosses the API.

**14. Measured** (this machine, `PROVIDER=mock`, via the HTTP API). `cat.ldr`, 311 parts: load 57 ms,
`GET /api/parts` 215 ms (cached afterwards, 2 ms), recolour 256 pieces 52 ms, reject a move 48 ms,
move with settle 178 ms, cascade delete 92 ms, duplicate 178 ms. `car.mpd`, 61 parts: "make the
lights blue" end to end 30 ms. `bunny.ldr`, 1642 parts (5x the target size): load 226 ms, worst
direct edit 1.2 s — the settle's three full gates dominate, and that is the honest cost of checking
1642 parts three times.

## Integration fixes (after running BE and FE together)

1. **A rejected settle now says *why*, with real pieces named.** When the settle search failed,
   `edits.apply` threw away the failing verdict and kept only its `code`, then rendered the copy from
   an empty culprit list. Users saw `Moving that would leave 0 pieces with nothing holding them up ().`
   and, for `COLLIDES`/`TIPS`, the unformatted `{name}`/`{side}` placeholders. `_search` now carries
   the whole verdict out, so the sentence reads *"Moving that would leave 1 piece with nothing holding
   it up (1 Brick 1x1). Nothing was changed."* Measured on `dog.ldr`: 426 dry runs over all 142 parts
   produced 97 rejections (38 COLLIDES, 27 WOULD_FALL, 19 FLOATING, 13 NO_SPOT) and **0** with a
   broken sentence; before the fix, 4 of the first 10 rejections were broken.
2. **A.3 no longer flashes between versions.** `refreshTable()` lands before the new model finishes
   loading, so for ~100 ms the old meshes were compared against the new table and the panel showed
   *"I can't line this model up with its piece list"* on every add/delete. `lib/editor.ts` now records
   the version the attached meshes came from and only judges A.3 when the table is for that same
   version; while they differ picking pauses and the notice stays off. Measured: the notice appeared
   in 1 of 106 polls during a delete before, 0 of 106 after.
3. **The SSE stream's port follows `BRICOLAGE_URL`.** `lib/bricolage.ts` hard-coded `:8017` for
   `EventSource` (the stream bypasses the Next proxy). `next.config.ts` now parses the port out of
   `BRICOLAGE_URL` into `NEXT_PUBLIC_STREAM_PORT`; the host still comes from `window.location`, so
   phones on the LAN are unaffected. `run.sh` passes `BRICOLAGE_URL` to the build as well as to
   `npm start`, since the port is baked into the bundle.
4. **`run.sh` runs without `uv`.** Order: `PYTHON=...`, then `uv` (unchanged for anyone who has it),
   then a sibling checkout's venv / `.venv` / `python3` that can import numpy+scipy, else an honest
   error naming `PYTHON=`. `bricolage` puts `../brickify` on `sys.path` itself, so only the deps
   matter.
