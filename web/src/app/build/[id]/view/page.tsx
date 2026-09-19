"use client";

import { play, setMuted, useMuted } from "@/lib/sound";

import { useBuild } from "@/lib/useBuild";
import { BuildMissing } from "@/components/BuildMissing";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { ArrowUp, Check, FileDown, Home, Loader2, Redo2, Settings, Shapes, Shuffle, Sparkles, TriangleAlert, Undo2, Volume2, VolumeX, X } from "lucide-react";
import { BrickChip, IconTile } from "@/components/ui/controls";
import { BagGlyph, GhostBricks, StudSlider } from "@/components/ui/chrome";
import { BrickGlyph } from "@/components/ui/IsoBrick";
import { AgentTape, useFixtureTape, useTapePlayback } from "@/components/AgentTape";
import { editBuild, getLive, redo, tryAnother, undo, useLive } from "@/lib/live";
import type { Report, TapeEvent } from "@/lib/bricolage";

import { useLandscape } from "@/lib/useOrientation";
import type { PreparedModel } from "@/lib/ldraw";

const ModelView = dynamic(() => import("@/components/three/ModelView").then((m) => m.ModelView), { ssr: false });

export default function ViewPage() {
  return (
    <Suspense>
      <Viewer />
    </Suspense>
  );
}

// 3D viewer (IMG_1231 / 1232 / 1242 / 1245): grey studio, model turning on
// display, side tiles, bag badge, timeline slider that ghosts unbuilt parts,
// and the big yellow build button.
function Viewer() {
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const router = useRouter();
  const { build, live, pending } = useBuild(id);
  const landscape = useLandscape();
  const [model, setModel] = useState<PreparedModel | null>(null);
  const [failed, setFailed] = useState(false);
  const [value, setValue] = useState(0);
  const [scrubbing, setScrubbing] = useState(false);
  const [settings, setSettings] = useState(false);
  const [editing, setEditing] = useState(params.get("edit") === "1");
  const count = model?.stepCount ?? 0;

  // Replays the build step by step so a change reads as a drop-in. For live
  // edits it waits until the new version's model has loaded.
  const replayTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const replayPending = useRef(false);
  useEffect(() => () => clearInterval(replayTimer.current ?? undefined), []);
  const replay = (total: number) => {
    clearInterval(replayTimer.current ?? undefined);
    let v = 0;
    setValue(0);
    replayTimer.current = setInterval(() => {
      v++;
      setValue(Math.min(v, total));
      play("connect", { volume: 0.35 });
      if (v >= total) clearInterval(replayTimer.current ?? undefined);
    }, 260);
  };
  const bagSize = Math.max(3, Math.ceil(count / 5));
  const bags = count ? Math.ceil(count / bagSize) : 0;
  const stops = Array.from({ length: Math.max(0, bags - 1) }, (_, i) => (i + 1) * bagSize);
  const timeline = model !== null && value < count;

  if (!build) return <BuildMissing pending={pending} live={live} />;

  return (
    <main className="fixed inset-0 overflow-hidden select-none" style={{ background: "linear-gradient(180deg,#8dbbe7 0%,#acd0f0 42%,#c9e2f6 100%)" }}>
      <GhostBricks seed={419} cols={5} rows={3} scale={1.5} color="#123a8c" opacity={0.1} skip={0.25} />
      {failed ? (
        <div className="grid h-full place-items-center text-center text-white">
          <div>
            <p className="text-[19px] font-bold">We couldn&apos;t load this model.</p>
            <Link href={`/build/${id}`} className="mt-3 inline-block font-bold underline">
              Go back
            </Link>
          </div>
        </div>
      ) : (
        <ModelView
          url={build.model}
          mode={timeline ? "timeline" : "display"}
          step={value - 1}
          spin={scrubbing || timeline ? 0 : 0.15}
          shadow
          onLoaded={(m) => {
            setModel(m);
            if (replayPending.current) {
              replayPending.current = false;
              replay(m.stepCount);
            } else setValue(m.stepCount);
          }}
          onError={() => setFailed(true)}
        />
      )}
      {!model && !failed && (
        <div className="pointer-events-none absolute inset-0 grid place-items-center">
          <div className="h-10 w-10 animate-spin rounded-full border-[4px] border-white/40 border-t-white" />
        </div>
      )}

      {/* Left tiles */}
      <div className="absolute left-0 top-0 flex flex-col gap-4 p-5" style={{ paddingLeft: "calc(var(--safe-left) + 20px)", paddingTop: "calc(var(--safe-top) + 20px)" }}>
        <IconTile tone="white" label="Home" href={`/build/${id}`} size={60}>
          <Home size={30} strokeWidth={2.2} />
        </IconTile>
        <IconTile tone="white" label="Settings" size={60} onClick={() => setSettings(true)}>
          <Settings size={30} strokeWidth={2.2} />
        </IconTile>
        <IconTile tone="white" label="All pieces" size={60} href={`/build/${id}/parts`}>
          <Shapes size={30} strokeWidth={2.2} />
        </IconTile>
        <IconTile tone="white" label="Change it" size={60} onClick={() => setEditing(true)}>
          <Sparkles size={28} strokeWidth={2.2} />
        </IconTile>
      </div>

      {/* Bottom bar: bag / slider / build button */}
      {model && (
        <div className="absolute inset-x-0 bottom-0 flex items-end gap-5 px-5" style={{ paddingBottom: "calc(var(--safe-bottom) + 20px)", paddingLeft: "calc(var(--safe-left) + 20px)", paddingRight: "calc(var(--safe-right) + 20px)" }}>
          <div className="mb-[-6px] shrink-0">
            <BagGlyph label={timeline ? `${Math.floor(Math.max(0, value - 1) / bagSize) + 1} / ${bags}` : `1 - ${bags}`} size={62} />
          </div>
          <div className={`relative mb-[17px] flex-1 ${landscape ? "max-w-[640px]" : ""}`} onPointerDown={() => setScrubbing(true)} onPointerUp={() => setScrubbing(false)} onPointerCancel={() => setScrubbing(false)}>
            {timeline && (
              <div className="pointer-events-none absolute bottom-[50px] -translate-x-1/2" style={{ left: `calc(14px + (100% - 28px) * ${value / Math.max(1, count)})` }}>
                <BrickChip bg="#ffffff" studs={2} className="!h-8 !px-3">
                  Step {Math.max(1, value)}
                </BrickChip>
              </div>
            )}
            <StudSlider value={value} max={count} stops={stops} onChange={setValue} />
          </div>
          <Link
            href={`/build/${id}/steps${timeline ? `?step=${Math.max(0, value - 1)}` : ""}`}
            aria-label="Start building"
            className="chunky grid h-[80px] w-[132px] shrink-0 place-items-center rounded-[20px]"
            style={{ background: "#ffd502", ["--rim" as string]: "#ccaa02", ["--lift" as string]: "6px" } as React.CSSProperties}
          >
            <BrickGlyph size={58} />
          </Link>
        </div>
      )}

      {settings && <SettingsModal onClose={() => setSettings(false)} onPdf={() => router.push(`/build/${id}/print`)} />}
      {editing && (
        <EditPanel
          live={live}
          landscape={landscape}
          onClose={() => setEditing(false)}
          onChanged={() => {
            if (live) replayPending.current = true;
            else replay(count);
          }}
        />
      )}
    </main>
  );
}

