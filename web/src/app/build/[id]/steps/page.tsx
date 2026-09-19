"use client";

import { play } from "@/lib/sound";

import { useBuild } from "@/lib/useBuild";
import { BuildMissing } from "@/components/BuildMissing";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, RefreshCw, X } from "lucide-react";
import { BrickChip, IconTile, ChunkyButton } from "@/components/ui/controls";
import { StepStrip } from "@/components/StepStrip";
import type { ModelViewHandle } from "@/components/three/ModelView";

import type { PreparedModel } from "@/lib/ldraw";
import { useLandscape } from "@/lib/useOrientation";
import { BrickGlyph } from "@/components/ui/IsoBrick";

const ModelView = dynamic(() => import("@/components/three/ModelView").then((m) => m.ModelView), { ssr: false });

/**
 * LEGO instruction-booklet palette: the page is the signature light blue, and
 * the parts list is the booklet's paler "callout box" with a blue rule.
 */
const MANUAL = { page: "#c9e2f6", callout: "#e4f1fc", line: "#9cc5ec" };

export default function StepsPage() {
  return (
    <Suspense>
      <Steps />
    </Suspense>
  );
}

// Step viewer (IMG_1235-1241): a film strip of step frames on the left (the
// current step large, neighbours smaller, dock-style magnification on hover), the model on a light stage with new parts outlined in
// purple, prev / next tiles, close and reset-view controls.
function Steps() {
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const router = useRouter();
  const { build, live, pending } = useBuild(id);
  const landscape = useLandscape();
  const view = useRef<ModelViewHandle>(null);
  const [model, setModel] = useState<PreparedModel | null>(null);
  const [failed, setFailed] = useState(false);
  const [step, setStep] = useState(() => Math.max(0, Number(params.get("step") ?? 0) || 0));
  const [rail, setRail] = useState(true);
  // Rail size in px once the user drags the tab (null = the default size).
  const [railSize, setRailSize] = useState<number | null>(null);
  const [resizing, setResizing] = useState(false);
  const asideRef = useRef<HTMLElement>(null);
  const [hint, setHint] = useState(true);

  const count = model?.stepCount ?? 0;
  const done = model !== null && step >= count;
  const bagSize = Math.max(3, Math.ceil(count / 5));

  const go = useCallback(
    (d: number) => {
      setHint(false);
      setStep((s) => Math.max(0, Math.min(count, s + d)));
    },
    [count],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") go(1);
      if (e.key === "ArrowLeft") go(-1);
      if (e.key === "Escape") router.push(`/build/${id}`);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, router, id]);

  useEffect(() => {
    const t = setTimeout(() => setHint(false), 4200);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    if (model) window.history.replaceState(null, "", `?step=${step}`);
  }, [step, model]);

  useEffect(() => {
    if (done) play("connect", { volume: 0.6 });
  }, [done]);

  if (!build) return <BuildMissing pending={pending} live={live} />;

  return (
    <main className="fixed inset-0 flex select-none overflow-hidden" style={{ background: MANUAL.page, flexDirection: landscape ? "row" : "column-reverse" }}>
      {/* Parts rail */}
      <aside
        ref={asideRef}
        className={`relative z-20 flex shrink-0 ${resizing ? "" : "transition-[width,height] duration-300"}`}
        style={
          landscape
            ? { width: rail ? (railSize ?? "min(30vw, 300px)") : 0, paddingLeft: rail ? "calc(var(--safe-left) + 0px)" : 0, background: MANUAL.callout, borderRight: rail ? `3px solid ${MANUAL.line}` : undefined }
            : { height: rail ? (railSize ?? "calc(168px + var(--safe-bottom))") : "calc(var(--safe-bottom) + 0px)", background: MANUAL.callout, borderTop: rail ? `3px solid ${MANUAL.line}` : undefined }
        }
      >
        <div className={`flex h-full w-full overflow-hidden ${landscape ? "flex-col gap-3 px-5 py-5" : "flex-row items-center pb-[var(--safe-bottom)]"}`} style={{ opacity: rail ? 1 : 0, transition: "opacity 200ms" }}>
          {landscape && <BagBadge bag={Math.floor(Math.min(step, count - 1) / bagSize) + 1} />}
          {/* data-sound off: picking a frame already plays the landing snap */}
          <div data-sound="off" className="flex min-h-0 min-w-0 flex-1 self-stretch">
            {model && !done && <StepStrip model={model} step={step} axis={landscape ? "y" : "x"} onPick={(i) => { setHint(false); setStep(i); }} />}
          </div>
          {landscape && (
            <IconTile tone="white" label="Previous step" onClick={() => go(-1)} disabled={step === 0} size={60} data-sound="off">
              <ChevronLeft size={34} strokeWidth={2.4} />
            </IconTile>
          )}
        </div>
        {/* Drawer handle: drag to resize the rail, tap to hide or show it */}
        <button
          aria-label={rail ? "Resize or hide parts" : "Show parts"}
          onPointerDown={(e) => {
            const aside = asideRef.current;
            if (!aside) return;
            e.currentTarget.setPointerCapture(e.pointerId);
            const start = { x: e.clientX, y: e.clientY };
            const box = aside.getBoundingClientRect();
            let moved = false;
            const move = (ev: PointerEvent) => {
              if (!moved && Math.hypot(ev.clientX - start.x, ev.clientY - start.y) < 5) return;
              if (!moved) {
                moved = true;
                setResizing(true);
                setRail(true);
              }
              const size = landscape ? ev.clientX - box.left : box.bottom - ev.clientY;
              const max = landscape ? Math.min(window.innerWidth * 0.6, 640) : window.innerHeight * 0.6;
              setRailSize(Math.round(Math.max(landscape ? 180 : 120, Math.min(max, size))));
            };
            const up = () => {
              window.removeEventListener("pointermove", move);
              window.removeEventListener("pointerup", up);
              window.removeEventListener("pointercancel", up);
              setResizing(false);
              if (!moved) setRail((r) => !r);
            };
            window.addEventListener("pointermove", move);
            window.addEventListener("pointerup", up);
            window.addEventListener("pointercancel", up);
          }}
          style={{ touchAction: "none", cursor: landscape ? "ew-resize" : "ns-resize" }}
          className={`absolute z-10 grid place-items-center bg-[#a9cdef] ${landscape ? "right-[-14px] top-1/2 h-[80px] w-[14px] -translate-y-1/2 rounded-r-[10px]" : "left-1/2 top-[-14px] h-[14px] w-[80px] -translate-x-1/2 rounded-t-[10px]"}`}
        >
          <span className={`rounded-full bg-[#4f86c6] ${landscape ? "h-[40px] w-[4px]" : "h-[4px] w-[40px]"}`} />
        </button>
      </aside>

      {/* Stage */}
      <section className="relative flex-1" style={{ background: MANUAL.page }}>
        {failed ? (
          <div className="grid h-full place-items-center p-8 text-center">
            <div>
              <p className="text-[19px] font-bold text-ink">We couldn&apos;t open this manual.</p>
              <Link href={`/build/${id}`} className="mt-3 inline-block font-bold text-blue">
                Back to the build
              </Link>
            </div>
          </div>
        ) : (
          <>
            {!model && <Loading />}
            <ModelView
              ref={view}
              url={build.model}
              mode={done ? "display" : "steps"}
              step={Math.min(step, Math.max(0, count - 1))}
              shadow={done}
              onLoaded={(m) => {
                setModel(m);
                setStep((s) => Math.min(s, m.stepCount));
              }}
              onError={() => setFailed(true)}
            />
          </>
        )}

        {/* Step number */}
        {model && !done && (
          <div className="pointer-events-none absolute left-6 top-5 flex items-baseline gap-1" style={{ paddingTop: landscape ? 0 : "var(--safe-top)", marginLeft: landscape && !rail ? "var(--safe-left)" : 0 }}>
            <span className="text-[44px] font-[800] leading-none tracking-[-0.03em] text-ink">{step + 1}</span>
            <span className="text-[17px] font-semibold text-[#8c8c8c]">/{count}</span>
          </div>
        )}

        <div className="absolute right-6 top-5 flex flex-col items-center gap-6" style={{ paddingTop: landscape ? 0 : "var(--safe-top)", marginRight: "var(--safe-right)" }}>
          <IconTile tone="white" label="Close" href={`/build/${id}`} size={60}>
            <X size={34} strokeWidth={2.6} />
          </IconTile>
        </div>
        {model && !done && (
          <button
            onClick={() => view.current?.resetView()}
            aria-label="Reset view"
            className={`absolute right-6 grid h-[60px] w-[60px] place-items-center rounded-full bg-white/85 shadow-[0_2px_6px_rgba(0,0,0,0.06)] active:scale-95 ${landscape ? "top-1/2 -translate-y-1/2" : "top-[104px]"}`}
            style={{ marginRight: "var(--safe-right)", marginTop: landscape ? 0 : "var(--safe-top)" }}
          >
            <RefreshCw size={28} strokeWidth={2.2} color="#9a9a9a" />
          </button>
        )}

        {model && !done && hint && <Hand />}

        {done && (
          <>
            <p className="pointer-events-none absolute left-6 top-5 text-[34px] font-[900] leading-none tracking-[-0.02em] text-ink" style={{ paddingTop: landscape ? 0 : "var(--safe-top)" }}>
              You built it!
            </p>
            <div className={`absolute bottom-0 flex gap-3 ${landscape ? "right-0 w-[380px] px-6" : "inset-x-0 px-6"}`} style={{ paddingBottom: "calc(var(--safe-bottom) + 24px)", paddingRight: landscape ? "calc(var(--safe-right) + 24px)" : undefined }}>
              <ChunkyButton variant="white" onClick={() => setStep(0)}>
                Start over
              </ChunkyButton>
              <ChunkyButton variant="yellow" href={`/build/${id}/view`} icon={<BrickGlyph size={30} />}>
                Show off
              </ChunkyButton>
            </div>
          </>
        )}

        {/* Prev / next */}
        {!landscape && model && (
          <div className="absolute bottom-5 left-5">
            <IconTile tone="white" label="Previous step" onClick={() => go(-1)} disabled={step === 0} size={60} data-sound="off">
              <ChevronLeft size={34} strokeWidth={2.4} />
            </IconTile>
          </div>
        )}
        {model && !done && (
          <div className="absolute bottom-6 right-6" style={{ marginRight: "var(--safe-right)", marginBottom: landscape ? "var(--safe-bottom)" : 0 }}>
            <IconTile tone="white" label="Next step" onClick={() => go(1)} size={60} data-sound="off">
              <ChevronRight size={34} strokeWidth={2.4} />
            </IconTile>
          </div>
        )}
      </section>
    </main>
  );
}

