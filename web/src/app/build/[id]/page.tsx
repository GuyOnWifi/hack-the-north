"use client";

import { useBuild } from "@/lib/useBuild";
import { useAssembly } from "@/lib/useAssembly";
import { BuildMissing } from "@/components/BuildMissing";
import dynamic from "next/dynamic";
import { useParams } from "next/navigation";
import { useState } from "react";
import { ArrowLeft, Layers, ListOrdered, Play, Plus, Sparkles, Users } from "lucide-react";
import { ChunkyButton, IconTile } from "@/components/ui/controls";
import { FloatingBricks } from "@/components/ui/chrome";
import { BrickGlyph } from "@/components/ui/IsoBrick";
import { coverage } from "@/lib/data";
import { useSession } from "@/lib/store";

const ModelView = dynamic(() => import("@/components/three/ModelView").then((m) => m.ModelView), { ssr: false });

// Build detail (IMG_1229): dark teal display card with the model turning on
// display, the two chunky actions, then the title and stat row.
export default function BuildDetail() {
  const { id } = useParams<{ id: string }>();
  const { build, live, pending, report } = useBuild(id);
  const session = useSession();
  const [failed, setFailed] = useState(false);
  // brick-by-brick assembly playback: reveal one step at a time, then settle
  const assembly = useAssembly(build?.id, 360);
  const { steps, step: astep, assembling } = assembly;
  const broken = live && report != null && !report.ok;

  if (!build) return <BuildMissing pending={pending} live={live} />;
  const cov = coverage(build, session.inventory);

  return (
    <main className="mx-auto min-h-dvh max-w-[520px] pb-10" style={{ background: "linear-gradient(180deg,#94afb9 0%,#c6d7de 100%)" }}>
      <section className="relative overflow-hidden rounded-b-[44px] px-[18px] pb-7" style={{ background: "linear-gradient(180deg,#0b1c22 0%,#1d3f4c 35%,#376275 70%,#4a7e96 100%)", boxShadow: "0 7px 0 #3b6679" }}>
        <FloatingBricks tone="grey" opacity={0.35} />
        <div className="relative z-10 flex justify-between" style={{ paddingTop: "calc(var(--safe-top) + 16px)" }}>
          <IconTile tone="dark" label="Back" href="/builds" size={60}>
            <ArrowLeft size={30} strokeWidth={2.8} />
          </IconTile>
          <IconTile tone="white" label="Save build" size={60}>
            <Plus size={34} strokeWidth={2.6} />
          </IconTile>
        </div>
        <div className="relative z-10 -mt-4 h-[330px]">
          {failed ? (
            <div className="grid h-full place-items-center text-center text-white/80">Couldn&apos;t load this model.</div>
          ) : (
            <>
              {steps === null && <div className="absolute inset-10 skeleton rounded-3xl opacity-40" />}
              <ModelView
                url={build.model}
                mode={assembling ? "timeline" : "display"}
                step={astep}
                spin={assembling ? 0 : 0.15}
                shadow
                onLoaded={(m) => assembly.start(m.stepCount)}
                onError={() => setFailed(true)}
              />
              {/* live assembly HUD */}
              {steps !== null && (
                <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-center justify-between px-2">
                  {assembling ? (
                    <span className="rounded-full bg-black/45 px-3 py-1 text-[13px] font-semibold text-white backdrop-blur">
                      assembling · brick {Math.min(astep, steps)}/{steps}
                    </span>
                  ) : (
                    <button
                      onClick={assembly.replay}
                      className="pointer-events-auto flex items-center gap-1 rounded-full bg-white/85 px-3 py-1 text-[13px] font-bold text-ink active:scale-95"
                    >
                      <Play size={14} fill="#1a1a1a" /> replay
                    </button>
                  )}
                  {broken && (
                    <span className="rounded-full bg-[#e02436] px-3 py-1 text-[13px] font-bold text-white shadow">
                      ⚠ won&apos;t stand
                    </span>
                  )}
                </div>
              )}
              {broken && <div className="pointer-events-none absolute inset-2 rounded-3xl ring-2 ring-[#e02436]/70" style={{ animation: "pulse 1.4s ease-in-out infinite" }} />}
            </>
          )}
        </div>
        <div className="relative z-10 mt-2 flex flex-col gap-4">
          <ChunkyButton variant="yellow" href={`/build/${build.id}/steps`} icon={<BrickGlyph size={36} />}>
            Start Building
          </ChunkyButton>
          <ChunkyButton variant="red" href={`/build/${build.id}/view?edit=1`} icon={<Sparkles size={26} fill="#fff" />}>
            Change it
          </ChunkyButton>
        </div>
      </section>

      <div className="mt-8 px-6 text-center">
        <div className="text-[17px] font-[600] text-ink">{build.theme}</div>
        <h1 className="mt-1 text-[32px] font-[800] leading-tight tracking-[-0.02em] text-ink">{build.name}</h1>
        <p className="mx-auto mt-2 max-w-[340px] text-[16px] text-ink-soft">{build.tagline}</p>
        {report && !report.ok && (
          <ul className="mx-auto mt-4 flex max-w-[380px] flex-col gap-1.5 text-left">
            {report.errors.map((e, i) => (
              <li key={i} className="rounded-[14px] bg-[#fde8ea] px-3 py-2 text-[14px] font-semibold text-[#9b1020]">
                {e.human}
              </li>
            ))}
          </ul>
        )}
        <div className="mt-6 grid grid-cols-3 gap-2">
          <Stat icon={<Layers size={26} strokeWidth={2} />} label="Pieces" value={String(build.pieces)} />
          <Stat icon={<ListOrdered size={26} strokeWidth={2} />} label="Steps" value={steps === null ? "…" : String(steps)} />
          {live ? (
            <Stat icon={<Users size={26} strokeWidth={2} />} label="Left over" value={report ? String(report.stats.inventory_remaining) : "-"} />
          ) : (
            <Stat icon={<Users size={26} strokeWidth={2} />} label="Your bricks" value={session.inventory.length ? `${Math.round((cov.used / cov.total) * 100)}%` : "-"} />
          )}
        </div>
        <ChunkyButton variant="white" href={`/build/${build.id}/parts`} className="mt-8 !text-[17px]" icon={<Layers size={22} />}>
          See all pieces
        </ChunkyButton>
      </div>
    </main>
  );
}

function Stat({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex flex-col items-center gap-1 text-ink">
      {icon}
      <span className="text-[17px]">{label}</span>
      <span className="text-[17px] font-[800]">{value}</span>
    </div>
  );
}
