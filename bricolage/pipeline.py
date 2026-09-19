"""The whole Lane B pipeline: prompt + inventory -> validated build + steps +
tape. One entry point everything downstream consumes.
"""
from __future__ import annotations

import router
import sculpt as sculpt_backend
from client import LLMClient
from generators import expand, AttachError
from repair import Budget, fix
from sequence import sequence, Unbuildable
from tape import Tape
from validate import validate


def build_from_prompt(prompt, inventory, seed=0, tape=None):
    tape = tape or Tape()
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

    budget = Budget(seed=seed)
    result = fix(build, inventory, budget, tape, client)
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
            "tape": tape, "fix": result, "backend": backend}


def _describe(node, depth=0):
    args = node.get("args", {})
    kv = ", ".join(f"{k}={v}" for k, v in args.items() if k != "seed")
    s = f"{node['gen']}({kv})"
    kids = node.get("children", [])
    if kids:
        s += " + " + " + ".join(f"{c['gen']}@{c.get('attach')}" for c in kids)
    return s
