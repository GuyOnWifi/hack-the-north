"use client";

import { useBuild } from "@/lib/useBuild";
import { BuildMissing } from "@/components/BuildMissing";
import { useParams } from "next/navigation";
import { useState } from "react";
import { ArrowLeft, Check } from "lucide-react";
import { IconTile } from "@/components/ui/controls";
import { PartsScroller } from "@/components/PartsScroller";

import { useLandscape } from "@/lib/useOrientation";

// All pieces for a build (IMG_1243 / IMG_1244), with a "Missing bricks?"
// mode that lets you tap the ones you can't find.
export default function PartsPage() {
  const { id } = useParams<{ id: string }>();
  const { build, live, pending } = useBuild(id);
  const landscape = useLandscape();
  const [marking, setMarking] = useState(false);
  const [missing, setMissing] = useState<Set<string>>(new Set());
  if (!build) return <BuildMissing pending={pending} live={live} />;

  const cells = build.parts.map((p) => {
    const key = `${p.part}@${p.colour}`;
    const gone = missing.has(key);
    return {
      key,
      part: p.part,
      colour: p.colour,
      count: p.count,
      ring: gone ? "#e3000b" : marking ? "rgba(255,255,255,0.9)" : undefined,
      badge: gone ? <span className="grid h-6 w-6 place-items-center rounded-full bg-[#e3000b] text-[14px] font-[900] text-white">!</span> : undefined,
      onClick: marking
        ? () =>
            setMissing((m) => {
              const next = new Set(m);
              if (next.has(key)) next.delete(key);
              else next.add(key);
              return next;
            })
        : undefined,
    };
  });

  return (
    <main className="fixed inset-0 flex flex-col bg-parts-bg">
      <header className="flex items-center justify-between gap-3 px-6 pb-4" style={{ paddingTop: "calc(var(--safe-top) + 20px)", paddingLeft: "calc(var(--safe-left) + 24px)", paddingRight: "calc(var(--safe-right) + 24px)" }}>
        <IconTile tone="glass-light" label="Back" href={`/build/${id}`} size={60}>
          <ArrowLeft size={32} strokeWidth={2.6} />
        </IconTile>
        {!landscape && <span className="text-[17px] font-[800] text-ink">{build.pieces} pieces</span>}
        <button
          onClick={() => setMarking((m) => !m)}
          className="chunky flex h-[60px] items-center gap-3 rounded-[16px] bg-white px-5 text-[18px] font-[700] text-ink"
          style={{ ["--rim" as string]: "#bdbdbd", ["--lift" as string]: "3px" } as React.CSSProperties}
        >
          {marking ? (
            <>
              <Check size={24} strokeWidth={3} /> Done{missing.size ? ` (${missing.size})` : ""}
            </>
          ) : (
            <>
              <MissingIcon /> Missing bricks?
            </>
          )}
        </button>
      </header>
      {marking && <p className="-mt-1 mb-2 text-center text-[15px] font-semibold text-ink-soft">Tap the pieces you can&apos;t find. We&apos;ll swap them out.</p>}
      <PartsScroller cells={cells} size={landscape ? 56 : 64} />
    </main>
  );
}

function MissingIcon() {
  return (
    <svg viewBox="0 0 32 28" width={30} height={26} aria-hidden>
      <path d="M3 8h26v17H3z" fill="none" stroke="#1a1a1a" strokeWidth="2.6" strokeLinejoin="round" />
      <rect x="6" y="3" width="7" height="5" rx="1" fill="none" stroke="#1a1a1a" strokeWidth="2.6" />
      <rect x="19" y="3" width="7" height="5" rx="1" fill="none" stroke="#1a1a1a" strokeWidth="2.6" />
      <text x="16" y="22.5" textAnchor="middle" fontSize="13" fontWeight="900" fill="#1a1a1a">
        ?
      </text>
    </svg>
  );
}
