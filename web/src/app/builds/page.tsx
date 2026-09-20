"use client";

import Link from "next/link";
import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, ArrowUp, BookOpen, Filter, Sparkles, Star, X } from "lucide-react";
import { TabBar } from "@/components/ui/chrome";
import { BrickChip, ChunkyButton, IconTile, YellowBucket } from "@/components/ui/controls";
import { IsoBrick } from "@/components/ui/IsoBrick";
import { ModelSnapshot } from "@/components/three/Snapshots";
import { BUILDS, THEMES } from "@/lib/data";
import { bricolage, type SavedModel } from "@/lib/bricolage";
import { openSaved } from "@/lib/live";
import { LIVE_ID, useBuild } from "@/lib/useBuild";

// Build suggestions (IMG_1228): yellow bucket with the hero model and
// floating studs, then a light-blue list of build tiles.
export default function BuildsPage() {
  return (
    <Suspense>
      <Builds />
    </Suspense>
  );
}

function Builds() {
  const params = useSearchParams();
  const theme = params.get("theme");
  const router = useRouter();
  const current = useBuild(LIVE_ID);
  const [prompt, setPrompt] = useState("");
  const design = (text: string) => text.trim() && router.push(`/create?prompt=${encodeURIComponent(text.trim())}`);
  const [filter, setFilter] = useState<string | null>(theme && theme !== "Anything" ? theme : null);

  const list = useMemo(() => BUILDS.filter((b) => !filter || b.theme === filter), [filter]);
  const library = useLibrary();
  const saved = library.models;
  const kept = saved.filter((m) => m.kept).length;

  const hero = current.build ?? list[0] ?? BUILDS[0];

  return (
    <main className="relative mx-auto min-h-dvh max-w-[520px] pb-36" style={{ background: "linear-gradient(180deg,#9cc0df 0%,#cfe0ef 45%,#ffffff 100%)" }}>
      <YellowBucket className="pb-7" tone="yellow">
        <div className="relative px-[18px] pt-4">
          <IconTile tone="yellow" label="Back" href="/home" size={60}>
            <ArrowLeft size={30} strokeWidth={2.8} />
          </IconTile>
          <FloatingStuds />
          <div className="relative -mt-6 flex justify-center">
            <ModelSnapshot url={hero.model} alt={hero.name} width={560} height={420} className="h-[210px] w-[300px] drop-shadow-[0_18px_18px_rgba(120,70,0,0.35)]" />
          </div>
          <div className="mt-2 flex justify-center">
            <span className="rounded-[12px] px-4 py-1 text-[28px] font-[900] italic tracking-[-0.02em] text-white" style={{ background: "linear-gradient(180deg,#1f8fe8,#0b5fc0)", boxShadow: "0 4px 0 #083f86, inset 0 0 0 3px #ffd502", textShadow: "0 2px 0 #083f86" }}>
              {filter ?? "BUILD IDEAS"}
            </span>
          </div>
        </div>
      </YellowBucket>

      <section className="mt-9 px-[18px]">
        <h2 className="text-center text-[22px] font-[800] tracking-[-0.01em] text-ink">What should we build?</h2>
        <form
          className="chunky mt-4 flex h-[60px] items-center gap-3 rounded-[18px] bg-white pl-5 pr-2"
          style={{ ["--rim" as string]: "#c9d6e3", ["--lift" as string]: "5px" } as React.CSSProperties}
          onSubmit={(e) => {
            e.preventDefault();
            design(prompt);
          }}
        >
          <Sparkles size={22} color="#e3000b" fill="#e3000b" />
          <input value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="A little red truck" aria-label="Describe a build" className="h-full min-w-0 flex-1 bg-transparent text-[18px] text-ink outline-none placeholder:text-[#949494]" />
          <button type="submit" aria-label="Design it" disabled={!prompt.trim()} className="grid h-11 w-11 place-items-center rounded-[14px] bg-ai text-white transition-opacity disabled:opacity-35">
            <ArrowUp size={24} strokeWidth={2.8} />
          </button>
        </form>
        <div className="no-scrollbar -mx-[18px] mt-3 flex gap-2 overflow-x-auto px-[18px] pt-1">
          {IDEAS.map((idea) => (
            <BrickChip key={idea} onClick={() => design(idea)}>
              {idea}
            </BrickChip>
          ))}
        </div>
      </section>

      {current.build && (
        <Link href={`/build/${LIVE_ID}`} className="chunky mx-[18px] mt-7 flex items-center gap-4 rounded-[22px] bg-white p-3 pr-5" style={{ ["--rim" as string]: "#c9d6e3", ["--lift" as string]: "5px" } as React.CSSProperties}>
          <ModelSnapshot url={current.build.model} alt={current.build.name} width={320} height={240} className="h-[84px] w-[112px]" />
          <div className="min-w-0 flex-1">
            <div className="text-[13px] font-[800] uppercase tracking-wide text-ai">Your design</div>
            <div className="truncate text-[19px] font-[800] text-ink">{current.build.name}</div>
            <div className="text-[15px] text-ink-soft">{current.build.pieces} pieces</div>
          </div>
          <BookOpen size={22} color="#005ad2" strokeWidth={2.4} />
        </Link>
      )}

      {saved.length > 0 && (
        <section className="mt-9">
          <h2 className="text-center text-[30px] font-[800] tracking-[-0.02em] text-ink">Your builds</h2>
          <p className="mx-auto mt-1 max-w-[330px] text-center text-[15px] text-ink-soft">
            {kept ? `${kept} kept of ${saved.length}. Clearing the rest leaves those alone.` : "Everything you have designed, newest first."}
          </p>
          <div className="mt-6 grid grid-cols-2 gap-x-4 gap-y-7 px-[18px]">
            {saved.map((m) => (
              <SavedCard
                key={m.id}
                model={m}
                onOpen={() => openSaved(m.id).then(() => router.push(`/build/${LIVE_ID}`))}
                onKeep={() => library.keep(m.id, !m.kept)}
                onRemove={() => library.remove(m.id)}
              />
            ))}
          </div>
          {kept > 0 && kept < saved.length && (
            <div className="mt-6 flex justify-center">
              <ChunkyButton variant="white" className="!w-auto !px-6 !text-[16px]" onClick={library.clearRest}>
                Clear the other {saved.length - kept}
              </ChunkyButton>
            </div>
          )}
        </section>
      )}

      <div className="relative mt-8">
        <button
          onClick={() => setFilter((f) => (f ? null : THEMES[0].id))}
          className="absolute left-0 top-0 flex h-[62px] w-[70px] items-center justify-center rounded-r-full bg-white shadow-[0_6px_16px_rgba(30,60,100,0.18)] active:scale-95"
          aria-label="Filter"
        >
          <Filter size={24} fill={filter ? "#2458ca" : "#1a1a1a"} color={filter ? "#2458ca" : "#1a1a1a"} />
        </button>
        <h2 className="pt-12 text-center text-[30px] font-[800] tracking-[-0.02em] text-ink">Featured</h2>
        <p className="mx-auto mt-1 max-w-[320px] text-center text-[15px] text-ink-soft">Or describe anything above and the designer will build it.</p>
      </div>

      {list.length === 0 ? (
        <div className="mx-6 mt-10 flex flex-col items-center gap-3 text-center">
          <IsoBrick w={2} d={2} h={3} color="#9aa7b5" size={70} />
          <p className="text-[17px] font-bold text-ink">No {filter} builds yet</p>
          <button onClick={() => setFilter(null)} className="text-[15px] font-bold text-blue">
            Show everything
          </button>
        </div>
      ) : (
        <div className="mt-8 grid grid-cols-2 gap-x-4 gap-y-8 px-[18px]">
          {list.map((build) => (
            <Link key={build.id} href={`/build/${build.id}`} className="group flex flex-col items-center text-center active:scale-[0.97] transition-transform">
              <ModelSnapshot url={build.model} alt={build.name} width={480} height={360} className="h-[140px] w-full" />
              <span className="mt-2 grid h-9 w-9 place-items-center rounded-full bg-blue">
                <BookOpen size={18} color="#fff" strokeWidth={2.4} />
              </span>
              <span className="mt-2 text-[17px] font-[800] leading-tight text-ink">{build.name}</span>
              <span className="text-[16px] text-ink">{build.pieces} pieces</span>
            </Link>
          ))}
        </div>
      )}
      <TabBar />
    </main>
  );
}

