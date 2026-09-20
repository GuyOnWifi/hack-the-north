"use client";

import { BrickLoader } from "@/components/ui/Logo";

import { play, setMuted, useMuted } from "@/lib/sound";

import { LIVE_ID, useBuild } from "@/lib/useBuild";
import { BuildMissing } from "@/components/BuildMissing";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import {
  FileDown,
  Home,
  Settings,
  Shapes,
  Sparkles,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import { BrickChip, IconTile } from "@/components/ui/controls";
import { BagGlyph, GhostBricks, StudSlider } from "@/components/ui/chrome";
import { BrickGlyph } from "@/components/ui/IsoBrick";
import { EditPanel, SHEET_H, SIDEBAR_W } from "@/components/edit/EditPanel";
import { EditToolbar } from "@/components/edit/EditToolbar";
import { ColourTray } from "@/components/edit/ColourTray";
import { PartTray } from "@/components/edit/PartTray";
import { useEditKeys } from "@/components/edit/useEditKeys";
import { loadLdrSession, useLive } from "@/lib/live";
import {
  addPart,
  attachModel,
  clearSelection,
  dragCancel,
  dragEnd,
  dragMove,
  dragStart,
  duplicate,
  linesOf,
  nudge,
  onTurnDone,
  pick,
  raise,
  recolour,
  refreshTable,
  remove,
  resetEditor,
  rotate,
  selectAll,
  undo as editorUndo,
  redo as editorRedo,
  useEditor,
  type ScreenDir,
} from "@/lib/editor";

import { useLandscape } from "@/lib/useOrientation";
import type { PreparedModel } from "@/lib/ldraw";
import type { ModelViewHandle } from "@/components/three/ModelView";

const ModelView = dynamic(
  () => import("@/components/three/ModelView").then((m) => m.ModelView),
  { ssr: false },
);

/** Shown verbatim when the builder can't be reached (docs/EDITING.md G.1). */
const NO_BUILDER =
  "Changing a model needs the builder running, and I can't reach it right now.";

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
  const source = useLive().source;
  const physics = useLive().payload?.physics ?? null;
  const landscape = useLandscape();
  const editor = useEditor();
  const [model, setModel] = useState<PreparedModel | null>(null);
  const [failed, setFailed] = useState(false);
  const [value, setValue] = useState(0);
  const [scrubbing, setScrubbing] = useState(false);
  const [settings, setSettings] = useState(false);
  const [editing, setEditing] = useState(params.get("edit") === "1");
  const [tray, setTray] = useState<"colour" | "part" | null>(null);
  const [seeding, setSeeding] = useState(false);
  const [seedError, setSeedError] = useState<string | null>(null);
  const view = useRef<ModelViewHandle | null>(null);
  const count = model?.stepCount ?? 0;

  // Opening "Change it" on a bundled or lab model seeds a real server session
  // from its own LDraw text, so from here on it behaves exactly like a design
  // the builder made. Guarded by a ref: strict mode runs effects twice.
  const seeded = useRef(false);
  useEffect(() => {
    if (!editing || seeded.current || !build) return;
    seeded.current = true;
    if (source === "fixture") return; // offline fixtures can't be edited; said below
    if (live) {
      void refreshTable();
      return;
    }
    const file = build.model;
    const name = build.name;
    void (async () => {
      setSeeding(true);
      setSeedError(null);
      try {
        const res = await fetch(file);
        if (!res.ok) throw new Error(`No ${file}`);
        await loadLdrSession({ name, ldr: await res.text(), source: id });
        await refreshTable();
        router.replace(`/build/${LIVE_ID}/view?edit=1`);
      } catch {
        setSeedError(NO_BUILDER);
        seeded.current = false;
      } finally {
        setSeeding(false);
      }
    })();
  }, [editing, build, live, source, id, router]);

  useEffect(() => () => resetEditor(), []);

  // The toolbar's arrows are screen-relative: the editor turns the direction
  // the user sees into a whole-stud step along one of the model's own axes.
  const angle = () => view.current?.viewAngle() ?? 0;
  const keys = {
    nudge: (dir: ScreenDir) => void nudge(dir, angle()),
    raise: (plates: number) => void raise(plates),
    rotate: () => void rotate(),
    duplicate: () => void duplicate(),
    remove: () => void remove(false),
    undo: () => void editorUndo(),
    redo: () => void editorRedo(),
    clear: clearSelection,
    selectAll,
  };
  useEditKeys(editing && !seeding, keys);

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
  // A structural change ("make the ears bigger") rebuilds the whole model, so
  // it reads best as a drop-in; a part-level edit swaps in place.
  useEffect(() => {
    onTurnDone((o) => {
      if (o.accepted && o.path === "brief") replayPending.current = true;
    });
    return () => onTurnDone(null);
  }, []);

  const bagSize = Math.max(3, Math.ceil(count / 5));
  const bags = count ? Math.ceil(count / bagSize) : 0;
  const stops = Array.from(
    { length: Math.max(0, bags - 1) },
    (_, i) => (i + 1) * bagSize,
  );
  // Editing shows the whole model, still, with every step placed (G.0).
  const timeline = model !== null && value < count && !editing;
  const showStability =
    !!physics?.com &&
    (physics.base?.length ?? 0) >= 3 &&
    (!physics.stable || editor.ghost?.valid === false);

  if (!build) return <BuildMissing pending={pending} live={live} />;

  return (
    <main
      className="fixed inset-0 overflow-hidden select-none"
      style={{ background: "#e4f1fc" }}
    >
      {/* The stage gives up its own space to the "Change it" sidebar (right in
          landscape, bottom in portrait) instead of the panel floating over it. */}
      <div
        className="absolute left-0 top-0 overflow-hidden transition-[right,bottom] duration-300 ease-out"
        style={{
          right: editing && landscape ? SIDEBAR_W : 0,
          bottom: editing && !landscape ? SHEET_H : 0,
          background:
            "linear-gradient(180deg,#8dbbe7 0%,#acd0f0 42%,#c9e2f6 100%)",
        }}
      >
        <GhostBricks
          seed={419}
          cols={5}
          rows={3}
          scale={1.5}
          color="#123a8c"
          opacity={0.1}
          skip={0.25}
        />
        {failed ? (
          <div className="grid h-full place-items-center text-center text-white">
            <div>
              <p className="text-[19px] font-bold">
                We couldn&apos;t load this model.
              </p>
              <Link
                href={`/build/${id}`}
                className="mt-3 inline-block font-bold underline"
              >
                Go back
              </Link>
            </div>
          </div>
        ) : (
          <ModelView
            ref={view}
            url={build.model}
            mode={timeline ? "timeline" : "display"}
            step={value - 1}
            spin={editing || scrubbing || timeline ? 0 : 0.15}
            shadow
            preserveView={editing}
            edit={
              editing
                ? {
                    enabled: true,
                    selected: linesOf(editor.selection),
                    candidates: linesOf(editor.candidates),
                    culprits: linesOf(editor.culprits),
                    ghost: editor.ghost,
                    onPick: pick,
                    onDrag: (phase, d) => {
                      if (phase === "start") dragStart();
                      else if (phase === "move") dragMove(d);
                      else if (phase === "end") void dragEnd();
                      else dragCancel();
                    },
                    stability: showStability
                      ? {
                          com: physics!.com!,
                          base: physics!.base,
                          ground: physics!.ground ?? 0,
                          stable: physics!.stable,
                        }
                      : null,
                  }
                : undefined
            }
            onLoaded={(m) => {
              setModel(m);
              attachModel(m);
              if (replayPending.current) {
                replayPending.current = false;
                if (editing) setValue(m.stepCount);
                else replay(m.stepCount);
              } else setValue(m.stepCount);
            }}
            onError={() => setFailed(true)}
          />
        )}
        {!model && !failed && (
          <div className="pointer-events-none absolute inset-0 grid place-items-center">
            <BrickLoader label="Unboxing your build…" />
          </div>
        )}

        {/* Left tiles */}
        <div
          className="absolute left-0 top-0 flex flex-col gap-4 p-5"
          style={{
            paddingLeft: "calc(var(--safe-left) + 20px)",
            paddingTop: "calc(var(--safe-top) + 20px)",
          }}
        >
          <IconTile tone="white" label="Home" href={`/build/${id}`} size={60}>
            <Home size={30} strokeWidth={2.2} />
          </IconTile>
          <IconTile
            tone="white"
            label="Settings"
            size={60}
            onClick={() => setSettings(true)}
          >
            <Settings size={30} strokeWidth={2.2} />
          </IconTile>
          <IconTile
            tone="white"
            label="All pieces"
            size={60}
            href={`/build/${id}/parts`}
          >
            <Shapes size={30} strokeWidth={2.2} />
          </IconTile>
          <IconTile
            tone="white"
            label="Change it"
            size={60}
            onClick={() => setEditing(true)}
          >
            <Sparkles size={28} strokeWidth={2.2} />
          </IconTile>
        </div>

        {/* The editor's toolbar sits along the top of the stage, right of the
            left tile column: no new layout, no floating card. */}
        {editing && (
          <div
            className="pointer-events-none absolute right-0 top-0 flex flex-col items-start gap-2"
            style={{
              left: "calc(var(--safe-left) + 96px)",
              paddingTop: "calc(var(--safe-top) + 20px)",
              paddingRight: "20px",
            }}
          >
            <div className="pointer-events-auto max-w-full">
              <EditToolbar
                active={editor.selection.length > 0}
                pending={editor.pending || seeding}
                portrait={!landscape}
                colours={tray === "colour"}
                parts={tray === "part"}
                onNudge={keys.nudge}
                onRaise={keys.raise}
                onRotate={keys.rotate}
                onDuplicate={keys.duplicate}
                onDelete={keys.remove}
                onColours={() => setTray((t) => (t === "colour" ? null : "colour"))}
                onParts={() => setTray((t) => (t === "part" ? null : "part"))}
              />
            </div>
            {tray === "colour" && editor.table && (
              <div className="pointer-events-auto max-w-full">
                <ColourTray
                  palette={editor.table.palette}
                  disabled={editor.pending}
                  onPick={(code) => void recolour(code)}
                />
              </div>
            )}
            {tray === "part" && editor.table && (
              <div className="pointer-events-auto max-w-full">
                <PartTray
                  kit={editor.table.kit}
                  colour={editor.lastColour ?? editor.table.palette[0]?.code ?? 4}
                  disabled={editor.pending}
                  onAdd={(part) =>
                    void addPart(
                      part,
                      editor.lastColour ?? editor.table?.palette[0]?.code ?? 4,
                    )
                  }
                />
              </div>
            )}
          </div>
        )}

        {/* Bottom bar: bag / slider / build button */}
        {model && (
          <div
            className="absolute inset-x-0 bottom-0 flex items-end gap-5 px-5"
            style={{
              paddingBottom: "calc(var(--safe-bottom) + 20px)",
              paddingLeft: "calc(var(--safe-left) + 20px)",
              paddingRight: "calc(var(--safe-right) + 20px)",
            }}
          >
            <div className="mb-[-6px] shrink-0">
              <BagGlyph
                label={
                  timeline
                    ? `${Math.floor(Math.max(0, value - 1) / bagSize) + 1} / ${bags}`
                    : `1 - ${bags}`
                }
                size={62}
              />
            </div>
            <div
              className={`relative mb-[17px] flex-1 ${landscape ? "max-w-[640px]" : ""}`}
              onPointerDown={() => setScrubbing(true)}
              onPointerUp={() => setScrubbing(false)}
              onPointerCancel={() => setScrubbing(false)}
            >
              {timeline && (
                <div
                  className="pointer-events-none absolute bottom-[50px] -translate-x-1/2"
                  style={{
                    left: `calc(14px + (100% - 28px) * ${value / Math.max(1, count)})`,
                  }}
                >
                  <BrickChip bg="#ffffff" studs={2} className="!h-8 !px-3">
                    Step {Math.max(1, value)}
                  </BrickChip>
                </div>
              )}
              <StudSlider
                value={value}
                max={count}
                stops={stops}
                onChange={setValue}
              />
            </div>
            <Link
              href={`/build/${id}/steps${timeline ? `?step=${Math.max(0, value - 1)}` : ""}`}
              aria-label="Start building"
              className="chunky grid h-[80px] w-[132px] shrink-0 place-items-center rounded-[20px]"
              style={
                {
                  background: "#ffd502",
                  ["--rim" as string]: "#ccaa02",
                  ["--lift" as string]: "6px",
                } as React.CSSProperties
              }
            >
              <BrickGlyph size={58} />
            </Link>
          </div>
        )}
      </div>

      {settings && (
        <SettingsModal
          onClose={() => setSettings(false)}
          onPdf={() => router.push(`/build/${id}/print`)}
        />
      )}
      {editing && (
        <EditPanel
          landscape={landscape}
          seeding={seeding}
          seedError={source === "fixture" ? NO_BUILDER : seedError}
          onClose={() => {
            setEditing(false);
            setTray(null);
            clearSelection();
          }}
        />
      )}
    </main>
  );
}

