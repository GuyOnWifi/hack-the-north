"use client";

import { useSyncExternalStore } from "react";
import { bricolage, fixturePayload, type Payload, type TapeEvent } from "./bricolage";
import { registerModelText } from "./ldraw";
import type { InventoryItem } from "./types";

// The live design session against Lane B: the current version, its LDraw text,
// and the agent tape as it streams. One per tab, shared by every build screen.

export type LiveStatus = "idle" | "working" | "ready" | "error";

export interface LiveState {
  status: LiveStatus;
  /** What the user asked for, for the "Designing…" copy. */
  prompt: string | null;
  payload: Payload | null;
  /** Model URL for ModelView (changes whenever the version does). */
  modelUrl: string | null;
  tape: TapeEvent[];
  /** "live" = the API answered; "fixture" = offline fallback. */
  source: "live" | "fixture" | null;
  error: string | null;
}

const initial: LiveState = { status: "idle", prompt: null, payload: null, modelUrl: null, tape: [], source: null, error: null };
let state = initial;
const listeners = new Set<() => void>();

function set(patch: Partial<LiveState>) {
  state = { ...state, ...patch };
  listeners.forEach((l) => l());
}

export function useLive() {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => state,
    () => initial,
  );
}

async function adopt(payload: Payload, source: "live" | "fixture", ldrText?: string) {
  if (!payload.version) throw new Error("The builder has no model yet");
  const text = ldrText ?? (await bricolage.ldr());
  const modelUrl = registerModelText(`${source}-${payload.version}`, text);
  set({ status: "ready", payload, modelUrl, source, error: null, tape: payload.tape ?? state.tape });
}

async function run(prompt: string | null, op: () => Promise<Payload>) {
  set({ status: "working", prompt: prompt ?? state.prompt, error: null });
  try {
    await adopt(await op(), "live");
  } catch (e) {
    set({ status: state.payload ? "ready" : "error", error: e instanceof Error ? e.message : String(e) });
    throw e;
  }
}

/** Designs a new build, streaming the agent tape. Falls back to the fixtures offline. */
export async function designBuild(prompt: string) {
  set({ status: "working", prompt, tape: [], error: null });
  try {
    const payload = await bricolage.stream(prompt, (e) => set({ tape: [...state.tape, e] }));
    await adopt(payload, "live");
  } catch {
    try {
      const { payload, ldr } = await fixturePayload();
      await replayTape(payload.tape ?? []);
      await adopt(payload, "fixture", ldr);
    } catch (e) {
      set({ status: "error", error: e instanceof Error ? e.message : "The builder is offline" });
    }
  }
}

/** Offline: play the fixture tape with its recorded timing (compressed). */
async function replayTape(events: TapeEvent[]) {
  set({ tape: [] });
  let last = 0;
  for (const e of events) {
    await new Promise((r) => setTimeout(r, Math.min(900, Math.max(180, (e.t - last) * 0.4))));
    last = e.t;
    set({ tape: [...state.tape, e] });
  }
}

export const editBuild = (text: string) => run(null, () => bricolage.edit(text));
export const tryAnother = () => run(null, bricolage.tryAnother);
export const undo = () => run(null, bricolage.undo);
export const redo = () => run(null, bricolage.redo);

/** Picks up an existing server session (e.g. after a reload). */
export async function resumeLive() {
  if (state.status !== "idle") return;
  try {
    const payload = await bricolage.state();
    if (payload.version) await adopt(payload, "live");
  } catch {
    // no server: stay idle
  }
}

/** Hands the reviewed inventory to the builder so designs fit the real pile. */
export async function sendInventory(items: InventoryItem[]) {
  try {
    await bricolage.setInventory(items.map((i) => ({ part: i.part, color: i.colour, count: i.count })));
    return true;
  } catch {
    return false;
  }
}

/** Current snapshot, for event handlers that just awaited an action. */
export const getLive = () => state;