// Lane B's golden prompts: each reaches a valid, sequenced build.
const IDEAS = ["A rover", "A small truck", "A house", "A garage", "A jet", "A tower", "A heart"];

function FloatingStuds() {
  const studs = [
    { x: "36%", y: 18, s: 30, r: 0 },
    { x: "47%", y: 2, s: 24, r: 0 },
    { x: "60%", y: 26, s: 28, r: 0 },
    { x: "30%", y: 58, s: 22, r: 0 },
    { x: "62%", y: 62, s: 30, r: 0 },
    { x: "54%", y: 44, s: 20, r: 0 },
  ];
  return (
    <div className="pointer-events-none absolute inset-x-0 top-6 h-24" aria-hidden>
      {studs.map((s, i) => (
        <div key={i} className="absolute" style={{ left: s.x, top: s.y, animation: `float-y ${4 + (i % 3)}s ease-in-out ${-i * 0.6}s infinite` }}>
          <IsoBrick w={1} d={1} h={1} round color="#e08a1e" size={s.s} />
        </div>
      ))}
    </div>
  );
}

/** Models designed on this machine. They live on disk, so they survive a
 *  reload, a restart and every new design after them. */
function useLibrary() {
  const [models, setModels] = useState<SavedModel[]>([]);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let alive = true;
    bricolage
      .library()
      .then((r) => alive && setModels(r.models))
      .catch(() => {}); // no backend: just the samples below
    return () => {
      alive = false;
    };
  }, [reload]);
  const again = () => setReload((n) => n + 1);
  return {
    models,
    remove: (id: string) => bricolage.removeModel(id).then(again).catch(() => {}),
    keep: (id: string, on: boolean) => bricolage.keepModel(id, on).then(again).catch(() => {}),
    clearRest: () => bricolage.clearUnkept().then(again).catch(() => {}),
  };
}

