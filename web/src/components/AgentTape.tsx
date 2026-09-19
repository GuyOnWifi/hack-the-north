"use client";

import { useEffect, useEffectEvent, useRef, useState } from "react";
import { parseSse, type TapeActor, type TapeEvent } from "@/lib/bricolage";
import { tapeCopy } from "@/lib/tapeCopy";

// The agent tape as a tower of bricks: every step the agent takes is a brick
// in that actor's colour, landing on top of the last, on a baseplate. A step
// that fails sits crooked and cracked; once a later step fixes it, it greys
// out. Plain words up front; timings and raw lines live behind "details".

// Actor colours are real LDraw colours so the tower looks like actual bricks.
const ACTOR: Record<TapeActor, { brick: string; ink: string; label: string }> = {
  router: { brick: "#0055bf", ink: "#ffffff", label: "Router" },
  designer: { brick: "#00838f", ink: "#ffffff", label: "Designer" },
  inspector: { brick: "#c91a09", ink: "#ffffff", label: "Inspector" },
  repair: { brick: "#f2cd37", ink: "#1a1a1a", label: "Repair" },
  scribe: { brick: "#237841", ink: "#ffffff", label: "Scribe" },
};

const STUD = { w: 20, h: 7 };

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

/** A failed step counts as fixed once any later step succeeds. */
function fixedFailures(events: TapeEvent[]) {
  const fixed = new Set<number>();
  events.forEach((e, i) => {
    if (e.status === "fail" && events.slice(i + 1).some((later) => later.status === "ok")) fixed.add(i);
  });
  return fixed;
}

/** The agent's working log, stacked as a tower of bricks (newest on top). */
export function AgentTape({ events, live }: { events: TapeEvent[]; live?: boolean; compact?: boolean }) {
  const top = useRef<HTMLDivElement>(null);
  const [details, setDetails] = useState(false);
  useEffect(() => {
    top.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [events.length, live]);
  const fixed = fixedFailures(events);
  const order = events.map((e, i) => ({ e, i })).reverse();

  return (
    <div className="flex min-w-0 flex-col" aria-live="polite">
      <div ref={top} />
      {live && <PendingBrick />}
      {order.map(({ e, i }) => (
        <TapeBrick key={`${e.t}-${i}`} event={e} index={i} fixed={fixed.has(i)} details={details} />
      ))}
      <Baseplate />
      {events.length > 0 && (
        <button type="button" onClick={() => setDetails((d) => !d)} className="mt-2 self-end px-1 text-[12px] font-bold text-ink-soft underline-offset-2 hover:underline">
          {details ? "Hide details" : "Show details"}
        </button>
      )}
    </div>
  );
}

function Studs({ colour, count = 5 }: { colour: string; count?: number }) {
  return (
    <div aria-hidden className="flex justify-evenly px-3" style={{ height: STUD.h }}>
      {Array.from({ length: count }, (_, k) => (
        <span key={k} className="rounded-t-[3px]" style={{ width: STUD.w, height: STUD.h, background: colour, boxShadow: "inset 0 2px 0 rgba(255,255,255,0.28)" }} />
      ))}
    </div>
  );
}

function TapeBrick({ event: e, index, fixed, details }: { event: TapeEvent; index: number; fixed: boolean; details: boolean }) {
  const a = ACTOR[e.actor] ?? ACTOR.router;
  const copy = tapeCopy(e);
  const failed = e.status === "fail";
  const warned = e.status === "warn";
  const brick = fixed ? "#a0a5a9" : a.brick;
  const ink = fixed ? "#ffffff" : a.ink;
  // Hand-stacked: bricks sit a few px off each other; a failure sits crooked.
  const nudge = [0, 6, -4, 3, -6, 2][index % 6];
  const tilt = failed && !fixed ? -2.4 : 0;
  return (
    <div className="relative" style={{ animation: "brick-drop 320ms cubic-bezier(.2,1.4,.4,1) both", marginLeft: Math.max(0, nudge), marginRight: Math.max(0, -nudge) }}>
      <div style={{ transform: `rotate(${tilt}deg)`, transformOrigin: "left bottom", transition: "transform 300ms" }}>
        <Studs colour={brick} />
        <div className="relative rounded-[5px] px-3.5 pb-3 pt-2.5" style={{ background: brick, color: ink, boxShadow: "inset 0 -5px 0 rgba(0,0,0,0.2), inset 0 2px 0 rgba(255,255,255,0.22)" }}>
          <div className="flex items-center justify-between gap-2">
            <span className="text-[11px] font-[900] uppercase tracking-[0.08em] opacity-80">{a.label}</span>
            <StatusMark status={e.status} fixed={fixed} ink={ink} />
          </div>
          <div className="mt-0.5 text-[15px] font-[800] leading-snug [overflow-wrap:anywhere]" style={{ textDecorationLine: fixed ? "line-through" : "none", textDecorationThickness: 2 }}>
            {copy.text}
          </div>
          {copy.parts && copy.parts.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {copy.parts.map((p) => (
                <span key={p} className="rounded-[4px] px-2 py-0.5 text-[12px] font-[800]" style={{ background: "rgba(255,255,255,0.22)" }}>
                  {p}
                </span>
              ))}
            </div>
          )}
          {fixed && <div className="mt-1 text-[12px] font-bold opacity-90">Fixed further up</div>}
          {warned && !fixed && <div className="mt-1 text-[12px] font-bold opacity-90">Worked around it</div>}
          {details && (
            <div className="mt-2 rounded-[4px] px-2 py-1.5 font-mono text-[11px] leading-snug [overflow-wrap:anywhere]" style={{ background: "rgba(0,0,0,0.18)" }}>
              {e.text}
              <div className="mt-0.5 opacity-80">
                {e.ms >= 1000 ? `${(e.ms / 1000).toFixed(1)}s` : `${e.ms}ms`}
                {e.tokens > 0 && ` · ${e.tokens.toLocaleString()} tokens`}
              </div>
            </div>
          )}
          {failed && !fixed && <Crack />}
        </div>
      </div>
    </div>
  );
}

