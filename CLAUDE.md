# CLAUDE.md

Hackathon project: **Bricolage** — photo of a LEGO pile → a buildable model using only those bricks
→ a real step-by-step manual. 36 hours, 2–3 people.

**Read `CONTEXT.md` before doing anything non-trivial.** It has the glossary, the invariants and the
type contracts. `STATUS.md` has what actually works right now.

## Invariants — these are bugs if violated, not tradeoffs

1. **No floats in the build model.** `pos` is integer `[x,y,z]` (X/Z in studs, Y in plates);
   `rot ∈ {0,90,180,270}`. Floats appear only in `core/ldraw/write.py`.
2. **Every mutation goes through `validate()`.** No exceptions, no "this path is safe".
3. **Builds are immutable.** Every op is `Build -> Build`, producing a new version.
4. **The LLM never emits a coordinate.** It picks generators, arguments, rule ids, shapes. If a
   prompt asks for x/y/z, it's wrong.
5. **`part` is always an LDraw part number** — not Rebrickable, not BrickLink.
6. **Colour is computed** (median LAB → nearest common colour), never learned, never LLM-guessed.
7. **Never delete the classical CV path.** Trained model is an alternative behind the same interface.
8. **Every loop has a budget and a degradation path.** Nothing spins forever.
9. **Generators and tilers take an explicit `seed`.** Determinism is what makes undo and replay work.

## Domain constants you'll need constantly

```
1 stud = 20 LDU = 8mm (X/Z)    1 plate = 8 LDU (Y)    1 brick = 3 plates = 24 LDU
−Y IS UP: stacking means y_ldu -= 24
A brick's LDraw origin is the centre of its TOP face; body spans y ∈ [0, +24] downward
  (verified against 3001.dat; bricknet puts studs at y=0 and anti-studs at y=24)
`0 STEP` ends a build step; LDrawLoader reads it natively
```

## Conventions

- `core/` is pure: no network, no DB, no framework imports. That's what makes it testable in 36h.
- Frozen dataclasses for all model types. No mutation, no setters.
- Validator errors carry a `human` string — it's rendered in the UI **and** fed to the repair prompt.
  Write it as user-facing copy.
- Lanes develop against `fixtures/`, never against each other. Change a contract → update its
  fixture in the same commit.
- Env-var switches for anything with two implementations: `VISION_SEG`, `VISION_CLS`, `PROVIDER`,
  `DEMO_SAFE`.

## LLM calls

```python
client.messages.create(
    model="claude-opus-5",
    max_tokens=16000,
    system=SYSTEM,                   # catalog + generators + rules; cache_control ephemeral
    thinking={"type": "adaptive"},   # budget_tokens returns 400 on Opus 5 — never use it
    output_config={"effort": "high"},
    tools=TOOLS, messages=msgs,
)
```
Structured output is `output_config={"format": ...}` (`output_format` is deprecated). Stream for
long outputs. Provider switching lives **only** in `api/llm/client.py`.

## Tests that matter (there are only four)

1. `test_validator_catches` — three bad builds (overlap/floating/disconnected), one good.
2. `test_ldraw_roundtrip` — parse → write → compare part refs.
3. `test_substitution_geometry` — children's cells exactly tile the parent's.
4. `test_replay` — replaying a build's op list from v0 reproduces it byte-for-byte.

## When working here

- This is a hackathon. Working and ugly beats elegant and unfinished — **except in `core/`**, which
  everything depends on and which gets tests.
- Don't add dependencies without saying so; conference wifi makes installs expensive.
- Don't refactor across lanes without asking the owner. Lane owners are in `docs/lanes/`.
- If you're about to write coordinates into a prompt, re-read invariant 4.
