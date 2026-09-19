"use client";

import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";
import { useLive } from "@/lib/live";
import { tapeCopy } from "@/lib/tapeCopy";
import { ACTOR_BRICK } from "@/lib/actors";
import { notifyStep } from "@/lib/notify";

// Designing takes minutes, so every step the designer takes lands as a brick
// in the corner, wherever you are in the app: the harness talking back. The
// Designing screen already stacks the same steps into its tower, so the feed
// stays out of its way. With the app in the background they arrive as OS
// notifications instead (lib/notify.ts).
//
// The bricks time themselves out with one CSS animation (slide in, hold, fade),
// so there are no timers and no state to keep in sync.

const SHOWN = 3;

export function StepFeed() {
  const path = usePathname();
  const live = useLive();
  const sent = useRef(0);
  const events = live.tape;

  useEffect(() => {
    // one OS notification per new step, newest last
    for (const e of events.slice(sent.current)) {
      const done = e.actor === "scribe" && /^Picked version/.test(tapeCopy(e).text);
      notifyStep(live.prompt ? `Building “${live.prompt}”` : "Building", tapeCopy(e).text, done);
    }
    sent.current = events.length;
  }, [events, live.prompt]);

  if (path === "/create" || live.status !== "working") return null;
  const latest = events.slice(-SHOWN);

  return (
    <div aria-live="polite" className="pointer-events-none fixed right-3 z-50 flex w-[min(320px,calc(100vw-24px))] flex-col items-end gap-1.5" style={{ top: "calc(var(--safe-top) + 12px)" }}>
      {latest.map((e, i) => {
        const a = ACTOR_BRICK[e.actor] ?? ACTOR_BRICK.router;
        return (
          <div key={`${e.t}-${events.length - latest.length + i}`} className="w-full" style={{ animation: "step-brick 7s ease-out forwards" }}>
            <span aria-hidden className="flex justify-evenly px-4" style={{ height: 5 }}>
              {Array.from({ length: 4 }, (_, k) => (
                <span key={k} className="rounded-t-[2px]" style={{ width: 14, height: 5, background: a.brick }} />
              ))}
            </span>
            <div
            className="w-full rounded-[7px] px-3 py-2"
            style={{ background: a.brick, color: a.ink, boxShadow: "inset 0 -4px 0 rgba(0,0,0,0.2), inset 0 2px 0 rgba(255,255,255,0.22), 0 8px 20px rgba(0,0,0,0.18)" }}
            >
              <div className="text-[10px] font-[900] uppercase tracking-[0.08em] opacity-80">{a.label}</div>
              <div className="text-[13px] font-[800] leading-snug [overflow-wrap:anywhere]">{tapeCopy(e).text}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