/** One saved model: its own render, not a live canvas (taste rule 15). Keep
 *  marks it to survive a clear; remove sends it to runs/removed/, so a mis-tap
 *  costs nothing, which is why it goes without a confirmation step. */
function SavedCard({ model, onOpen, onKeep, onRemove }: { model: SavedModel; onOpen: () => void; onKeep: () => void; onRemove: () => void }) {
  return (
    <div className="group relative flex flex-col items-center text-center">
      <button onClick={onOpen} className="w-full transition-transform active:scale-[0.97]">
        <div className="h-[140px] w-full overflow-hidden rounded-[18px] bg-[#cfe3f5]" style={model.kept ? { outline: "3px solid #e3000b", outlineOffset: 2 } : undefined}>
          {model.thumb ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={bricolage.thumb(model.id)} alt={model.name} className="h-full w-full object-cover" />
          ) : (
            <div className="grid h-full w-full place-items-center">
              <IsoBrick w={2} d={2} h={3} color="#9aa7b5" size={56} />
            </div>
          )}
        </div>
        <span className="mt-2 block text-[17px] font-[800] leading-tight text-ink">{model.name}</span>
        <span className="text-[16px] text-ink">{model.parts ?? "?"} pieces</span>
      </button>
      <div className="absolute right-2 top-2 flex gap-1.5">
        <button
          onClick={onKeep}
          aria-label={model.kept ? `Stop keeping ${model.name}` : `Keep ${model.name}`}
          title={model.kept ? "Kept" : "Keep this one"}
          className="grid h-8 w-8 place-items-center rounded-[8px] shadow-[0_2px_0_rgba(0,0,0,0.15)] active:scale-95"
          style={{ background: model.kept ? "#e3000b" : "rgba(255,255,255,0.92)" }}
        >
          <Star size={16} strokeWidth={2.6} color={model.kept ? "#ffffff" : "#1a1a1a"} fill={model.kept ? "#ffffff" : "none"} />
        </button>
        <button
          onClick={onRemove}
          aria-label={`Remove ${model.name}`}
          title="Remove from your builds"
          className="grid h-8 w-8 place-items-center rounded-[8px] bg-white/92 shadow-[0_2px_0_rgba(0,0,0,0.15)] active:scale-95"
        >
          <X size={16} strokeWidth={2.8} color="#1a1a1a" />
        </button>
      </div>
    </div>
  );
}
