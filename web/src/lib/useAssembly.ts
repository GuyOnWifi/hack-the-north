"use client";

import { useEffect, useState } from "react";

/** Brick-by-brick assembly playback: reveals one step every `interval` ms once
 *  `start(stepCount)` is called, then settles. State lives in the clock, not in
 *  effects, so a new model (a different `key`) simply starts from nothing. */
export function useAssembly(key: unknown, interval = 340) {
  const [run, setRun] = useState<{ key: unknown; steps: number; start: number } | null>(null);
  const [now, setNow] = useState(0);
  const current = run && run.key === key ? run : null;

  useEffect(() => {
    if (!current) return;
    const end = current.start + current.steps * interval + 500;
    const tick = setInterval(() => {
      const t = performance.now();
      setNow(t);
      if (t >= end) clearInterval(tick);
    }, interval / 3);
    return () => clearInterval(tick);
  }, [current, interval]);

  const elapsed = current ? Math.max(0, now - current.start) : 0;
  return {
    /** Total steps, once the model has loaded. */
    steps: current?.steps ?? null,
    /** Steps revealed so far. */
    step: current ? Math.min(current.steps, Math.floor(elapsed / interval)) : 0,
    /** True until the last step has landed (and while waiting for the model). */
    assembling: !current || elapsed < current.steps * interval + 500,
    start: (steps: number) => setRun({ key, steps, start: performance.now() }),
    replay: () => setRun((r) => (r ? { ...r, start: performance.now() } : r)),
  };
}
