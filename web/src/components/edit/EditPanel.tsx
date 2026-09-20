"use client";

import { useState } from "react";
import { ArrowUp, Check, Loader2, Redo2, Shuffle, Sparkles, Undo2, X } from "lucide-react";
import { AgentTape } from "@/components/AgentTape";
import { BrickChip } from "@/components/ui/controls";
import { BrickLoader } from "@/components/ui/Logo";
import { acceptCascade, clearSelection, redo, say, tryAnother, undo, useEditor, type EditTurn } from "@/lib/editor";

// The "Change it" sidebar: docked right in landscape, docked bottom in portrait
// (taste rule 12). Every turn shows ONLY that edit's own tape and the server's
// own sentence — no recorded build narration, no canned playback.

export const SIDEBAR_W = 400;
export const SHEET_H = "46%";

export function EditPanel({
  landscape,
  seeding,
  seedError,
  onClose,
}: {
  landscape: boolean;
  /** Seeding a server session from a bundled model's LDraw text. */
  seeding: boolean;
  seedError: string | null;
  onClose: () => void;
}) {
  const { turns, pending, table, notice, selection } = useEditor();
  const [text, setText] = useState("");
  const busy = pending || seeding;
  const ready = !seeding && !seedError;

  const submit = (value: string) => {
    const ask = value.trim();
    if (!ask || busy || !ready) return;
    setText("");
    void say(ask);
  };

  const chips = table?.suggestions ?? [];

  return (
    <aside
      className="absolute z-40 flex min-w-0 flex-col overflow-hidden"
      style={
        landscape
          ? {
              top: 0,
              right: 0,
              bottom: 0,
              width: SIDEBAR_W,
              background: "#e4f1fc",
              borderLeft: "3px solid #9cc5ec",
              paddingTop: "var(--safe-top)",
              paddingRight: "var(--safe-right)",
              animation: "sidebar-in 260ms cubic-bezier(.2,.9,.3,1)",
            }
          : {
              left: 0,
              right: 0,
              bottom: 0,
              height: SHEET_H,
              background: "#e4f1fc",
              borderTop: "3px solid #9cc5ec",
              animation: "sheet-up 260ms cubic-bezier(.2,.9,.3,1)",
            }
      }
    >
      <header className="flex items-center justify-between px-5 pb-2 pt-4">
        <div className="flex items-center gap-2">
          <span className="grid h-9 w-9 place-items-center rounded-full bg-ai">
            <Sparkles size={18} color="#fff" fill="#fff" />
          </span>
          <span className="whitespace-nowrap text-[19px] font-[800] text-ink">Change it</span>
          {/* data-sound off: clearing already plays its own soft tick. */}
          {selection.length > 0 && (
            <span data-sound="off">
              <BrickChip size="sm" studs={2} bg="#9840b0" ink="#ffffff" onClick={clearSelection} aria-label="Clear the selection">
                {selection.length} selected
              </BrickChip>
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <button onClick={() => void undo()} disabled={busy || !ready} aria-label="Undo" data-sound="off" className="grid h-10 w-10 place-items-center rounded-full bg-black/5 active:scale-95 disabled:opacity-40">
            <Undo2 size={20} strokeWidth={2.6} />
          </button>
          <button onClick={() => void redo()} disabled={busy || !ready} aria-label="Redo" data-sound="off" className="grid h-10 w-10 place-items-center rounded-full bg-black/5 active:scale-95 disabled:opacity-40">
            <Redo2 size={20} strokeWidth={2.6} />
          </button>
          <button onClick={() => void tryAnother()} disabled={busy || !ready} aria-label="Try another" data-sound="off" className="grid h-10 w-10 place-items-center rounded-full bg-black/5 active:scale-95 disabled:opacity-40">
            <Shuffle size={20} strokeWidth={2.6} />
          </button>
          <button onClick={onClose} aria-label="Close" className="grid h-10 w-10 place-items-center rounded-full bg-black/5 active:scale-95">
            <X size={22} strokeWidth={2.6} />
          </button>
        </div>
      </header>

      <div className="no-scrollbar min-w-0 flex-1 overflow-y-auto overflow-x-hidden px-4 pb-3">
        {seeding && (
          <div className="grid place-items-center py-8">
            <BrickLoader label="Getting it ready to change…" />
          </div>
        )}
        {seedError && <p className="mt-2 rounded-[14px] bg-[#fde8ea] px-3 py-2 text-[14px] font-semibold text-[#9b1020]">{seedError}</p>}
        {!seeding && !seedError && turns.length === 0 && (
          <p className="px-1 pt-1 text-[15px] text-ink-soft">
            Tap a piece to pick it, drag it to move it, or tell me what to change. I&apos;ll check it still holds together before anything moves.
          </p>
        )}
        {turns.map((turn, i) => (
          <Turn key={i} turn={turn} live={i === turns.length - 1 && pending} />
        ))}
      </div>

      <div className="px-4 pb-[calc(var(--safe-bottom)+14px)]">
        {notice && <p className="px-1 pb-2 text-[13px] font-semibold text-ink-soft">{notice}</p>}
        {chips.length > 0 && (
          <div data-sound="off" className="no-scrollbar -mx-4 mb-3 flex gap-2 overflow-x-auto px-4 pt-1">
            {chips.map((c) => (
              <BrickChip key={c} onClick={() => submit(c)} disabled={busy || !ready} bg="#ffffff" className="!text-[14px]">
                {c}
              </BrickChip>
            ))}
          </div>
        )}
        <form
          className="flex h-[56px] items-center gap-2 rounded-[18px] bg-white pl-4 pr-2 shadow-[0_3px_0_#d5d5d5]"
          onSubmit={(e) => {
            e.preventDefault();
            submit(text);
          }}
        >
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={selection.length ? `Change the ${selection.length} selected…` : "Make the lights blue…"}
            aria-label="Describe a change"
            disabled={!ready}
            className="min-w-0 flex-1 bg-transparent text-[16px] outline-none placeholder:text-[#9a9a9a]"
          />
          <button type="submit" aria-label="Send" data-sound="off" disabled={!text.trim() || busy || !ready} className="grid h-11 w-11 place-items-center rounded-[14px] bg-ai text-white transition-opacity disabled:opacity-35">
            {busy ? <Loader2 size={22} className="animate-spin" /> : <ArrowUp size={24} strokeWidth={2.8} />}
          </button>
        </form>
      </div>
    </aside>
  );
}

/** One action and what the server actually did about it. */
function Turn({ turn, live }: { turn: EditTurn; live: boolean }) {
  return (
    <div className="mb-4">
      <div className="mb-3 ml-auto w-fit max-w-[85%] rounded-[18px] rounded-br-[6px] bg-blue px-4 py-2.5 text-[16px] font-semibold text-white">{turn.text}</div>
      {(turn.events.length > 0 || live) && <AgentTape events={turn.events} live={live} compact />}
      {turn.result && turn.ok && (
        <div className="mt-2 flex items-start gap-2 rounded-[14px] bg-white px-3 py-2.5 text-[14px] font-semibold text-ink shadow-[0_2px_0_rgba(0,0,0,0.06)]" style={{ animation: "tape-in 260ms ease-out" }}>
          <Check size={18} strokeWidth={2.8} color="#1f7a3a" className="mt-0.5 shrink-0" />
          <span className="[overflow-wrap:anywhere]">{turn.result}</span>
        </div>
      )}
      {turn.result && turn.ok === false && <p className="mt-2 rounded-[14px] bg-[#fde8ea] px-3 py-2 text-[14px] font-semibold text-[#9b1020] [overflow-wrap:anywhere]">{turn.result}</p>}
      {turn.offer?.cascade && (
        <div data-sound="off" className="mt-2 pt-1">
          <BrickChip bg="#ffffff" className="!text-[14px]" onClick={() => void acceptCascade(turn)}>
            Remove those too
          </BrickChip>
        </div>
      )}
    </div>
  );
}
