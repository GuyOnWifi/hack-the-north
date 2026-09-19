"use client";

import { useEffect } from "react";
import { play, preloadSounds, unlockSound } from "@/lib/sound";

/**
 * Unlocks audio on the first gesture and gives every pressable thing the tap
 * sound. Opt an element (and its children) out with data-sound="off", e.g.
 * controls that make their own sound like the timeline slider.
 */
export function SoundProvider() {
  useEffect(() => {
    preloadSounds();
    const onDown = (e: PointerEvent) => {
      unlockSound();
      const target = e.target as Element | null;
      const pressable = target?.closest("button, a[href], [role='button'], label[for]");
      if (!pressable || pressable.closest("[data-sound='off']")) return;
      if ((pressable as HTMLButtonElement).disabled) return;
      play("tap");
    };
    const onKey = (e: KeyboardEvent) => {
      unlockSound();
      if (e.key === "Enter" || e.key === " ") {
        const el = document.activeElement;
        if (el?.matches("button, a[href]") && !el.closest("[data-sound='off']")) play("tap");
      }
    };
    window.addEventListener("pointerdown", onDown, { capture: true, passive: true });
    window.addEventListener("keydown", onKey, { capture: true });
    return () => {
      window.removeEventListener("pointerdown", onDown, { capture: true });
      window.removeEventListener("keydown", onKey, { capture: true });
    };
  }, []);
  return null;
}
