"use client";

import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { Play, X } from "lucide-react";
import { GhostBricks, PlateProgress } from "@/components/ui/chrome";
import { BrickChip, ChunkyButton, IconTile } from "@/components/ui/controls";
import { BrickGlyph } from "@/components/ui/IsoBrick";
import { AgentTape } from "@/components/AgentTape";
import { StepBell } from "@/components/StepBell";
import { BrickLoader, LogoLockup } from "@/components/ui/Logo";
import { chooseDesign, designBuild, tryAnother, useLive } from "@/lib/live";
import { LIVE_ID } from "@/lib/useBuild";
import { useAssembly } from "@/lib/useAssembly";
import { useLandscape } from "@/lib/useOrientation";
import { tapeCopy } from "@/lib/tapeCopy";

const ModelView = dynamic(() => import("@/components/three/ModelView").then((m) => m.ModelView), { ssr: false });

export default function CreatePage() {
  return (
    <Suspense>
      <Create />
    </Suspense>
  );
}

const EXPECTED_EVENTS = 16; // roughly what one design run emits
const RAIL_W = 400;
const RAIL_H = "46%";

// Designing: the same full studio as the viewer (rule 10) with the model
// floating in it, while the agent tape docks along the edge (rule 12) and the
// design builds itself brick by brick in front of you.
function Create() {
  const params = useSearchParams();
  const prompt = params.get("prompt")?.trim() || "build a rover";
  const fromSketch = params.get("sketch") === "1";
  const live = useLive();
  const landscape = useLandscape();
  const started = useRef<string | null>(null);

  useEffect(() => {
    if (started.current === prompt) return;
    started.current = prompt;
    designBuild(prompt, { sketch: fromSketch });
  }, [prompt, fromSketch]);

  const valid = live.payload?.report?.ok !== false; // renderable / openable
  const stable = live.payload?.physics?.stable !== false; // physically stands?
  const overlaps = !!live.payload?.report?.warnings?.some((w) => w.code === "OVERLAP");

  const events = live.prompt === prompt ? live.tape : [];
  const done = live.status === "ready" && live.prompt === prompt;
  // show the finished model when it lands; while working, show the newest
  // round the designer has built so far
  const isDraft = !done && !!live.partialUrl && live.prompt === prompt;
  const modelUrl = done ? live.modelUrl : isDraft ? live.partialUrl : null;
  const lastEvent = [...events].reverse().find((e) => e.text);
  const lastThink = lastEvent ? tapeCopy(lastEvent).text : "Reading your idea…";
  const failed = live.status === "error" && live.prompt === prompt;
  const progress = done ? 1 : Math.min(0.92, events.length / EXPECTED_EVENTS);

  const assembly = useAssembly(modelUrl);
  const { steps: mSteps, step: astep, assembling } = assembly;

  return (
    <main className="fixed inset-0 select-none overflow-hidden" style={{ background: "#e4f1fc" }}>
      {/* the stage gives up its space to the docked tape, never sits under it */}
      <div
        className="absolute left-0 top-0 overflow-hidden transition-[right,bottom] duration-300 ease-out"
        style={{ right: landscape ? RAIL_W : 0, bottom: landscape ? 0 : RAIL_H, background: "linear-gradient(180deg,#8dbbe7 0%,#acd0f0 42%,#c9e2f6 100%)" }}
      >
        <GhostBricks seed={73} cols={5} rows={3} scale={1.5} color="#123a8c" opacity={0.1} skip={0.25} />

        {live.art.length > 0 && (
          <div className={`pointer-events-none absolute z-10 ${modelUrl ? "bottom-24 right-5 w-[190px]" : "inset-0 grid place-items-center px-6"}`}>
            <div className={modelUrl ? "" : "flex flex-col items-center gap-3"}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={live.art[0].image}
                alt="The concept art the designer is working from"
                className="rounded-[14px] bg-white object-contain shadow-[0_10px_30px_rgba(20,40,80,0.25)]"
                style={{ width: modelUrl ? 190 : "min(78vw, 620px)", maxHeight: modelUrl ? undefined : "62vh", border: "4px solid #ffffff" }}
              />
              {!modelUrl && <p className="text-[17px] font-[800] text-ink">{lastThink}</p>}
            </div>
          </div>
        )}

        {modelUrl ? (
          <ModelView
            url={modelUrl}
            mode={isDraft || !assembling ? "display" : "timeline"}
            step={astep}
            landed={isDraft ? live.partialLanded : 0}
            zoom={isDraft ? 0.42 : 1}
            spin={isDraft || !assembling ? 0.15 : 0}
            shadow
            onLoaded={(m) => !isDraft && assembly.start(m.stepCount)}
            onError={() => {}}
          />
        ) : live.art.length === 0 ? (
          <div className="pointer-events-none absolute inset-0 grid place-items-center px-8">
            <div className="flex flex-col items-center gap-4 text-center">
              {!failed && <BrickLoader size={64} label="Designing your model…" />}
              <p className="max-w-[420px] text-[17px] font-[800] leading-snug text-ink">{lastThink}</p>
            </div>
          </div>
        ) : null}

        {live.choices.length > 0 && <Chooser choices={live.choices} />}

        <div className="absolute left-0 top-0 flex items-center gap-3 p-5" style={{ paddingLeft: "calc(var(--safe-left) + 20px)", paddingTop: "calc(var(--safe-top) + 16px)" }}>
          <LogoLockup size={24} />
        </div>

        <div className="absolute right-0 top-0 flex items-center gap-2 p-5" style={{ paddingRight: "calc(var(--safe-right) + 12px)", paddingTop: "calc(var(--safe-top) + 12px)" }}>
          <StepBell />
          <IconTile tone="white" label="Cancel" href="/builds" size={56}>
            <X size={30} strokeWidth={2.6} />
          </IconTile>
        </div>

        {/* what it is and how it's going, along the bottom of the stage */}
        <div className="pointer-events-none absolute inset-x-0 bottom-0 flex flex-col gap-3 px-6 pb-5" style={{ paddingBottom: "calc(var(--safe-bottom) + 18px)" }}>
          <div className="flex flex-wrap items-end gap-2">
            {modelUrl && !isDraft &&
              (assembling ? (
                <BrickChip size="sm">
                  Brick {Math.min(astep, mSteps ?? 0)} of {mSteps ?? "…"}
                </BrickChip>
              ) : (
                <BrickChip size="sm" className="pointer-events-auto" onClick={assembly.replay}>
                  <Play size={12} fill="#1a1a1a" /> Replay
                </BrickChip>
              ))}
            {isDraft && (
              <BrickChip size="sm" bg="#237841" ink="#ffffff">
                Building it now
              </BrickChip>
            )}
            {modelUrl && !stable && (
              <BrickChip size="sm" bg="#e3000b" ink="#ffffff">
                Won&apos;t stand up
              </BrickChip>
            )}
            {modelUrl && done && overlaps && (
              <BrickChip size="sm" bg="#e3000b" ink="#ffffff">
                Some pieces overlap
              </BrickChip>
            )}
          </div>
          <div className="flex items-end justify-between gap-4">
            <div className="min-w-0">
              <p className="text-[13px] font-[800] uppercase tracking-[0.1em] text-ink-soft">{done ? (valid ? "Designed" : "Almost") : "Designing"}</p>
              <h1 className="truncate text-[26px] font-[900] leading-tight tracking-[-0.02em] text-ink">&ldquo;{prompt}&rdquo;</h1>
            </div>
            <div className="shrink-0 pb-1">
              <PlateProgress value={progress} count={14} />
            </div>
          </div>
        </div>
      </div>

      {/* the agent tape, docked: the harness talking while it works */}
      <aside
        className="absolute z-40 flex min-w-0 flex-col overflow-hidden"
        style={
          landscape
            ? { top: 0, right: 0, bottom: 0, width: RAIL_W, background: "#e4f1fc", borderLeft: "3px solid #9cc5ec", paddingTop: "var(--safe-top)", paddingRight: "var(--safe-right)" }
            : { left: 0, right: 0, bottom: 0, height: RAIL_H, background: "#e4f1fc", borderTop: "3px solid #9cc5ec" }
        }
      >
        <header className="flex items-center justify-between gap-2 px-5 pb-2 pt-4">
          <span className="text-[19px] font-[800] text-ink">{done ? "How it was built" : "Building it"}</span>
          {!done && <span className="h-2.5 w-2.5 animate-pulse rounded-[2px] bg-ai" />}
        </header>

        <div className="no-scrollbar min-h-0 flex-1 overflow-y-auto px-5 pb-2">
          {failed ? (
            <div className="flex flex-col items-center justify-center gap-3 py-6 text-center">
              <p className="text-[17px] font-[800] text-ink">The builder didn&apos;t answer</p>
              <p className="text-[15px] text-ink-soft">{live.error}</p>
              <ChunkyButton variant="blue" onClick={() => designBuild(prompt)}>
                Try again
              </ChunkyButton>
            </div>
          ) : events.length === 0 ? (
            <div className="grid h-full place-items-center">
              <BrickLoader size={44} label="Reading your idea…" />
            </div>
          ) : (
            <AgentTape events={events} live={!done} />
          )}
        </div>

        <div className="shrink-0 border-t-2 border-[#9cc5ec] px-5 pb-4 pt-3" style={{ paddingBottom: landscape ? "calc(var(--safe-bottom) + 16px)" : "calc(var(--safe-bottom) + 12px)" }}>
          {failed ? null : done && valid ? (
            <div className="flex gap-3">
              <ChunkyButton variant="white" className="!text-[16px]" onClick={() => tryAnother().catch(() => {})}>
                Try another
              </ChunkyButton>
              <ChunkyButton variant="yellow" className="!text-[16px]" href={`/build/${LIVE_ID}`} icon={<BrickGlyph size={30} />}>
                Open it
              </ChunkyButton>
            </div>
          ) : (
            <p className="text-center text-[14px] font-semibold text-ink-soft">You get to change it once the design is ready.</p>
          )}
          {done && !valid && (
            <ul className="mt-2 flex flex-col gap-1.5">
              {live.payload?.report?.errors.map((e, i) => (
                <li key={i} className="rounded-[10px] bg-[#fde8ea] px-3 py-2 text-[14px] font-semibold text-[#9b1020]">
                  {e.human}
                </li>
              ))}
            </ul>
          )}
          {live.source === "fixture" && live.prompt === prompt && <p className="mt-2 text-center text-[13px] font-semibold text-ink-soft">The builder is offline, so this is the saved sample.</p>}
        </div>
      </aside>
    </main>
  );
}

