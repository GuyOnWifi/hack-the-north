"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { PartImage } from "@/components/three/Snapshots";
import { stepParts, type PreparedModel } from "@/lib/ldraw";

// The manual's parts rail as a scrolling film strip of step frames, like a
// picker wheel: whichever frame is in the middle of the strip is the biggest,
// and frames shrink toward the edges. Scrolling scrubs the build: the frame in
// the middle is the current step, so the model builds up or comes apart as you
// scroll. Changing step elsewhere (arrows, keys, tapping a frame) scrolls that
// frame to the middle. Nothing sits before step 1.

const GAP = 10;
/** Layout slot per frame, relative to the biggest (centred) frame. */
const SLOT = 0.72;
/** Smallest a frame gets, relative to the biggest. */
const MIN = 0.56;

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
  const [scroll, setScroll] = useState(0);
  const raf = useRef(0);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setBox({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const steps = useMemo(() => Array.from({ length: model.stepCount }, (_, i) => stepParts(model, i)), [model]);

  const vertical = axis === "y";
  const along = vertical ? box.h : box.w;
  const across = vertical ? box.w : box.h;
  const big = Math.max(0, Math.min(across - 10, along * 0.5));
  const slot = big * SLOT;
  const pitch = slot + GAP;
  // Padding lets the first and last frames reach the middle.
  const pad = Math.max(0, (along - slot) / 2);

  // Step changes that came from the user's own scrolling must not scroll the
  // strip back (that would fight their finger); everything else re-centres.
  const fromScroll = useRef<number | null>(null);
  const smooth = useRef(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || !big) return;
    if (fromScroll.current === step) {
      fromScroll.current = null;
      return;
    }
    el.dataset.settling = smooth.current ? "1" : "0";
    el.scrollTo({ [vertical ? "top" : "left"]: step * pitch, behavior: smooth.current ? "smooth" : "auto" });
    smooth.current = true;
  }, [step, pitch, vertical, big]);

  const pick = useRef(onPick);
  const current = useRef(step);
  useEffect(() => {
    pick.current = onPick;
    current.current = step;
  }, [onPick, step]);

  const onScroll = () => {
    cancelAnimationFrame(raf.current);
    raf.current = requestAnimationFrame(() => {
      const el = ref.current;
      if (!el || !pitch) return;
      const at = vertical ? el.scrollTop : el.scrollLeft;
      setScroll(at);
      // The frame nearest the middle is the step being shown.
      const nearest = Math.max(0, Math.min(steps.length - 1, Math.round(at / pitch)));
      if (nearest !== current.current && !programmatic(el, current.current * pitch, vertical)) {
        fromScroll.current = nearest;
        pick.current(nearest);
      }
    });
  };

  return (
    <div
      ref={ref}
      onScroll={onScroll}
      onWheel={() => ref.current && (ref.current.dataset.settling = "0")}
      onTouchStart={() => ref.current && (ref.current.dataset.settling = "0")}
      className={`no-scrollbar relative min-h-0 min-w-0 flex-1 ${vertical ? "overflow-y-auto overflow-x-hidden" : "overflow-x-auto overflow-y-hidden"}`}
      style={{ scrollSnapType: `${vertical ? "y" : "x"} proximity` }}
    >
      {big > 0 && (
        <div className="relative" style={vertical ? { height: pad * 2 + steps.length * pitch - GAP } : { width: pad * 2 + steps.length * pitch - GAP, height: "100%" }}>
          {steps.map((parts, i) => {
            const centre = pad + i * pitch + slot / 2;
            const d = (centre - (scroll + along / 2)) / pitch;
            if (Math.abs(d) > along / pitch) return null;
            // Biggest in the middle, easing down toward the edges.
            const scale = MIN + (1 - MIN) * Math.exp(-d * d * 1.6);
            const current = i === step;
            return (
              <button
                key={i}
                onClick={() => onPick(i)}
                aria-label={`Step ${i + 1}`}
                aria-current={current ? "step" : undefined}
                className="absolute overflow-hidden rounded-[14px]"
                style={{
                  ...(vertical ? { left: across / 2, top: centre } : { left: centre, top: across / 2 }),
                  width: big,
                  height: big,
                  scrollSnapAlign: "center",
                  // Laid out once at full size and scaled as one unit, so the
                  // frame, bricks, counts and number always grow together.
                  transform: `translate(-50%, -50%) scale(${scale})`,
                  zIndex: Math.round(scale * 100),
                  background: current ? "#ffffff" : "rgba(255,255,255,0.7)",
                  boxShadow: current ? "0 0 0 4px #4f86c6, 0 6px 14px rgba(20,60,110,0.18)" : "inset 0 0 0 3px #b5d4f0",
                }}
              >
                <FrameContent parts={parts} size={big} />
                <span className="absolute left-[9px] top-[7px] font-[900] leading-none text-ink" style={{ fontSize: Math.max(13, big * 0.11) }}>
                  {i + 1}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

/**
 * True while a re-centring scroll we started is still travelling toward its
 * target, so passing frames on the way don't count as the user scrubbing.
 */
function programmatic(el: HTMLElement, target: number, vertical: boolean) {
  const at = vertical ? el.scrollTop : el.scrollLeft;
  const settling = el.dataset.settling === "1";
  if (Math.abs(at - target) < 2) el.dataset.settling = "0";
  return settling && Math.abs(at - target) >= 2;
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