/** Two big tiles over a dimmed scene (IMG_1246). */
function SettingsModal({ onClose, onPdf }: { onClose: () => void; onPdf: () => void }) {
  const sound = !useMuted();
  return (
    <div className="absolute inset-0 z-50 grid place-items-center bg-black/65" style={{ animation: "fade-in 160ms ease-out" }} onClick={onClose}>
      <div className="absolute right-5 top-5" style={{ marginTop: "var(--safe-top)", marginRight: "var(--safe-right)" }}>
        <IconTile tone="dark" label="Close" size={60} onClick={onClose}>
          <X size={34} strokeWidth={2.6} />
        </IconTile>
      </div>
      <div className="flex gap-5" onClick={(e) => e.stopPropagation()}>
        <BigTile label={sound ? "Sound on" : "Sound off"} onClick={() => setMuted(sound)}>
          {sound ? <Volume2 size={100} strokeWidth={2} /> : <VolumeX size={100} strokeWidth={2} />}
        </BigTile>
        <BigTile label="Download manual" onClick={onPdf}>
          <FileDown size={96} strokeWidth={2} />
        </BigTile>
      </div>
    </div>
  );
}

function BigTile({ children, label, onClick }: { children: React.ReactNode; label: string; onClick: () => void }) {
  return (
    <button
      aria-label={label}
      onClick={onClick}
      className="chunky grid h-[min(216px,40vw)] w-[min(216px,40vw)] place-items-center rounded-[44px] bg-[#f2f2f2] text-ink"
      style={{ ["--rim" as string]: "#cfcfcf", ["--lift" as string]: "10px" } as React.CSSProperties}
    >
      {children}
    </button>
  );
}

