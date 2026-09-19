"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { Play, X } from "lucide-react";
import { FloatingBricks, PlateProgress } from "@/components/ui/chrome";
import { ChunkyButton, IconTile } from "@/components/ui/controls";
import { AgentTape } from "@/components/AgentTape";
import { designBuild, getSteers, steer, tryAnother, useLive } from "@/lib/live";
import { LIVE_ID } from "@/lib/useBuild";

const ModelView = dynamic(() => import("@/components/three/ModelView").then((m) => m.ModelView), { ssr: false });

export default function CreatePage() {
  return (
    <Suspense>
      <Create />
    </Suspense>
  );
}

const EXPECTED_EVENTS = 6;

// Designing (IMG_1230 studio): the agent tape streams in live while Lane B
// routes, designs, inspects, repairs and sequences; then we open the build.
function Create() {
  const params = useSearchParams();
  const prompt = params.get("prompt")?.trim() || "build a rover";
  const live = useLive();
  const started = useRef<string | null>(null);

  useEffect(() => {
    if (started.current === prompt) return;
    started.current = prompt;
    designBuild(prompt);
  }, [prompt]);

  const valid = live.payload?.report?.ok !== false;

  const events = live.prompt === prompt ? live.tape : [];
  const done = live.status === "ready" && live.prompt === prompt;
  const modelUrl = done ? live.modelUrl : null;

  // once the model resolves, stream it together brick-by-brick on this screen
  const [mSteps, setMSteps] = useState<number | null>(null);
  const [astep, setAstep] = useState(0);
  const [assembling, setAssembling] = useState(true);
  const [playToken, setPlayToken] = useState(0);
  useEffect(() => {
    setMSteps(null);
    setAstep(0);
    setAssembling(true);
  }, [modelUrl]);
  useEffect(() => {
    if (mSteps == null) return;
    setAstep(0);
    setAssembling(true);
    let s = 0;
    const iv = setInterval(() => {
      s += 1;
      setAstep(s);
      if (s >= (mSteps ?? 0)) {
        clearInterval(iv);
        setTimeout(() => setAssembling(false), 500);
      }
    }, 340);
    return () => clearInterval(iv);
  }, [mSteps, playToken]);
  const failed = live.status === "error" && live.prompt === prompt;
  const progress = done ? 1 : Math.min(0.92, events.length / EXPECTED_EVENTS);

  // show the physics: connection nodes at every joint the solver checked.
  // off by default (clean model); the toggle reveals the joint layer.
  const [showJoints, setShowJoints] = useState(false);
  const physicsJointCount = live.payload?.physics?.studs ?? 0;

  // stop-and-steer: correct the build in natural language while it streams
  const [steerText, setSteerText] = useState("");
  const [steers, setSteers] = useState<string[]>([]);
  const submitSteer = () => {
    const t = steerText.trim();
    if (!t) return;
    steer(t);
    setSteers(getSteers());
    setSteerText("");
  };

  return (
    <main className="fixed inset-0 flex flex-col items-center overflow-y-auto" style={{ background: "linear-gradient(180deg,#6e6e6e 0%,#838383 50%,#959595 100%)" }}>
      <FloatingBricks tone="grey" />
      <div className="absolute right-5 top-5 z-10" style={{ marginTop: "var(--safe-top)" }}>
        <IconTile tone="glass-light" label="Cancel" href="/builds" size={60}>
          <X size={32} strokeWidth={2.6} />
        </IconTile>
      </div>

      <div className="relative z-10 flex w-full max-w-[520px] flex-1 flex-col px-5" style={{ paddingTop: "calc(var(--safe-top) + 96px)" }}>
        <p className="text-center text-[15px] font-bold uppercase tracking-wide text-white/70">{done ? (valid ? "Designed" : "Almost") : "Designing"}</p>
        <h1 className="mt-1 text-center text-[28px] font-[900] leading-tight tracking-[-0.02em] text-white">&ldquo;{prompt}&rdquo;</h1>
        {live.source === "fixture" && live.prompt === prompt && <p className="mt-2 text-center text-[14px] font-semibold text-white/80">The builder is offline, so this is the saved sample.</p>}

        {/* the model streams itself together, brick by brick, right here */}
        {modelUrl && (
          <div className="relative mt-5 h-[268px] shrink-0 overflow-hidden rounded-[24px]" style={{ background: "linear-gradient(180deg,#0b1c22 0%,#376275 100%)", animation: "tape-in 300ms ease-out" }}>
            <ModelView url={modelUrl} mode={assembling ? "timeline" : "display"} step={astep} spin={assembling ? 0 : 0.15} joints={showJoints} broken={live.payload?.physics?.broken} shadow onLoaded={(m) => setMSteps(m.stepCount)} onError={() => {}} />
            {/* joints toggle — see the physics: a node at every connection the
                solver checked, red where it couldn't hold. */}
            <button
              onClick={() => setShowJoints((v) => !v)}
              className={`pointer-events-auto absolute left-3 top-3 flex items-center gap-1.5 rounded-full px-3 py-1 text-[12px] font-bold backdrop-blur active:scale-95 ${showJoints ? "bg-[#2fd66f] text-ink" : "bg-black/45 text-white"}`}
            >
              <span className="text-[14px] leading-none">◉</span> {physicsJointCount ? `${physicsJointCount} joints` : "joints"}
            </button>
            <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-center justify-between px-3 pb-2.5">
              {assembling ? (
                <span className="rounded-full bg-black/45 px-3 py-1 text-[13px] font-semibold text-white backdrop-blur">assembling · brick {Math.min(astep, mSteps ?? 0)}/{mSteps ?? "…"}</span>
              ) : (
                <button onClick={() => setPlayToken((t) => t + 1)} className="pointer-events-auto flex items-center gap-1 rounded-full bg-white/90 px-3 py-1 text-[13px] font-bold text-ink active:scale-95">
                  <Play size={14} fill="#1a1a1a" /> replay
                </button>
              )}
              {!valid && <span className="rounded-full bg-[#e02436] px-3 py-1 text-[13px] font-bold text-white shadow">⚠ won&apos;t stand</span>}
            </div>
            {!valid && <div className="pointer-events-none absolute inset-2 rounded-[18px] ring-2 ring-[#e02436]/70" style={{ animation: "pulse 1.4s ease-in-out infinite" }} />}
          </div>
        )}

        {/* stop-and-steer — sits right under the render so you always steer the
            thing you're looking at, mid-build or after. */}
        <div className="mt-4 shrink-0">
          {steers.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-1.5">
              {steers.map((s, i) => (
                <span key={i} className="rounded-full bg-purple/85 px-2.5 py-1 text-[12px] font-semibold text-white backdrop-blur">
                  ↳ {s}
                </span>
              ))}
            </div>
          )}
          <div className="flex items-center gap-2 rounded-[18px] bg-white p-1.5 pl-4 shadow-[0_10px_30px_rgba(0,0,0,0.3)] ring-2 ring-purple/40">
            <input
              value={steerText}
              onChange={(e) => setSteerText(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submitSteer()}
              placeholder="Steer it — “not a 2d flower, a 3d one”"
              className="min-w-0 flex-1 bg-transparent text-[15px] font-semibold text-ink outline-none placeholder:text-ink-soft/70"
            />
            <button
              onClick={submitSteer}
              disabled={!steerText.trim()}
              className="shrink-0 rounded-[13px] bg-purple px-5 py-2 text-[15px] font-[800] text-white active:scale-95 disabled:opacity-40"
            >
              Steer
            </button>
          </div>
        </div>

        <div className="no-scrollbar mt-4 min-h-0 flex-1 overflow-auto rounded-[24px] bg-[#eef0f2]/90 p-3 shadow-[0_18px_40px_rgba(0,0,0,0.25)]">
          {failed ? (
            <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
              <p className="text-[19px] font-[800] text-ink">The builder didn&apos;t answer</p>
              <p className="text-[15px] text-ink-soft">{live.error}</p>
              <div className="mt-2 flex w-full gap-3">
                <ChunkyButton variant="white" href="/builds">
                  Back
                </ChunkyButton>
                <ChunkyButton variant="blue" onClick={() => designBuild(prompt)}>
                  Try again
                </ChunkyButton>
              </div>
            </div>
          ) : events.length === 0 ? (
            <div className="flex h-full items-center justify-center gap-2 text-[15px] font-semibold text-ink-soft">
              <span className="h-2 w-2 animate-pulse rounded-full bg-purple" /> Reading your bricks…
            </div>
          ) : (
            <AgentTape events={events} live={!done} />
          )}
        </div>
        {done && !valid && (
          <div className="mt-4 rounded-[20px] bg-white p-4" style={{ animation: "tape-in 260ms ease-out" }}>
            <p className="text-[17px] font-[800] text-ink">That design doesn&apos;t fit your bricks yet</p>
            <ul className="mt-2 flex flex-col gap-1.5">
              {live.payload?.report?.errors.map((e, i) => (
                <li key={i} className="rounded-[12px] bg-[#fde8ea] px-3 py-2 text-[14px] font-semibold text-[#9b1020]">
                  {e.human}
                </li>
              ))}
            </ul>
            <div className="mt-4 flex gap-3">
              <ChunkyButton variant="white" href="/builds" className="!text-[16px]">
                New idea
              </ChunkyButton>
              <ChunkyButton variant="blue" className="!text-[16px]" onClick={() => tryAnother().catch(() => {})}>
                Try another
              </ChunkyButton>
            </div>
          </div>
        )}
        {done && valid && (
          <Link href={`/build/${LIVE_ID}`} className="mt-4 text-center text-[16px] font-bold text-white underline-offset-4 hover:underline">
            Open the build
          </Link>
        )}
      </div>

      <div className="relative z-10 pt-6" style={{ paddingBottom: "calc(var(--safe-bottom) + 30px)" }}>
        <PlateProgress value={progress} count={14} />
      </div>
    </main>
  );
}