function BagBadge({ bag }: { bag: number }) {
  return (
    <div className="grid h-[60px] w-[60px] shrink-0 place-items-center rounded-full bg-[#a9cdef]">
      <div className="relative grid h-[34px] w-[30px] place-items-center rounded-[4px] border-[3px] border-[#1a1a1a] bg-white">
        <span className="text-[15px] font-[900] leading-none text-ink">{bag}</span>
      </div>
    </div>
  );
}

function Loading() {
  return (
    <div className="absolute inset-0 grid place-items-center">
      <div className="flex flex-col items-center gap-3 text-[#8c8c8c]">
        <div className="h-10 w-10 animate-spin rounded-full border-[4px] border-[#cfcfcf] border-t-[#e3000b]" />
        <span className="text-[15px] font-semibold">Opening the manual…</span>
      </div>
    </div>
  );
}

/** Tutorial glove from IMG_1235: "drag to spin". */
function Hand() {
  return (
    <div className="pointer-events-none absolute left-1/2 top-1/2 flex -translate-x-1/2 translate-y-6 flex-col items-center" aria-hidden>
      <div className="relative h-[92px] w-[92px] rounded-full bg-black/10">
        <svg viewBox="0 0 64 64" width={84} height={84} className="absolute left-[18px] top-[14px] drop-shadow-[0_3px_3px_rgba(0,0,0,0.25)]" style={{ animation: "hand-tap 1.6s ease-in-out infinite" }}>
          <path
            d="M20 8c3 0 5 2 5 5v17l3-1V10c0-3 2-5 5-5s5 2 5 5v18l3 .5V14c0-3 2-5 5-5s5 2 5 5v22c0 11-7 21-19 21-8 0-13-4-17-10L6 38c-2-3-1-6 1-7.5s5-1 7 1.5l1 1.5V13c0-3 2-5 5-5z"
            fill="#fff"
            stroke="#1a1a1a"
            strokeWidth="2.6"
            strokeLinejoin="round"
          />
          <ellipse cx="33" cy="50" rx="12" ry="4" fill="#bfe3ff" opacity="0.8" />
        </svg>
      </div>
      <BrickChip bg="rgba(255,255,255,0.92)" className="mt-3 !h-8 !px-3 !text-[14px]">
        Drag to spin
      </BrickChip>
    </div>
  );
}