const LIVE_CHIPS = ["Make the chassis longer", "Make the cabin taller", "Make it wider", "Make it red"];
const SAMPLE_CHIPS = ["Make it lower", "Swap the wheels", "Add a spoiler", "Less red"];

type Turn = { text: string; events: TapeEvent[]; report: Report | null; error: string | null; result?: string };

/**
 * Natural-language edit. Live builds call Lane B's /edit (the new version's
 * model swaps in and replays); sample builds play the recorded tape.
 */
function EditPanel({ live, landscape, onClose, onChanged }: { live: boolean; landscape: boolean; onClose: () => void; onChanged: () => void }) {
  const session = useLive();
  const fixture = useFixtureTape();
  const [text, setText] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [sampleRun, setSampleRun] = useState<number | null>(null);
  const played = useTapePlayback(fixture, sampleRun, () => {
    setBusy(false);
    onChanged();
  });

  const submit = async (value: string, op?: () => Promise<void>) => {
    const ask = value.trim();
    if ((!ask && !op) || busy) return;
    setText("");
    setBusy(true);
    if (!live) {
      setTurns((t) => [...t, { text: ask, events: [], report: null, error: null }]);
      setSampleRun((r) => (r ?? 0) + 1);
      return;
    }
    setTurns((t) => [...t, { text: ask, events: [], report: null, error: null }]);
    try {
      onChanged();
      await (op ? op() : editBuild(ask));
      const p = getLive().payload;
      // Lane B records a tape for builds but not (yet) for edits: summarise the new version instead.
      const result = p?.version ? `Now on ${p.version} · ${p.build?.parts.length ?? 0} pieces · ${p.report?.ok ? "stands up" : "needs fixes"}` : undefined;
      setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? { ...turn, events: p?.tape ?? [], report: p?.report ?? null, result } : turn)));
    } catch (e) {
      setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? { ...turn, error: e instanceof Error ? e.message : "That change didn't work" } : turn)));
    } finally {
      setBusy(false);
    }
  };

  const chips = live ? LIVE_CHIPS : SAMPLE_CHIPS;
  const remaining = session.payload?.report?.stats.inventory_remaining;

  return (
    <aside
      className={`absolute z-40 flex flex-col bg-[#eef0f2]/95 backdrop-blur ${landscape ? "bottom-4 right-4 top-4 w-[400px] rounded-[28px]" : "inset-x-0 bottom-0 max-h-[64%] rounded-t-[28px]"}`}
      style={{ animation: landscape ? "fade-in 180ms ease-out" : "sheet-up 260ms cubic-bezier(.2,.9,.3,1)", boxShadow: "0 12px 40px rgba(0,0,0,0.25)", marginTop: landscape ? "var(--safe-top)" : 0, marginRight: landscape ? "var(--safe-right)" : 0 }}
    >
      <header className="flex items-center justify-between px-5 pb-2 pt-4">
        <div className="flex items-center gap-2">
          <span className="grid h-9 w-9 place-items-center rounded-full bg-ai">
            <Sparkles size={18} color="#fff" fill="#fff" />
          </span>
          <span className="text-[19px] font-[800] text-ink">Change it</span>
        </div>
        <div className="flex items-center gap-1">
          {live && (
            <>
              <button onClick={() => submit("Undo", undo)} disabled={busy} aria-label="Undo" className="grid h-10 w-10 place-items-center rounded-full bg-black/5 active:scale-95 disabled:opacity-40">
                <Undo2 size={20} strokeWidth={2.6} />
              </button>
              <button onClick={() => submit("Redo", redo)} disabled={busy} aria-label="Redo" className="grid h-10 w-10 place-items-center rounded-full bg-black/5 active:scale-95 disabled:opacity-40">
                <Redo2 size={20} strokeWidth={2.6} />
              </button>
              <button onClick={() => submit("Try another", tryAnother)} disabled={busy} aria-label="Try another" className="grid h-10 w-10 place-items-center rounded-full bg-black/5 active:scale-95 disabled:opacity-40">
                <Shuffle size={20} strokeWidth={2.6} />
              </button>
            </>
          )}
          <button onClick={onClose} aria-label="Close" className="grid h-10 w-10 place-items-center rounded-full bg-black/5 active:scale-95">
            <X size={22} strokeWidth={2.6} />
          </button>
        </div>
      </header>
      <div className="no-scrollbar flex-1 overflow-auto px-4 pb-3">
        {turns.length === 0 ? (
          <p className="px-1 pt-1 text-[15px] text-ink-soft">Tell me what you&apos;d change. I&apos;ll only rebuild that part and keep the rest.</p>
        ) : (
          turns.map((turn, i) => {
            const last = i === turns.length - 1;
            const events = live ? turn.events : last ? played : fixture;
            return (
              <div key={i} className="mb-4">
                <div className="mb-3 ml-auto w-fit max-w-[85%] rounded-[18px] rounded-br-[6px] bg-blue px-4 py-2.5 text-[16px] font-semibold text-white">{turn.text}</div>
                {(events.length > 0 || (last && busy)) && <AgentTape events={events} live={last && busy} compact />}
                {live && !events.length && turn.result && (
                  <div className="flex items-center gap-2 rounded-[14px] bg-white px-3 py-2.5 text-[14px] font-semibold text-ink shadow-[0_2px_0_rgba(0,0,0,0.06)]" style={{ animation: "tape-in 260ms ease-out" }}>
                    <Check size={18} strokeWidth={2.8} color="#1f7a3a" />
                    {turn.result}
                  </div>
                )}
                {turn.error && <p className="mt-2 rounded-[14px] bg-[#fde8ea] px-3 py-2 text-[14px] font-semibold text-[#9b1020]">{turn.error}</p>}
                {turn.report && <ReportNotes report={turn.report} />}
              </div>
            );
          })
        )}
        {live && remaining !== undefined && turns.length > 0 && !busy && (
          <div className="flex items-center justify-between rounded-[16px] bg-white px-4 py-3" style={{ animation: "tape-in 260ms ease-out" }}>
            <span className="text-[15px] font-bold text-ink">Bricks left in your pile</span>
            <span className="text-[22px] font-[900] text-ink">{remaining}</span>
          </div>
        )}
      </div>
      <div className="px-4 pb-[calc(var(--safe-bottom)+14px)]">
        <div className="no-scrollbar -mx-4 mb-3 flex gap-2 overflow-x-auto px-4 pt-1">
          {chips.map((c) => (
            <BrickChip key={c} onClick={() => submit(c)} disabled={busy} bg="#ffffff" className="!text-[14px]">
              {c}
            </BrickChip>
          ))}
        </div>
        <form
          className="flex h-[56px] items-center gap-2 rounded-[18px] bg-white pl-4 pr-2 shadow-[0_3px_0_#d5d5d5]"
          onSubmit={(e) => {
            e.preventDefault();
            submit(text);
          }}
        >
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Hmm, I don't like the chassis…" aria-label="Describe a change" className="min-w-0 flex-1 bg-transparent text-[16px] outline-none placeholder:text-[#9a9a9a]" />
          <button type="submit" aria-label="Send" disabled={!text.trim() || busy} className="grid h-11 w-11 place-items-center rounded-[14px] bg-ai text-white transition-opacity disabled:opacity-35">
            {busy ? <Loader2 size={22} className="animate-spin" /> : <ArrowUp size={24} strokeWidth={2.8} />}
          </button>
        </form>
      </div>
    </aside>
  );
}

/** Validator messages, rendered verbatim (they're written as UI copy). */
function ReportNotes({ report }: { report: Report }) {
  const notes = [...report.errors.map((e) => ({ ...e, kind: "error" as const })), ...report.warnings.map((w) => ({ ...w, kind: "warning" as const }))];
  if (!notes.length) return null;
  return (
    <ul className="mt-2 flex flex-col gap-1.5">
      {notes.map((n, i) => (
        <li key={i} className="flex items-start gap-2 rounded-[14px] px-3 py-2 text-[14px] font-semibold" style={{ background: n.kind === "error" ? "#fde8ea" : "#fff6dc", color: n.kind === "error" ? "#9b1020" : "#7a5600" }}>
          <TriangleAlert size={16} strokeWidth={2.6} className="mt-0.5 shrink-0" />
          {n.human}
        </li>
      ))}
    </ul>
  );
}
