# LANE C — Frontend, 3D & the manual

**You own:** everything a judge looks at. Four screens, two render styles, the step viewer, the PDF,
and the agent tape. You are also, in practice, the owner of whether this project wins anything —
the other two lanes produce correctness, you produce the thing people react to.

**You do not own:** the build model, the validator, the CV pipeline.

**Your contracts:** consume Contracts 1–4 in `00-contracts.md`. **From fixtures, from hour 1.**
You should not be blocked by another lane at any point in the 36 hours. If you are, you've started
consuming a real endpoint too early — go back to the fixture.

> Detail: [`../05-manual-and-render.md`](../05-manual-and-render.md) — read it before writing any
> three.js.

---

## The one thing that matters most

**Black LDraw edge lines.** `LDrawLoader` gives you them free, including conditional lines (the
outlines that only appear on silhouettes). They are most of what makes a render read as "official
LEGO manual" rather than "someone's WebGL demo". Get them working in hour 1 and everything after is
downhill.

## Two render setups, kept separate

| | Manual look | Display look |
|---|---|---|
| Camera | orthographic / FOV ≈ 20°, isometric | slight perspective, slow orbit 0.15 rad/s, pauses on drag |
| Material | flat, **black edge lines** | studio env map, roughness ≈ 0.25, light clearcoat |
| Ground | flat pale blue `#CFE3F4` | `<ContactShadows>` |
| Motion | pieces drop in once, then **stop** — it should look printed | continuous slow rotation |

Do not try to make one renderer do both. Two configs, one scene graph.

---

## Hour by hour

### T+0 → T+4 · deploy first
- [ ] Next.js + Tailwind up and **deployed to Vercel in the first hour.** Deploy early, deploy often;
      a URL that exists at hour 1 is a URL that works at hour 35.
- [ ] `LDrawLoader` rendering `fixtures/model.ldr` with edge lines.
- [ ] Crib from the official three.js example `webgl_loader_ldraw.html` — it already has the
      building-step GUI and the visibility traversal. **Do not invent this.**

### T+4 → T+8 · the step viewer
- [ ] Step slider off `group.userData.numBuildingSteps` / `child.userData.buildingStep`.
- [ ] Split the two render setups.
- [ ] Highlight the current step's new pieces; desaturate the placed ones.

### T+8 → T+14 · the manual page
- [ ] Big step number, parts panel with `2×` counts, page nav.
- [ ] Drop-in animation: new pieces ease down from +40 LDU over 250ms, then settle.
- [ ] Camera auto-frames the current step's new pieces, lerped — never cut.
- [ ] Keyboard `←/→`.

**GATE (T+14): a 40-piece fixture build browses as a correct, good-looking manual.
This is the demo floor — from here the project always has something to show.**

### T+14 → T+20 · the inventory UI
- [ ] Grid with confidence chips: green / amber "needs review" / grey unknown.
- [ ] **The evidence panel** — click a row, see the crop it came from and the top-3 alternatives as
      one-tap buttons. **20 minutes of work, and the most convincing thing in the demo.** It is the
      difference between "an AI guessed" and "a system that quantifies its own uncertainty".
- [ ] Typed add with typeahead; set-number import.
- [ ] Capture screen with the guided overlay: plain background · spread them out · scale card.

### T+20 → T+26 · the closers
- [ ] **The agent tape panel** — render `fixtures/tape.jsonl` on a timer first, swap to real SSE
      later. Worth more at the judging table than any amount of polish elsewhere.
- [ ] **PDF export** — fixed isometric camera per step, `toDataURL`, lay out with jsPDF, cover page
      + parts list. ~45 min for a disproportionate payoff: a PDF is a thing a judge can hold.
- [ ] Ghost-out / drop-in animation for edits, with a live "bricks remaining" counter.
- [ ] Per-step camera scoring via the ID buffer (`../05-manual-and-render.md` §2) — **cut this first
      if you're behind.** Fixed isometric is fine.

### T+26 → T+28 · freeze
- [ ] Empty states, error states, loading states. **Every spinner needs an exit.**
- [ ] Mobile: the capture screen must work on a phone, in portrait, one-handed.
- [ ] **Test on the projector.** External displays halve your framerate, always at the worst moment.
- [ ] Demo-safe mode: cached renders, canned session, wifi off.

---

## Performance — where 3D hackathon projects die

- **Pre-bake parts to GLB** with `packLDrawModel`. Runtime `.dat` parsing is fine for 12 parts in
  dev and not fine for 300 on stage.
- **Instance the studs.** They're the majority of your triangle count. One `InstancedMesh` for stud
  geometry across the scene is the biggest single win available.
- Cache geometry per part, material per colour.
- Target 60fps at 300 pieces **with the projector plugged in**.
- Service-worker the GLB pack so the second load — and a wifi outage — is instant.

---

## Prize hooks

| Prize | What you specifically do |
|---|---|
| **Finalist** ← the one that matters | This lane *is* the finalist submission. Creative, tactile, surprising. The bin of real bricks, the printed manual, the step scrub, the edit animation |
| **Sentry** | **Session Replay** on the capture flow — watching a real person fail to photograph bricks is the best UX feedback you'll get all weekend — plus **Tracing** on the frontend. ~1.5h, and it produces a real finding you can quote |
| **Warp** (if you want a stretch) | Only if the agent tape becomes a genuinely useful debugging tool. Don't force it |

## Definition of done

1. A stranger can use it on their own phone without being told anything.
2. Every screen has an empty state, an error state and a loading state.
3. It renders at 60fps on the projector.
4. `DEMO_SAFE=1` works with wifi off.
5. The PDF prints and looks like a manual.
