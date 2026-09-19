# Lane contracts — freeze these at T+1, then never block on each other

Three people working in parallel only works if the seams between them are agreed **before** anyone
writes code. This file is that agreement. It is the only file all three lanes edit together, and
after T+1 it changes only by all three agreeing out loud.

## The unblocking mechanism: fixtures

At **T+1**, commit real, hand-written example files:

```
fixtures/
├── inventory.json     # what CV produces   → LLM + FRONTEND consume
├── build.json         # what LLM produces  → FRONTEND consumes
├── report.json        # validator output   → FRONTEND consumes
├── steps.json         # sequencer output   → FRONTEND consumes
├── tape.jsonl         # SSE agent-tape events, one JSON per line
└── model.ldr          # a hand-written 40-piece build that renders
```

**Every lane develops against fixtures, not against the other lanes.** Frontend builds the entire
manual UI before any LLM call exists. LLM builds the loop before any photo works. CV builds the
model before the API exists. Nobody says "I'm blocked on you" for the first 20 hours.

Rule: if you change a contract, you update the fixture in the same commit and say so in the group
chat. A fixture that disagrees with the code is worse than no fixture.

---

## Contract 1 — `Inventory` (CV → everyone)

```jsonc
{
  "session_id": "ses_...",
  "items": [
    { "id": "inv_001",
      "part": "3001",              // LDraw part number — the universal key in this project
      "color": 4,                  // LDraw colour code
      "qty": 6,
      "source": "photo",           // photo | typed | set_import
      "confidence": { "part": 0.93, "color": 0.81 },
      "status": "confirmed",       // confirmed | needs_review | unknown
      "evidence": {                // present only when source == "photo"
        "crop_url": "https://.../crop_017.png",
        "alternatives": [ { "part": "3003", "name": "Brick 2 x 2", "score": 0.41 } ]
      } }
  ],
  "totals": { "pieces": 412, "distinct": 63, "unknown": 11 }
}
```

- `part` is **always** an LDraw part number. Not Rebrickable, not BrickLink. One key, everywhere.
- Items with `status: "unknown"` count in `totals.pieces` but are **excluded from the solver**.
- **`color_mode`** — colour is our weakest stage (0.70 accuracy on high-confidence rows), so it is
  a *hint*, not a constraint. `"exact"` means trust it; `"similar"` means the solver may substitute
  another colour freely. The comparable product ignores colour entirely; Rebrickable exposes
  Exact/Similar/Ignore as a user toggle. Lane C should surface it as one.
- **`evidence.bboxes`** — one entry per detected instance, so the UI can answer "where are my six
  red 2×4s in the photo". `evidence.bbox` stays as the first one for convenience.
- **`sufficient` / `guidance`** — below ~40 detected pieces, generation produces something
  embarrassing. Refusing with an actionable sentence is deliberate product behaviour, not an error
  state. Lane C renders `guidance` verbatim.
- CV owns producing this. LLM only ever sees an aggregated *summary* of it (never the evidence).

## Contract 2 — `Build` (LLM → frontend)

Defined in `../01-architecture.md` §1.2. The parts of it the other lanes depend on:

```jsonc
{ "id": "bld_...", "version": 7, "name": "Desk Rover",
  "parts": [ { "id": "p12", "part": "3001", "color": 4,
               "pos": [2, 3, 0], "rot": 90, "sub": "chassis" } ],
  "subassemblies": { "chassis": { "parent": null, "attach": [...] } } }
```

**`pos` is `[x, y, z]` in integer grid units: X/Z in studs, Y in plate heights. `rot ∈ {0,90,180,270}`.**
No floats. Ever. The conversion to LDraw units happens in exactly one function, `ldraw/write.py`.

## Contract 3 — `Report` (validator → frontend)

```jsonc
{ "ok": false,
  "errors":   [ { "code": "OUT_OF_BUDGET", "parts": ["p12"],
                  "human": "Needs 4× Brick 2x4 in red; you have 1" } ],
  "warnings": [ { "code": "WEAK_BOND", "sub": "wing", "human": "..." } ],
  "stats": { "parts": 147, "studs_used": 312, "inventory_remaining": 265 } }
```

Frontend renders `human` verbatim. LLM's repair prompt feeds on `human` verbatim. So whoever writes
these strings is writing user-facing copy *and* prompt text at the same time — write them well once.

## Contract 4 — SSE agent tape (LLM → frontend)

`GET /builds/{id}/events` → `text/event-stream`, one JSON object per event:

```jsonc
{ "t": 1739, "actor": "designer", "kind": "propose",
  "text": "chassis(10,4) + axle_pair + cabin(open)",
  "status": "ok", "ms": 1900, "tokens": 2400 }
```

`actor ∈ {designer, inspector, repair, scribe, cataloguer}` · `status ∈ {ok, fail, warn, running}`.
Frontend renders this as the tape panel and needs nothing else to do so — it can build the whole
panel from `fixtures/tape.jsonl` on a timer, before the backend exists.

## Contract 5 — REST

Frozen at T+1, from `../01-architecture.md` §9. Frontend mocks it with MSW or a static JSON server
until it's real. Any new endpoint gets a fixture in the same commit.

---

## Sync points (the only mandatory meetings)

| T+ | 10 minutes, standing up | Decide |
|---|---|---|
| 1 | contracts + fixtures committed | anything ambiguous, now |
| 8 | integration #1: frontend renders a real `build.json` from the backend | is anything drifting |
| 14 | integration #2: real inventory flows into a real build | what gets cut |
| 20 | **go/no-go on stretch items** | `sculpt`, photo path, PDF, camera scoring |
| 26 | freeze approaching; demo script read aloud | who says what |
| 28 | **feature freeze** | nothing else ships |

Outside these, don't interrupt each other. A lane owner who gets pulled into someone else's bug
loses an hour of their own critical path.
