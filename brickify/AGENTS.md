# brickify: rules for agents working here

Read `README.md` first for what the pipeline does and how to run it.

## The one principle

**Models decide what to build; code places every brick.** No model ever emits
3D coordinates or picks individual bricks. Models write *briefs* (small
per-layer character grids, palette keys, connectors); `assembly.py` turns them
into real parts. Every earlier attempt that let a model place bricks produced
blobs and overlapping pieces. Don't reintroduce that.

## Rules

1. **Geometry comes from the LDraw library, never guesses.** Before adding a
   part to `kit.py`, measure it from the part file (bounding box, origin,
   stud and connector positions, which end of a slope is high). The probes used
   so far are in the git history of `kit.py`; every value there was measured.
2. **Legality is enforced by construction, then checked.** Inside a body the
   merge layout guarantees no overlaps and full connectivity. Across bodies,
   `check.py` rejects collisions. Only cosmetic parts (surfacing slopes) may be
   dropped to resolve a collision; structure always wins.
3. **New techniques are connectors or detail kinds, not free placement.** To
   let briefs express something new (swivels, clips, angled bars, wedge
   plates), add a connector kind in `assembly.py` with real part geometry, then
   document it in `BRIEF.md` with a JSON example. The brief format is the
   models' whole vocabulary: if it isn't in `BRIEF.md`, they can't use it.
4. **Keep ideas buildable before drawing them.** `DISTILL.md` decides what the
   kit can plausibly build. When the kit gains a capability, update the "can
   build" list there; when the critic keeps asking for something the kit can't
   do, add it to "cannot build" with a simplification, or build the capability.
5. **After adding parts, rebuild the web pack**:
   `cd web && LDRAW_DIR=~/ldraw node scripts/build-ldraw-pack.mjs` (needs the
   LDraw library). Otherwise the renderer 404s on the new parts.
6. **Measure, don't eyeball.** Judge changes by running the pipeline on the
   same ideas and comparing `runs/<name>/result.json` scores, and by looking at
   the renders in `runs/<name>/views-rN/`.

## Known gaps (the critic keeps asking for these)

- Second rotation axis (swivel) for swept-back wings and turned heads.
- Clip-and-bar at arbitrary angles (angled beaks, shafts, handles).
- Wedge plates in the brief vocabulary (feathers, tapered tails): geometry for
  43722/43723/41769/41770 is already in `kit.py`, but they aren't exposed yet.
- The kernel should reject weak joints (a child body not covering its
  connector's studs) instead of relying on the critic to notice.
- Hinge bricks should default to the colour of the body they sit in.
- Straight roof slopes (3039/3040 family) as a surfacing mode. Today a pitched
  roof is stepped plates with curved slopes on every step, so it reads curled
  (house scored 5/10 on exactly this). Base plates also get their edges
  rounded; flat bases should skip surfacing.
- Round bricks/cones for bushes, trees and paws.
