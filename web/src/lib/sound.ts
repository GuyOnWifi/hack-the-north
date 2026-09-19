"use client";

import { useSyncExternalStore } from "react";

// UI sound effects (public/sounds, from the team's "Sound Effects" folder).
// Web Audio so rapid, overlapping clicks are sample-accurate and cheap; every
// play gets a little pitch/volume variation so repeats never sound robotic.

export type Sound = "tap" | "connect" | "tick" | "drag";

const FILES: Record<Sound, string[]> = {
  tap: ["/sounds/tap-1.mp3", "/sounds/tap-2.mp3"],
  connect: ["/sounds/connect-1.mp3", "/sounds/connect-2.mp3"],
  tick: ["/sounds/tick-1.mp3"],
  drag: ["/sounds/drag-1.mp3"],
};

const LEVEL: Record<Sound, number> = { tap: 0.55, connect: 0.9, tick: 0.5, drag: 0.4 };

/** Minimum gap between two plays of the same sound, so bursts never clip. */
const MIN_GAP_MS: Record<Sound, number> = { tap: 40, connect: 28, tick: 22, drag: 45 };

const MUTE_KEY = "brickbook-muted";

let ctx: AudioContext | null = null;
let master: GainNode | null = null;
const buffers = new Map<Sound, AudioBuffer[]>();
const lastPlayed = new Map<Sound, number>();
let loading: Promise<void> | null = null;

let muted = readMuted();
const listeners = new Set<() => void>();

function readMuted() {
  try {
    return typeof window !== "undefined" && window.localStorage.getItem(MUTE_KEY) === "1";
  } catch {
    return false;
  }
}

function context() {
  if (ctx || typeof window === "undefined") return ctx;
  const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Ctor) return null;
  ctx = new Ctor();
  master = ctx.createGain();
  master.connect(ctx.destination);
  return ctx;
}

/** Fetch and decode every sound once (works while the context is still suspended). */
export function preloadSounds() {
  const c = context();
  if (!c || loading) return loading;
  loading = Promise.all(
    (Object.keys(FILES) as Sound[]).map(async (kind) => {
      const decoded = await Promise.all(
        FILES[kind].map((url) =>
          fetch(url)
            .then((r) => r.arrayBuffer())
            .then((data) => c.decodeAudioData(data))
            .catch(() => null),
        ),
      );
      buffers.set(kind, decoded.filter((b): b is AudioBuffer => b !== null));
    }),
  ).then(() => undefined);
  return loading;
}

/** Browsers only allow audio after a user gesture; call from one. */
export function unlockSound() {
  const c = context();
  if (c && c.state === "suspended") c.resume().catch(() => {});
  preloadSounds();
}

const rand = (a: number, b: number) => a + Math.random() * (b - a);

/** Plays one sound, `delayMs` from now. */
export function play(kind: Sound, { volume = 1, delayMs = 0 }: { volume?: number; delayMs?: number } = {}) {
  if (muted) return;
  const c = context();
  const list = buffers.get(kind);
  if (!c || !master || c.state !== "running" || !list?.length) return;
  const at = performance.now() + delayMs;
  if (at - (lastPlayed.get(kind) ?? -Infinity) < MIN_GAP_MS[kind]) return;
  lastPlayed.set(kind, at);

  const source = c.createBufferSource();
  source.buffer = list[Math.floor(Math.random() * list.length)];
  source.playbackRate.value = rand(0.94, 1.07);
  const gain = c.createGain();
  gain.gain.value = LEVEL[kind] * volume * rand(0.85, 1);
  source.connect(gain).connect(master);
  source.start(c.currentTime + delayMs / 1000);
}

/**
 * A run of `count` plays at random spacings: the way the tick and drag sounds
 * are meant to be used ("multiple in succession at random spacings").
 */
export function rattle(kind: Sound, count: number, { minGap = 45, maxGap = 120, volume = 1 }: { minGap?: number; maxGap?: number; volume?: number } = {}) {
  let t = 0;
  for (let i = 0; i < count; i++) {
    play(kind, { delayMs: t, volume: volume * rand(0.8, 1) });
    t += rand(minGap, maxGap);
  }
}

export function setMuted(value: boolean) {
  muted = value;
  try {
    window.localStorage.setItem(MUTE_KEY, value ? "1" : "0");
  } catch {}
  listeners.forEach((l) => l());
}

export function useMuted() {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => muted,
    () => false,
  );
}
