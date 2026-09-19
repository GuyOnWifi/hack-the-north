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