/** Two big tiles over a dimmed scene (IMG_1246). */
function SettingsModal({
  onClose,
  onPdf,
}: {
  onClose: () => void;
  onPdf: () => void;
}) {
  const sound = !useMuted();
  return (
    <div
      className="absolute inset-0 z-50 grid place-items-center bg-black/65"
      style={{ animation: "fade-in 160ms ease-out" }}
      onClick={onClose}
    >
      <div
        className="absolute right-5 top-5"
        style={{
          marginTop: "var(--safe-top)",
          marginRight: "var(--safe-right)",
        }}
      >
        <IconTile tone="dark" label="Close" size={60} onClick={onClose}>
          <X size={34} strokeWidth={2.6} />
        </IconTile>
      </div>
      <div className="flex gap-5" onClick={(e) => e.stopPropagation()}>
        <BigTile
          label={sound ? "Sound on" : "Sound off"}
          onClick={() => setMuted(sound)}
        >
          {sound ? (
            <Volume2 size={100} strokeWidth={2} />
          ) : (
            <VolumeX size={100} strokeWidth={2} />
          )}
        </BigTile>
        <BigTile label="Download manual" onClick={onPdf}>
          <FileDown size={96} strokeWidth={2} />
        </BigTile>
      </div>
    </div>
  );
}

function BigTile({
  children,
  label,
  onClick,
}: {
  children: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      aria-label={label}
      onClick={onClick}
      className="chunky grid h-[min(216px,40vw)] w-[min(216px,40vw)] place-items-center rounded-[44px] bg-[#f2f2f2] text-ink"
      style={
        {
          ["--rim" as string]: "#cfcfcf",
          ["--lift" as string]: "10px",
        } as React.CSSProperties
      }
    >
      {children}
    </button>
  );
}
