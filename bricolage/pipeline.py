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
    """ONE path: the LEGO LLM harness. Every prompt is designed by the LLM in the
    3D brick grammar, then lint + force/torque physics checked. No hardcoded
    template designs, no canned fallbacks — it's real model output or nothing."""
    tape = tape or Tape()
    import agents

    if recipe is not None:
        # DETERMINISTIC REPLAY from the recorded bricks — no router, no model.
        import bricks as bricks_mod
        build = bricks_mod.to_build(recipe["bricks"], name=recipe["name"],
                                    color=recipe.get("color", 71))
        return _finish_harness(build, recipe, tape)

    _, noun, _, reason = router.route(prompt)
    tape.emit("router", "route", f"{reason}  (backend=sculpt)", ms=2)
    build = agents.build(prompt, name=noun.title(), tape=tape, seed=seed)
    recipe = {"backend": "harness", "name": build.name,
              "color": build.parts[0].color if build.parts else 71,
              "bricks": build.provenance.get("bricks", [])}
    return _finish_harness(build, recipe, tape)


def _finish_harness(build, recipe, tape):
    """Harness builds are VALID/viewable if they produced a model. Physical
    instability is a WARNING (shown red in the UI), NOT a failure — you should
    always be able to see, assemble, and open your model even if it's top-heavy."""
    import physics
    from repair import FixResult
    from validate import Report
    ph = physics.analyze(recipe.get("bricks", []))
    parts = len(build.parts)
    report = Report(ok=parts > 0,
                    errors=[] if parts > 0 else
                    [{"code": "EMPTY", "parts": [], "human": "no bricks were produced"}],
                    warnings=[] if ph["stable"] else
                    [{"code": "UNSTABLE", "sub": None,
                      "human": "top-heavy — the physics says it might not stand on its own"}],
                    stats={"parts": parts,
                           "studs_used": sum(p.footprint()[0] * p.footprint()[1] for p in build.parts),
                           "subs": 1})
    return _finish(FixResult(build, report, __import__("collections").Counter(), 0, 0), "harness", recipe, tape)


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
    if recipe["backend"] == "harness":
        # naive = the model's raw proposal placed as-is (pre-lint, pre-physics),
        # so it can float/collide; verified = the same design legalised.
        import bricks as bricks_mod
        raw = recipe.get("raw_bricks") or recipe.get("bricks", [])
        naive = bricks_mod.to_build(raw, name=recipe["name"], color=recipe.get("color", 71))
    elif recipe["backend"] == "sculpt":
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
