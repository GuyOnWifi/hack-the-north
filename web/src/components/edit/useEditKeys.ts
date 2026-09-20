"use client";

import { useEffect, useEffectEvent } from "react";
import type { ScreenDir } from "@/lib/editor";

// Desktop shortcuts for edit mode. They're off while the panel's input has
// focus, so typing "delete the roof" never deletes anything.

export interface EditKeyHandlers {
  nudge: (dir: ScreenDir) => void;
  raise: (plates: number) => void;
  rotate: () => void;
  remove: () => void;
  duplicate: () => void;
  undo: () => void;
  redo: () => void;
  clear: () => void;
  selectAll: () => void;
}

const KEYS: Record<string, ScreenDir> = { ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down" };

function typing() {
  const el = document.activeElement as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
}

export function useEditKeys(enabled: boolean, handlers: EditKeyHandlers) {
  const run = useEffectEvent((ev: KeyboardEvent) => {
    const mod = ev.metaKey || ev.ctrlKey;
    if (ev.key === "Escape") return handlers.clear();
    if (typing()) return;
    if (mod && ev.key.toLowerCase() === "z") {
      ev.preventDefault();
      return ev.shiftKey ? handlers.redo() : handlers.undo();
    }
    if (mod && ev.key.toLowerCase() === "a") {
      ev.preventDefault();
      return handlers.selectAll();
    }
    if (mod) return;
    const dir = KEYS[ev.key];
    if (dir) {
      ev.preventDefault();
      return handlers.nudge(dir);
    }
    if (ev.key === "PageUp" || ev.key.toLowerCase() === "q" || ev.key.toLowerCase() === "w") return handlers.raise(1);
    if (ev.key === "PageDown" || ev.key.toLowerCase() === "e" || ev.key.toLowerCase() === "s") return handlers.raise(-1);
    if (ev.key.toLowerCase() === "r") return handlers.rotate();
    if (ev.key.toLowerCase() === "d") return handlers.duplicate();
    if (ev.key === "Delete" || ev.key === "Backspace") {
      ev.preventDefault();
      return handlers.remove();
    }
  });

  useEffect(() => {
    if (!enabled) return;
    const onKey = (ev: KeyboardEvent) => run(ev);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled]);
}
