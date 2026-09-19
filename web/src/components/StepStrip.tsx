"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { PartImage } from "@/components/three/Snapshots";
import { stepParts, type PreparedModel } from "@/lib/ldraw";

// The manual's parts rail as a film strip of step frames. The current step
// sits large and centred; earlier steps run toward the start, later ones
// toward the end (nothing before step 1). Moving the pointer along the strip
// magnifies the frames nearest to it like a dock, so a quick pass ripples.

const GAP = 12;
/** Neighbouring frames at rest, relative to the focused frame. */
const REST = 0.52;
/** How far the pointer can grow a frame, relative to the focused frame. */
const REACH = 0.9;
/** Falloff of the ripple along the strip, in multiples of the focused frame. */
const SPREAD = 0.75;
/** Frames rendered either side of the focus (the rest are off screen anyway). */
const WINDOW = 7;

type Props = {
  model: PreparedModel;
  step: number;
  onPick: (step: number) => void;
  /** "y" for the landscape side rail, "x" for the portrait bottom rail. */
  axis: "x" | "y";
};

export function StepStrip({ model, step, onPick, axis }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ w: 0, h: 0 });
  const [pointer, setPointer] = useState<number | null>(null);
  const frame = useRef(0);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setBox({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const steps = useMemo(() => Array.from({ length: model.stepCount }, (_, i) => stepParts(model, i)), [model]);

  const along = axis === "y" ? box.h : box.w;
  const across = axis === "y" ? box.w : box.h;
  const focus = Math.max(0, Math.min(across - 8, along * 0.46));

  // Resting layout: the focused frame centred, neighbours packed outward.
  const first = Math.max(0, step - WINDOW);
  const last = Math.min(steps.length - 1, step + WINDOW);
  const rest: { i: number; size: number; centre: number }[] = [];
  for (let i = first; i <= last; i++) rest.push({ i, size: i === step ? focus : focus * REST, centre: 0 });
  const place = (list: typeof rest) => {
    const f = list.findIndex((r) => r.i === step);
    list[f].centre = along / 2;
    for (let k = f + 1; k < list.length; k++) list[k].centre = list[k - 1].centre + list[k - 1].size / 2 + GAP + list[k].size / 2;
    for (let k = f - 1; k >= 0; k--) list[k].centre = list[k + 1].centre - list[k + 1].size / 2 - GAP - list[k].size / 2;
    return list;
  };
  place(rest);

  // Pointer ripple: grow each frame by its distance from the pointer on the
  // resting layout (so the sizes don't chase themselves), then re-pack.
  const frames =
    pointer === null
      ? rest
      : place(
          rest.map((r) => {
            const d = (r.centre - pointer) / (focus * SPREAD);
            const grown = focus * REST + (focus * REACH - focus * REST) * Math.exp(-d * d);
            return { ...r, size: Math.min(across - 8, Math.max(r.size, r.i === step ? r.size : grown)) };
          }),
        );

  const track = (e: React.PointerEvent) => {
    if (e.pointerType === "touch") return;
    const rect = ref.current!.getBoundingClientRect();
    const at = axis === "y" ? e.clientY - rect.top : e.clientX - rect.left;
    cancelAnimationFrame(frame.current);
    frame.current = requestAnimationFrame(() => setPointer(at));
  };

  return (
    <div
      ref={ref}
      className="relative min-h-0 min-w-0 flex-1 overflow-hidden"
      onPointerMove={track}
      onPointerLeave={() => {
        cancelAnimationFrame(frame.current);
        setPointer(null);
      }}
    >
      {focus > 0 &&
        frames.map(({ i, size, centre }) => {
          const current = i === step;
          const pos = axis === "y" ? { left: (across - size) / 2, top: centre - size / 2 } : { top: (across - size) / 2, left: centre - size / 2 };
          return (
            <button
              key={i}
              onClick={() => onPick(i)}
              aria-label={`Step ${i + 1}`}
              aria-current={current ? "step" : undefined}
              className="absolute overflow-hidden rounded-[14px] transition-[left,top,width,height,opacity] duration-150 ease-out"
              style={{
                ...pos,
                width: size,
                height: size,
                background: current ? "#ffffff" : "rgba(255,255,255,0.62)",
                boxShadow: current ? "0 0 0 3px #4f86c6, 0 6px 14px rgba(20,60,110,0.18)" : "inset 0 0 0 2px #b5d4f0",
                opacity: current || pointer !== null ? 1 : 0.8,
              }}
            >
              <FrameContent parts={steps[i]} size={size} />
              <span className="absolute left-[6px] top-[4px] font-[900] leading-none text-ink" style={{ fontSize: Math.max(11, size * 0.11) }}>
                {i + 1}
              </span>
            </button>
          );
        })}
    </div>
  );
}

/** Up to four of the step's parts, each with its "2x" count. */
function FrameContent({ parts, size }: { parts: ReturnType<typeof stepParts>; size: number }) {
  const shown = parts.slice(0, 4);
  const grid = shown.length > 1;
  const cell = grid ? size * 0.4 : size * 0.64;
  return (
    <div className={`grid h-full w-full place-items-center p-[10%] ${grid ? "grid-cols-2" : ""}`}>
      {shown.map((p) => (
        <div key={`${p.part}@${p.colour}`} className="relative grid place-items-center">
          <PartImage part={p.part} colour={p.colour} node={p.sample} size={cell} />
          <span className="absolute bottom-0 right-0 font-[800] leading-none text-ink" style={{ fontSize: Math.max(10, cell * 0.2) }}>
            {p.count}x
          </span>
        </div>
      ))}
      {parts.length > 4 && <span className="absolute bottom-[4px] right-[6px] text-[11px] font-[800] text-ink-soft">+{parts.length - 4}</span>}
    </div>
  );
}
