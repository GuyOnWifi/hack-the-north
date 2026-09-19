# UI taste log

Rules from the product owner's audits. Anyone (human or agent) changing the UI
in `web/` follows these. Newest last; each rule says why, so edge cases can be
judged the same way.

## Sound

1. **One action, one soft sound.** A press, a step or a snap plays a single,
   quiet sound. Never stack sounds (a button click on top of a result sound),
   and never play a burst or a run for a single event.
   *Why:* stacked or rapid-fire sounds read as a glitch ("a barrage"), not as
   feedback. The first build step showed it: "Next step" played the button
   click plus one snap per new part, and it should have been one soft click.
   *How:* when an action has its own result sound, opt its control out of the
   global tap with `data-sound="off"`. Keep result sounds at roughly 0.35 to 0.6
   volume. Repeated sounds are only for continuous physical input the user is
   driving (rotating the model, scrubbing the slider), where each sound tracks
   their motion.

## Model previews and backgrounds

2. **Model previews are big, cropped and alive.** Wherever a card or hero shows
   a build, the model is large enough that the card's edge crops part of it,
   and it turns slowly on display (about 0.2 rad/s). Never a small, static
   model floating in the middle of empty space.
   *Why:* a small still render reads as a thumbnail; a cropped, turning model
   reads as the real object sitting right there ("make the vehicles much larger
   so that part of them clips off the screen, make them slowly rotate").
   When in doubt, go bigger: the first pass was already cropped and the
   feedback was still "make it even larger". Aim for the model to be roughly
   1.5 to 2 times the card's height, cropped on two or three sides.
   *How:* `ModelView` with `interactive={false}`, `spin`, and `zoom`, inside a
   wrapper that covers the whole card and overflows it, so only the card's own
   rounded edge ever crops the model (never a visible canvas edge). Keep the
   title legible with a corner scrim and a soft text shadow. Pause previews
   that are off screen (`active` from `useInView`).

3. **No plain gradient backgrounds.** A flat gradient behind content is boring;
   scatter faint "ghost" bricks over it, randomly dispersed, drifting slowly.
   *Why:* the brick silhouettes give depth and make every surface feel like it
   belongs to the same world ("a gradient background is kinda boring").
   *How:* `<GhostBricks seed={n} />` (seeded, so the layout is stable). Give
   each surface its own seed so no two look alike. Colour follows context:
   - On the page's light-blue background, the bricks are dark blue.
   - Inside a card, the bricks take the main colour of that card's model
     (Themes: Vehicles orange/yellow, Space blue, Trucks red, Surprise blue).
     Never put one colour over a background it muddies (blue over yellow
     reads as olive).
   Go large and few on tall cards: `cols={2} rows={3} scale={1.5}`.

4. **Hero objects are dark, transparent glass that warps what is behind it.**
   The hero brick is smoked glass: you see through it, and the glowing shapes
   behind it bend and ripple as it turns. It must still read against a dark
   card, which comes from bright rim highlights, not from a bright body.
   *Why:* three tries. An opaque smoked-black brick on the black card "looks
   ugly asl" (no edges, no life). A metallic-silver brick read clearly but was
   plain. The ask that landed: "dark and transparent with lots of warping glass
   effect".
   *How:* `GlassBrick` (`components/three/GlassBrick.tsx`). Three things make
   it work, and each was learned the hard way:
   - Glass can only bend what is rendered behind it in the same 3D scene, so
     the rings are a shader plane inside the canvas, not page elements.
   - Light it like a product shot: a black environment with a few thin bright
     strips (`Lightformer`). A bright room turns dark glass into grey plastic;
     big or strong strips wash the top face out white.
   - Keep `distortion` around 0.3 and `chromaticAberration` under 0.1. Higher
     values stop reading as glass and turn into rainbow noise.
   Use a real LDraw part for the shape (true studs, hollow underside).

5. **Decorative motifs go big and anchor to an edge.** Rings, glows and similar
   shapes should be larger than the card and centred on one of its edges, so
   the card shows sweeping arcs, not a small bullseye behind the object.
   *How:* for the glass hero, `rings={{ at: [1, 0], size: 2.3 }}` on
   `GlassBrick` (centre on the right edge, 2.3 card-heights across) with a low
   `ringFade` (0.09), because only the outer arcs are visible. Ghost bricks
   still go behind everything.

## Characters

6. **Put a real minifigure in the header, big, top left.** The home header is
   short (search bar plus one line of copy) with a large character
   (`/darth-vader.png`) standing in the top-left corner, overlapping the
   header's top edge and standing behind the search bar.
   *Why:* a tall header with a generic illustration (the blue booklet card)
   read as "this ugly top thing"; a recognisable minifig gives the screen
   personality immediately.
   *How:* absolutely positioned `<img>` inside the header, about 184px tall,
   with text padded to its right. Keep his feet hidden behind the search bar,
   never poking out below it.

## Page backgrounds

7. **No grey page backgrounds. Use the signature LEGO light blue (`#c9e2f6`),
   and let grey live in the items, like a Minecraft inventory.** Collections of
   pieces sit in square grey slots (`#8b8b8b`), bevelled dark top-left and light
   bottom-right, with the count bold white in the bottom-right corner.
   *Why:* an all-grey screen of grey-ish parts read as dull ("not a fan of
   grey"); blue page plus grey slots gives it structure and a game-inventory
   feel.
   The step-by-step manual follows the real instruction booklet: the stage is
   the same light blue page, and the parts list is the booklet's paler
   "callout box" (`#e4f1fc`) edged with a blue rule (`#9cc5ec`). Controls on
   blue are white tiles, never grey glass.
   *How:* `PartsScroller variant="slots"`. Give each piece a soft drop shadow
   inside its slot, or light-grey parts vanish into the grey. Dark blue ghost
   bricks go behind (rule 3).

## Shapes

8. **No pills, anywhere.** Every chip, tag, filter and label is a brick seen
   from the side: a rounded rectangle (about 8px corners) with studs sticking
   up off its top edge. Three studs by default, like the side of a 2x3 brick.
   *Why:* pills are generic app UI; the brick shape makes even the smallest
   control feel like it belongs to LEGO ("make ALL pills disappear").
   *How:* `BrickChip` from `components/ui/controls.tsx` (`size="sm"` for tiny
   labels, `studs={2}` when narrow). Status dots inside chips are small
   rounded squares, not circles. Leave a few px of top padding in chip rows so
   the studs aren't clipped by a scroll container.

## Manual and viewer

9. **The manual's parts rail is a scrolling film strip; scrolling scrubs the
   build.** One frame per step, square-ish, showing that step's pieces with
   counts. The frame in the middle of the strip is the biggest and frames shrink
   toward the edges (picker-wheel style). The middle frame IS the current step:
   scrolling forward builds the model up, scrolling back takes it apart.
   Arrows, keys and tapping a frame re-centre the strip. The tab on the rail's
   edge drag-resizes the rail; a plain tap hides or shows it.
   *Why:* the first version magnified frames under the hover pointer and was
   "super buggy"; the ask became "just make it scroll and the central one is
   biggest", then "scrolling should reverse/progress the build".
   *How:* `components/StepStrip.tsx`. Each frame is laid out once at full size
   and scaled with a CSS transform, so its border, bricks, counts and number
   always grow together as one unit (never size the pieces separately). No
   hover effects. Scroll-driven step changes must not trigger a re-centring
   scroll, or the strip fights the user's finger.

10. **The 3D show-off viewer is blue too.** Same family as the booklet page: a
    light-blue studio gradient, faint dark-blue ghost bricks, white control
    tiles, and a blue-tinted slider track. No grey studios anywhere (rule 7).

## Colour

11. **The AI is LEGO red (`#e3000b`), everywhere.** Sparkles, "Change it", the
    send buttons, "working" dots, loading spinners and the Inspector tag all
    use the `ai` colour token. Never purple.
    *Why:* purple for AI "doesn't match"; red is a core LEGO colour and sits
    with the yellow and blue.
    *Exceptions:* the purple outline on new parts in the manual comes from the
    reference and would vanish on red bricks, so it stays. Theme cards keep
    their own background colours.

## Panels

12. **Panels dock; they don't float.** Side panels (like "Change it") are
    solid, full-height sidebars attached to the screen edge (right in
    landscape, bottom in portrait), square to the edge with a blue rule, and
    the stage shrinks to make room. No rounded cards hovering over the content.
    *Why:* a rounded rectangle laid on top of the 3D view read as "imposed on
    top of the UI"; a docked sidebar feels like part of the app.
    *How:* the stage is its own absolutely positioned box whose right (or
    bottom) inset animates to the sidebar's size; the sidebar uses the booklet
    callout colours (`#e4f1fc`, `#9cc5ec`).
    Content never changes a panel's size: the width is fixed, and long
    unbroken text (agent-tape tool calls like `chassis(length=8,...)`) wraps
    with `overflow-wrap:anywhere` instead of widening the panel.

## Agent tape

13. **The agent tape is a tower of bricks, in plain words.** Each step the
    agent takes is a brick in its actor's LDraw colour (Router blue, Designer
    teal, Inspector red, Repair yellow, Scribe green), studs on top, landing
    on the tower with the newest on top and a baseplate underneath. A failed
    step sits crooked and cracked; once a later step fixes it, it greys out,
    struck through, "Fixed further up". The step being worked on is a dashed
    outline brick.
    *Why:* white rounded log cards with checkmarks and milliseconds "don't
    feel on theme"; a tower that the agent visibly builds, where a failure is a
    brick that doesn't fit until Repair swaps it, tells the story at a glance.
    *How:* `components/AgentTape.tsx`. Copy comes from `lib/tapeCopy.ts`, which
    rewrites Lane B's engineer-speak ("OUT_OF_BUDGET: Needs 6x Brick 2x4 in
    dark gray; you have 0." becomes "Not enough dark gray Brick 2x4 (need 6,
    have 0)"; a design proposal becomes "Sketched the design" plus part chips).
    Raw lines, timings and token counts only appear under "Show details".
    Add a pattern to `tapeCopy` whenever Lane B adds a new tape message.
