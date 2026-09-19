"""The whole Lane B pipeline: prompt + inventory -> validated build + steps +
tape. One entry point everything downstream consumes.
"""
from __future__ import annotations

import os
import router
import sculpt as sculpt_backend
from client import LLMClient
from generators import expand, AttachError
from repair import Budget, fix
from sequence import sequence, Unbuildable
from tape import Tape
from validate import validate


def build_from_prompt(prompt, inventory, seed=0, tape=None, recipe=None):
    tape = tape or Tape()

    if recipe is not None:
        # DETERMINISTIC REPLAY: rebuild from the recorded LLM proposal — no
        # router, no model, no vision. expand/fix are deterministic, so same
        # recipe + seed + inventory => byte-identical build.
        backend = recipe["backend"]
        if backend == "sculpt":
            build = sculpt_backend.build_voxels(recipe["voxels"], name=recipe["name"],
                                                tape=tape, seed=seed)
        else:
            build = expand(recipe["composition"], name=recipe["name"],
                           seed=seed, lenient=True)
        result = fix(build, inventory, Budget(seed=seed), tape)
        return _finish(result, backend, recipe, tape)

    backend, noun, size, reason = router.route(prompt)
    tape.emit("router", "route", f"{reason}  (backend={backend})", ms=2)
    client = LLMClient(tape)

    if backend == "sculpt":
        tape.emit("designer", "imagine",
                  f"sketching '{prompt}' as a voxel shape…", ms=1400, tokens=1800)
        voxels, model_name = client.propose_shape(prompt, noun, size, seed)
        tape.emit("designer", "propose",
                  f"proposed a {len(voxels)}-cell shape across "
                  f"{len({y for _, y, _ in voxels})} layers", ms=200)
        build = sculpt_backend.build_voxels(voxels, name=model_name, tape=tape, seed=seed)
        # vision-in-the-loop: render it, look at it, correct it (real LLM only)
        import vision
        if vision.available():
            import tempfile
            rd = os.path.join(tempfile.gettempdir(), "bricolage_renders")
            os.makedirs(rd, exist_ok=True)
            build = vision.refine(build, voxels, prompt, tape, rd, rounds=2, seed=seed)
        # record the FINAL mosaic (post-vision) so replay skips the model
        recipe = {"backend": "sculpt", "name": model_name,
                  "voxels": dict(build.provenance.get("voxels", voxels))}
    else:
        comp = client.propose_compose(prompt, inventory.summarize(), noun, size, seed)
        tape.emit("designer", "propose", _describe(comp["root"]), ms=1900, tokens=2400)
        try:
            # lenient: keep the model's valid children, drop only the impossible
            build = expand(comp, name=comp.get("name", noun), seed=seed, lenient=True)
            for d in build.provenance.get("dropped", []):
                tape.emit("inspector", "reject",
                          f"dropped {d['gen']}@{d['attach']}: {d['why']}",
                          status="warn", ms=4)
        except AttachError as e:
            # even the root won't attach — degrade to a known-good template
            tape.emit("inspector", "reject",
                      f"composition invalid ({e}); falling back to a known-good "
                      f"template", status="warn", ms=5)
            from proposer import synthesize
            comp = synthesize(noun, size, seed)
            tape.emit("designer", "propose", _describe(comp["root"]), ms=200, tokens=0)
            build = expand(comp, name=comp.get("name", noun), seed=seed)
        recipe = {"backend": "compose", "name": comp.get("name", noun),
                  "composition": comp}

    result = fix(build, inventory, Budget(seed=seed), tape, client)
    return _finish(result, backend, recipe, tape)


def _finish(result, backend, recipe, tape):
    build, report = result.build, result.report

    steps = None
    if report.ok:
        try:
            steps = sequence(build)
            tape.emit("scribe", "sequence",
                      f"ordered {steps['n_steps']} build steps "
                      f"(insertion sweep passed)", status="ok", ms=30)
        except Unbuildable as e:
            tape.emit("scribe", "sequence", f"UNBUILDABLE: {e}",
                      status="fail", ms=30)

    return {"build": build, "report": report, "steps": steps,
            "tape": tape, "fix": result, "backend": backend, "recipe": recipe}


def compare(prompt, inventory, seed=0):
    """Run the SAME request two ways for the split-screen demo:
      naive    — the model's imagined shape placed as-is (LLM places bricks)
      verified — our solver legalises + verifies it
    Returns both builds with their reports + physics, so the UI can show the
    floating/toppling mess next to the buildable one. This is the thesis."""
    import stability
    from serialize import build_json, report_json
    import sculpt as sculpt_backend

    # build once, then derive the naive baseline from the SAME recorded proposal
    # so the split-screen compares two renderings of one design, not two samples.
    verified = build_from_prompt(prompt, inventory, seed)
    recipe = verified["recipe"]
    if recipe["backend"] == "sculpt":
        naive = sculpt_backend.build_voxels_naive(recipe["voxels"], name=recipe["name"], seed=seed)
    else:
        from generators import expand
        naive = expand(recipe["composition"], name=recipe["name"], seed=seed, lenient=True)

    def pack(b):
        return {"build": build_json(b), "report": report_json(validate(b, inventory)),
                "physics": stability.report(b.parts)}
    return {"prompt": prompt, "naive": pack(naive),
            "verified": {"build": build_json(verified["build"]),
                         "report": report_json(verified["report"]),
                         "physics": stability.report(verified["build"].parts)}}


def _describe(node, depth=0):
    args = node.get("args", {})
    kv = ", ".join(f"{k}={v}" for k, v in args.items() if k != "seed")
    s = f"{node['gen']}({kv})"
    kids = node.get("children", [])
    if kids:
        s += " + " + " + ".join(f"{c['gen']}@{c.get('attach')}" for c in kids)
    return s
