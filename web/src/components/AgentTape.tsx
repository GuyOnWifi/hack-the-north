"use client";

import { useEffect, useEffectEvent, useRef, useState } from "react";
import { Check, Loader2, TriangleAlert, X } from "lucide-react";
import { BrickChip } from "@/components/ui/controls";
import { parseSse, type TapeActor, type TapeEvent, type TapeStatus } from "@/lib/bricolage";

// Actor colours follow Lane B's dev console so the two read the same.
const ACTOR: Record<TapeActor, { bg: string; ink: string; label: string }> = {
  router: { bg: "#e5efff", ink: "#2458ca", label: "Router" },
  designer: { bg: "#dff7fb", ink: "#0e7c8c", label: "Designer" },
  inspector: { bg: "#fde4e4", ink: "#c20009", label: "Inspector" },
  repair: { bg: "#fff4d6", ink: "#946200", label: "Repair" },
  scribe: { bg: "#e3f5e8", ink: "#1f7a3a", label: "Scribe" },
};

const STATUS: Record<TapeStatus, { icon: typeof Check; ink: string }> = {
  ok: { icon: Check, ink: "#1f7a3a" },
  fail: { icon: X, ink: "#c0182b" },
  warn: { icon: TriangleAlert, ink: "#b27a00" },
  running: { icon: Loader2, ink: "#8c8c8c" },
};

let fixtureTape: Promise<TapeEvent[]> | null = null;

/** Lane B's recorded tape (fixtures/tape.sse), for the bundled sample builds. */
export function useFixtureTape() {
  const [events, setEvents] = useState<TapeEvent[]>([]);
  useEffect(() => {
    let alive = true;
    fixtureTape ??= fetch("/bricolage-fixtures/tape.sse")
      .then((r) => r.text())
      .then(parseSse)
      .catch(() => []);
    fixtureTape.then((e) => alive && setEvents(e));
    return () => {
      alive = false;
    };
  }, []);
  return events;
}

/**
 * Plays a recorded run with its own timing (compressed), restarting whenever
 * runKey changes; onDone fires after the last event lands.
 */
export function useTapePlayback(events: TapeEvent[], runKey: number | null, onDone?: () => void) {
  const [run, setRun] = useState({ key: -1, shown: 0 });
  const done = useEffectEvent(() => onDone?.());
  useEffect(() => {
    if (runKey === null || !events.length) return;
    const timers: ReturnType<typeof setTimeout>[] = [setTimeout(() => setRun({ key: runKey, shown: 0 }), 0)];
    let at = 0;
    let last = 0;
    events.forEach((e, i) => {
      at += Math.min(900, Math.max(220, (e.t - last) * 0.4));
      last = e.t;
      timers.push(setTimeout(() => setRun({ key: runKey, shown: i + 1 }), at));
    });
    timers.push(setTimeout(done, at + 500));
    return () => timers.forEach(clearTimeout);
  }, [events, runKey]);
  return runKey === null || run.key !== runKey ? [] : events.slice(0, run.shown);
}

/** The agent's working log: who acted, what they did, and whether it held up. */
export function AgentTape({ events, live, compact }: { events: TapeEvent[]; live?: boolean; compact?: boolean }) {
  const end = useRef<HTMLLIElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [events.length, live]);
  return (
    <ol className="flex flex-col gap-2" aria-live="polite">
      {events.map((e, i) => {
        const a = ACTOR[e.actor] ?? ACTOR.router;
        const s = STATUS[e.status] ?? STATUS.ok;
        const Icon = s.icon;
        return (
          <li key={`${e.t}-${i}`} className="flex items-start gap-3 rounded-[14px] bg-white px-3 py-2.5 shadow-[0_2px_0_rgba(0,0,0,0.06)]" style={{ animation: "tape-in 260ms ease-out" }}>
            <BrickChip size="sm" bg={a.bg} ink={a.ink} studs={2} className="uppercase tracking-wide">
              {a.label}
            </BrickChip>
            <div className="min-w-0 flex-1">
              <div className={`text-[14px] font-semibold leading-snug text-ink ${compact ? "line-clamp-2" : ""}`}>{e.text}</div>
              {(e.ms > 0 || e.tokens > 0) && (
                <div className="mt-0.5 text-[12px] font-semibold text-ink-soft">
                  {e.ms > 0 && `${e.ms >= 1000 ? `${(e.ms / 1000).toFixed(1)}s` : `${e.ms}ms`}`}
                  {e.tokens > 0 && ` · ${e.tokens.toLocaleString()} tokens`}
                </div>
              )}
            </div>
            <Icon size={18} strokeWidth={2.8} color={s.ink} className={`mt-0.5 shrink-0 ${e.status === "running" ? "animate-spin" : ""}`} />
          </li>
        );
      })}
      <li ref={end} className="flex items-center gap-2 px-3 py-1 text-[13px] font-semibold text-ink-soft" style={{ visibility: live ? "visible" : "hidden" }}>
        <span className="h-2 w-2 animate-pulse rounded-full bg-ai" /> Working…
      </li>
    </ol>
  );
}
