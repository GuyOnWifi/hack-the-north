"use client";

import { useSyncExternalStore } from "react";
import { bricolage, type Choice, type Payload, type TapeEvent } from "./bricolage";
import { registerModelText } from "./ldraw";

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
  /** A speculative-draft model shown WHILE the real build streams in. */
  partialUrl: string | null;
  /** The concept art the designer is working from, as it arrives. */
  art: { role: string; image: string }[];
  /** Candidate designs waiting to be picked (empty once chosen). */
  choices: Choice[];
  tape: TapeEvent[];
  /** "live" = the API answered; "fixture" = offline fallback. */
  source: "live" | "fixture" | null;
  error: string | null;
}

const initial: LiveState = { status: "idle", prompt: null, payload: null, modelUrl: null, partialUrl: null, art: [], choices: [], tape: [], source: null, error: null };
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
  set({ status: "ready", payload, modelUrl, partialUrl: null, source, error: null, tape: payload.tape ?? state.tape });
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

/** Designs a new build, streaming the agent tape. Falls back to the fixtures
 *  offline. Corrections happen mid-run instead: the designer stops with the
 *  model on screen and takes a note (see chooseDesign). */
export async function designBuild(prompt: string) {
  return streamDesign(prompt, prompt);
}

async function streamDesign(displayPrompt: string, fullPrompt: string) {
  set({ status: "working", prompt: displayPrompt, tape: [], partialUrl: null, art: [], choices: [], error: null });
  try {
    const payload = await bricolage.stream(fullPrompt, (e) => {
      // a "geometry" event carries an LDraw blob (the speculative draft, or a
      // partial). Render it immediately instead of showing it as a tape row.
      const g = e as TapeEvent & { kind?: string; ldr?: string; image?: string; role?: string; choices?: Choice[] };
      if (g.kind === "geometry" && g.ldr) {
        const url = registerModelText(`partial-${state.tape.length}-${g.ldr.length}`, g.ldr);
        set({ partialUrl: url, choices: [] });
        return;
      }
      // the concept art, and the designs waiting to be picked, aren't tape rows
      if (g.kind === "art" && g.image) {
        set({ art: [...state.art.filter((a) => a.role !== g.role), { role: g.role ?? "concept", image: g.image }] });
        return;
      }
      if (g.kind === "choices") {
        set({ choices: g.choices ?? [] });
        return;
      }
      set({ tape: [...state.tape, e] });
    });
    await adopt(payload, "live");
  } catch (e) {
    // NO canned fallback. If the live builder fails, say so — never show a
    // hardcoded design. Everything on screen is real LLM output or nothing.
    set({ status: "error", error: e instanceof Error ? e.message : "The builder is offline" });
  }
}

/** Keep one of the candidate designs (null = let the critic decide). */
export async function chooseDesign(index: number | null, note = "") {
  const picked = index === null ? null : state.choices[index];
  set({ choices: [], partialUrl: picked ? registerModelText(`picked-${index}-${picked.ldr.length}`, picked.ldr) : state.partialUrl });
  await bricolage.choose(index, note);
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

/** Current snapshot, for event handlers that just awaited an action. */
export const getLive = () => state;