/** Your say on what was built: every version this run made, the critic's
 *  favourite marked, and a box to say what to change. Renders, not live 3D,
 *  so the screen keeps one canvas. */
function Chooser({ choices }: { choices: { n: number; style: string; stands: boolean; preferred?: boolean; parts?: number; image?: string; ldr: string }[] }) {
  const [note, setNote] = useState("");
  const one = choices.length === 1;
  return (
    <div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-4 overflow-y-auto px-5 py-6" style={{ background: "rgba(228,241,252,0.94)" }}>
      <p className="text-[22px] font-[900] tracking-[-0.02em] text-ink">{one ? "How does that look?" : "Keep which one?"}</p>
      <div className="flex flex-wrap items-stretch justify-center gap-3">
        {choices.map((c, i) => (
          <button
            key={c.n}
            onClick={() => chooseDesign(i, note)}
            className="chunky flex flex-col items-center gap-2 rounded-[20px] bg-white p-3 transition-transform active:scale-95"
            style={{ ["--rim" as string]: c.preferred && !one ? "#e3000b" : "#9cc5ec", ["--lift" as string]: "5px", width: one ? "min(82vw, 560px)" : "min(44vw, 330px)" }}
          >
            {c.image ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={c.image}
                alt={c.style || `Version ${c.n}`}
                className="w-full rounded-[14px] object-contain"
                style={{ height: one ? "min(52vh, 420px)" : "min(34vh, 260px)" }}
              />
            ) : (
              <div className="w-full rounded-[14px] bg-[#e4f1fc]" style={{ height: one ? 420 : 260 }} />
            )}
            <span className="text-[15px] font-[800] leading-tight text-ink">{one ? "Build this one" : c.style || `Version ${c.n}`}</span>
            <span className="flex items-center gap-2 text-[13px] font-[800] text-ink-soft">
              {c.parts ? `${c.parts} bricks` : ""}
              {c.preferred && !one && <span className="rounded-[4px] bg-ai px-1.5 py-0.5 text-white">critic&apos;s pick</span>}
              {!c.stands && <span className="text-ai">tips over</span>}
            </span>
          </button>
        ))}
      </div>
      <div className="flex w-full max-w-[600px] items-center gap-2 rounded-[16px] bg-white p-1.5 pl-4 ring-2 ring-ai/40">
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder={one ? "Or say what to change: “bigger wheels”" : "Pick one, and say what to change: “bigger wheels”"}
          className="min-w-0 flex-1 bg-transparent text-[15px] font-semibold text-ink outline-none placeholder:text-ink-soft/70"
        />
      </div>
      <button onClick={() => chooseDesign(null, note)} className="text-[15px] font-[800] text-ink-soft underline-offset-4 hover:underline">
        {one ? "Let the critic decide" : "Go with the critic's pick"}
      </button>
    </div>
  );
}
