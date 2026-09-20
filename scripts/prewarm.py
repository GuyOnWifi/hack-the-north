#!/usr/bin/env python
"""Ask the designer every demo prompt once, backstage, so the stage is warm.

WHY THIS IS THE HIGHEST-LEVERAGE THING IN THE BUILD PATH
--------------------------------------------------------
propose_compose() memoises on disk. A warm prompt costs 0.00 s; a cold one costs
a full model call. So the difference between a demo that feels instant and one
with a pause in the middle is whether somebody ran this before walking up.

And the cache key contains the PROVIDER and the EFFORT. That is deliberate --
the `claude -p` path sends no tools and no --model, so it is genuinely a
different answer from the SDK path, and an effort sweep must not silently
re-serve the previous setting's build. The cost is that flipping PROVIDER or
BRICOLAGE_EFFORT invalidates every entry you warmed under the old one. Warm
under exactly the settings you will present with:

    PROVIDER=anthropic scripts/prewarm.py

A degraded answer is NOT cached (that is the point of the degraded flag), so if
the network is down this script warms nothing and says so rather than pinning a
generic build for the rest of the night.

    scripts/prewarm.py                  warm the golden set
    scripts/prewarm.py "a red dragon"   warm specific prompts instead
    scripts/prewarm.py --check          warm nothing, just report what is cold
"""
from __future__ import annotations

import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bricolage"))


def main(argv: list[str]) -> int:
    check_only = "--check" in argv
    prompts = [a for a in argv if not a.startswith("-")]

    import client as client_mod
    import router
    from client import LLMClient
    from demo import rich_bin

    if not prompts:
        from tests import GOLDEN
        prompts = list(GOLDEN)

    provider = client_mod.provider()
    print(f"provider={provider}  model={client_mod.MODEL}  "
          f"effort={client_mod.EFFORT}  cache={client_mod.CACHE_DIR}")
    if provider == "mock":
        print("\nPROVIDER is unset or mock, so nothing calls a model and nothing needs\n"
              "warming. Re-run as:  PROVIDER=anthropic scripts/prewarm.py")
        return 0
    print()

    bin_summary = rich_bin().summarize()
    warmed = cold = failed = 0

    for prompt in prompts:
        _backend, noun, size, seed = router.route(prompt)
        c = LLMClient()
        t0 = time.perf_counter()

        if check_only:
            key = client_mod._cache_key(provider, client_mod.MODEL, client_mod.EFFORT,
                                        prompt, bin_summary, noun, size, seed)
            hit = client_mod._cache_get(key) is not None
            cold += not hit
            warmed += hit
            print(f"  {'warm' if hit else 'COLD':5}  {prompt}")
            continue

        try:
            c.propose_compose(prompt, bin_summary, noun, size, seed)
        except Exception as e:                       # never let one prompt stop the rest
            failed += 1
            print(f"  ERROR  {prompt:26} {type(e).__name__}: {e}")
            continue

        dt = time.perf_counter() - t0
        if c.degraded:
            failed += 1
            print(f"  FAIL   {prompt:26} {dt:5.2f}s  {c.last_error}")
        elif c.calls == 0:
            warmed += 1
            print(f"  cached {prompt:26} {dt:5.2f}s")
        else:
            warmed += 1
            print(f"  warmed {prompt:26} {dt:5.2f}s")

    print()
    if check_only:
        print(f"{warmed} warm, {cold} cold")
        return 1 if cold else 0

    print(f"{warmed}/{len(prompts)} warm" + (f", {failed} FAILED" if failed else ""))
    if failed:
        print("\nA failed prompt was answered by the offline template and deliberately NOT\n"
              "cached. Fix the network or the key and run this again -- otherwise those\n"
              "prompts each cost a full model call on stage.")
        return 1
    print("\nEvery prompt above now answers in 0.00 s. Do not change PROVIDER or\n"
          "BRICOLAGE_EFFORT after this point -- either one invalidates the cache.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
