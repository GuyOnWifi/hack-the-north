"""The FIX loop (L1) and the escalation ladder. Deterministic rungs run BEFORE
the LLM ever sees a failure; we log which rung closed each error, so
"most repairs never reach the model" is a number we get for free.

  rung 0  local deterministic   drop orphan / floating decorative parts
  rung 1  re-generate           shrink the composition to fit, new seed
  rung 2  substitution search   swap parts for smaller ones the bin has
  rung 3  LLM re-propose subtree (mock)
  rung 4  LLM re-propose whole   (mock)

Every loop has a budget and a degradation path (invariant #8): past budget we
return the best-so-far build with an honest Report, never a spinner.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from collections import Counter

import substitute
from generators import expand
from validate import validate


@dataclass
class Budget:
    max_attempts: int = 6
    max_llm_calls: int = 3
    max_wall_ms: int = 25_000
    seed: int = 0


@dataclass
class FixResult:
    build: object
    report: object
    rung_hits: Counter = field(default_factory=Counter)
    errors_closed: int = 0
    attempts: int = 0
    degraded: bool = False


SIZE_ARGS = ("length", "width", "depth", "height", "span", "footprint")


def _shrink_composition(comp):
    """rung 1: reduce numeric size args by one step (min 2). Socket NAMES are
    unchanged, so children stay attached — same mechanism as the edit loop."""
    import copy
    comp = copy.deepcopy(comp)

    def walk(node):
        args = node.setdefault("args", {})
        for k in SIZE_ARGS:
            if k in args and isinstance(args[k], int) and args[k] > 2:
                args[k] -= 1
        for c in node.get("children", []):
            walk(c)
    walk(comp["root"])
    return comp


def fix(build, inventory, budget, tape, client=None):
    hits = Counter()
    closed = 0
    attempts = 0
    report = validate(build, inventory)
    if report.ok:
        tape.emit("inspector", "verify", "build is valid on first try",
                  status="ok", ms=40)
        return FixResult(build, report, hits, 0, 0)

    while attempts < budget.max_attempts and not report.ok:
        attempts += 1
        err = report.errors[0]
        code = err["code"]
        before = len(report.errors)
        tape.emit("inspector", "reject",
                  f"{code}: {err['human']}", status="fail", ms=35)

        applied_rung = None

        if code == "OUT_OF_BUDGET":
            # rung 2 first — deterministic, cheap, no model
            new_parts, swaps, resolved = substitute.apply(build.parts, inventory)
            if swaps:
                build = build.with_parts(new_parts)
                applied_rung = 2
                tape.emit("repair", "substitute",
                          f"rung 2: swapped {len(swaps)} part(s) for smaller "
                          f"pieces the bin has ({swaps[0]['from']} -> "
                          f"{'+'.join(swaps[0]['to'])})", status="ok", ms=8)
            if not resolved or not swaps:
                # rung 1 — shrink to fit
                comp = build.provenance.get("composition")
                if comp:
                    build = expand(_shrink_composition(comp),
                                   build_id=build.id, name=build.name,
                                   seed=budget.seed)
                    applied_rung = applied_rung or 1
                    tape.emit("repair", "regenerate",
                              "rung 1: re-ran generators one size smaller to fit "
                              "the bin (sockets unchanged, children stay attached)",
                              status="ok", ms=12)

        elif code in ("FLOATING", "DISCONNECTED"):
            # drop ALL currently-unsupported/orphan parts at once (no whack-a-mole)
            drop = {pid for e in report.errors
                    if e["code"] in ("FLOATING", "DISCONNECTED")
                    for pid in e.get("parts", [])}
            kept = [p for p in build.parts if p.id not in drop]
            if kept and len(kept) < len(build.parts):
                build = build.with_parts(kept)
                applied_rung = 0
                tape.emit("repair", "prune",
                          f"rung 0: dropped {len(drop)} unsupported part(s)",
                          status="ok", ms=5)

        elif code == "OVERLAP":
            comp = build.provenance.get("composition")
            if comp:
                budget.seed += 1
                build = expand(comp, build_id=build.id, name=build.name,
                               seed=budget.seed)
                applied_rung = 1
                tape.emit("repair", "reseed",
                          "rung 1: regenerated with a new seam offset", ms=10)

        if applied_rung is None:
            # rung 3/4 — escalate to the model (mock). Only reached when the
            # deterministic rungs cannot help.
            comp = build.provenance.get("composition")
            if comp and client and client.calls < budget.max_llm_calls:
                shrunk = _shrink_composition(_shrink_composition(comp))
                build = expand(shrunk, build_id=build.id, name=build.name,
                               seed=budget.seed)
                applied_rung = 4
                tape.emit("designer", "re-propose",
                          "rung 4: model re-proposed a smaller build",
                          status="warn", ms=1900, tokens=2200)
            else:
                break  # nothing more to try -> degrade

        report = validate(build, inventory)
        after = len(report.errors)
        if after < before:
            hits[applied_rung] += (before - after)
            closed += (before - after)

    degraded = not report.ok
    if degraded:
        tape.emit("inspector", "degrade",
                  f"budget spent; returning best build with {len(report.errors)} "
                  f"honest issue(s) rather than spinning", status="warn", ms=20)
    else:
        tape.emit("inspector", "verify", "all issues resolved — build stands up",
                  status="ok", ms=40)
    return FixResult(build, report, hits, closed, attempts, degraded)
