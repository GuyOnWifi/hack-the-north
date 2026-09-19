# Pre-demo checklist

Work top to bottom. **T−60** is an hour before judging; **T−10** is ten minutes before you stand
up. Nothing on this list takes longer than a minute except the first block.

A checklist item is either green or it is a sentence you say on stage. There is no third state.

---

## T−60 — the software

- [ ] **The suite passes.**
      `cd <repo> && .venv/bin/python -m pytest tests/ -q`
      Anything red here is a demo failure that has not happened yet.

- [ ] **The snapshot is fresh.** Regenerate it if `core/`, `api/` or `render/` changed today:
      `.venv/bin/python -m demo.snapshot`
      It re-runs the real pipeline over `data/real/inventory.json` and re-renders the manual.
      Exit 0 = good. Exit 2 = it built something too small to show (see *the long tail*, below).

- [ ] **Demo-safe passes, offline.**
      `scripts/demo_safe.sh --check`
      Must end in `… passed, 0 failed`. The server it starts installs `demo/netguard`, so a
      non-loopback connection **raises** — this check is proof, not optimism.

- [ ] **Now actually turn the wifi off and run it again.** The guard proves the program does not
      reach the network. Turning the wifi off proves nothing else on the laptop does either
      (an editor, a sync client, a font loader in the browser).

- [ ] **Read `demo/canned/meta.json`.** `check.warnings` is the list of things you might be asked
      about. `counts.parts` is the size of the model the judges will see.

- [ ] **The golden prompts, against the LIVE engine.** In demo-safe every prompt returns the same
      canned build, so checking them there proves nothing. Run each through the real pipeline:
      ```bash
      for p in "build me a rover" "build me a tower" "build me a little house"; do
        .venv/bin/python -m demo.snapshot --prompt "$p" --no-render \
          --out /tmp/golden --allow-degenerate | grep '^run'
      done
      ```
      Each must print `run ok`. Note the part counts — that is what a judge will see if they ask
      for one of these instead of the rover.

- [ ] **The edit and the undo.** With the server up: `make the chassis longer`, then **undo**.
      `scripts/demo_safe.sh --check` already does both, but do it in the UI you will present.

- [ ] **The fallback snapshot exists.** `demo/canned-rich/` is the same pipeline on a bin that is
      not long-tail — 23 parts, 7 steps. If the real bin builds something embarrassing:
      `scripts/demo_safe.sh demo/canned-rich`
      Say what it is if you use it: *"this is a fuller bin — the real one is the long-tail case."*

## T−60 — the room

- [ ] **Projector tested, with this laptop, at this resolution.** Mirror, do not extend — an
      extended display is how you end up presenting your notes.
- [ ] Browser zoom set so the inventory grid and the tape are readable **from the back of the
      room**. 125–150% is usually right. Check it from the back.
- [ ] Dark mode / light mode decided. The manual pages are pale blue; they wash out under a weak
      projector. Test one step page.
- [ ] Notifications off. `Do Not Disturb`, Slack quit, phone face down.
- [ ] Only the tabs you need are open, in demo order. Close everything else.

## T−60 — the table

- [ ] **The bin of real bricks**, the one in the photo. On the table, not in a bag.
- [ ] **The printed manual.** Printed on paper. `demo/canned/manual/manual.pdf`.
      *(Note: `.gitignore` excludes `*.pdf`, so on a fresh clone you must regenerate it —
      `.venv/bin/python -m demo.snapshot` — rather than expecting it in the repo.)*
- [ ] **The model you physically built from that manual.** This is the 2:40 beat and it is the
      single most persuasive object in the room.
- [ ] A phone with the photos on it, in case someone asks to see the capture.

## T−10 — the last pass

- [ ] Laptop **charged and plugged in**. Power brick in the bag, not at the hotel.
- [ ] `scripts/demo_safe.sh` running, browser pointed at it, first page loaded.
- [ ] `demo/SCRIPT.md` read once more, out loud, timing yourself. Two minutes fifty.
- [ ] You can say the **three limits** without looking: single-layer capture, ~200-part
      whitelist, no Technic.
- [ ] You know the four numbers: **0.88** recall, **0.70** colour accuracy, **49** part+colour
      combinations in the bin, **0** coordinates emitted by the LLM.
- [ ] Water. You will talk for three minutes, twelve times.

---

## The long tail, if exit code 2 happens

`demo.snapshot` exits 2 when the build it produced is under 12 parts. That is not a crash; it is
the system telling you the truth about the bin. The real bin is 49 part+colour combinations across
57 pieces — nearly everything is quantity one — and the allocator matches on part **and** colour,
so a generator asking for four 2×4s in red finds one.

Three options, in order of preference:

1. **Re-run the snapshot** if colour pooling has landed in `core/alloc.py` since you last did.
   That is the fix, and it makes this a 25-part build instead of a 3-part one.
2. **Use `demo/canned-rich/`** and say it is a fuller bin.
3. **Demo it as it is, and make the tape the story.** The degenerate run has the best tape in the
   project: the designer proposes, the inspector rejects with `EMPTY`, and rung 1 repairs it with
   no model in the loop. That is the architecture, demonstrated by a failure. Judges like that
   more than a big model built from a tidy bin.

---

## One command, from cold

```bash
cd /Users/jamesyang/Documents/GitHub/hack-the-north
.venv/bin/python -m pytest tests/ -q          # everything still works
.venv/bin/python -m demo.snapshot             # freeze a fresh run   (~4 s)
scripts/demo_safe.sh --check                  # prove it offline     (~2 s)
scripts/demo_safe.sh                          # and serve it
```