/** Status as a stud: seated (ok), cross (fail), half-seated (warn), spinning (running). */
function StatusMark({ status, fixed, ink }: { status: TapeEvent["status"]; fixed: boolean; ink: string }) {
  const ring = { width: 16, height: 16, borderRadius: 999, border: `2.5px solid ${ink}` } as const;
  if (status === "running") return <span aria-label="Working" className="animate-spin" style={{ ...ring, borderTopColor: "transparent" }} />;
  if (status === "fail" && !fixed)
    return (
      <span aria-label="Didn't fit" className="text-[15px] font-[900] leading-none">
        ✕
      </span>
    );
  if (status === "warn") return <span aria-label="Partly fitted" style={{ ...ring, background: `linear-gradient(90deg, ${ink} 50%, transparent 50%)` }} />;
  return <span aria-label="Fitted" style={{ ...ring, background: ink }} />;
}

/** A jagged crack across a brick that didn't fit. */
function Crack() {
  return (
    <svg aria-hidden viewBox="0 0 60 40" className="pointer-events-none absolute right-10 top-1 h-[calc(100%-8px)] w-12 opacity-45">
      <path d="M30 0 L24 12 L33 18 L26 29 L31 40" fill="none" stroke="#1a1a1a" strokeWidth="2.4" strokeLinejoin="round" />
    </svg>
  );
}

/** The brick being placed right now: a dashed outline waiting to be filled. */
function PendingBrick() {
  return (
    <div className="animate-pulse">
      <div aria-hidden className="flex justify-evenly px-3" style={{ height: STUD.h }}>
        {Array.from({ length: 5 }, (_, k) => (
          <span key={k} className="rounded-t-[3px] border-2 border-b-0 border-dashed border-[#9cc5ec]" style={{ width: STUD.w, height: STUD.h }} />
        ))}
      </div>
      <div className="flex h-[52px] items-center rounded-[5px] border-2 border-dashed border-[#9cc5ec] px-3.5 text-[13px] font-bold text-ink-soft">Placing the next brick…</div>
    </div>
  );
}

/** Where the tower stands. */
function Baseplate() {
  return (
    <div aria-hidden>
      <div className="flex h-[5px] justify-evenly px-1">
        {Array.from({ length: 14 }, (_, k) => (
          <span key={k} className="rounded-t-[2px]" style={{ width: 12, height: 5, background: "#9cc5ec" }} />
        ))}
      </div>
      <div className="h-[9px] rounded-[3px]" style={{ background: "#9cc5ec", boxShadow: "inset 0 -3px 0 rgba(0,0,0,0.1)" }} />
    </div>
  );
}
