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
  /** How many pieces of that draft were already on screen before this update,
   *  so the viewer drops in the new ones instead of rebuilding the lot. */
  partialLanded: number;
  /** The concept art the designer is working from, as it arrives. */
  art: { role: string; image: string }[];
  /** Candidate designs waiting to be picked (empty once chosen). */
  choices: Choice[];
  /** Which run is waiting on that answer. */
  ask: string;
  tape: TapeEvent[];
  /** "live" = the API answered; "fixture" = offline fallback. */
  source: "live" | "fixture" | null;
  error: string | null;
}

const initial: LiveState = { status: "idle", prompt: null, payload: null, modelUrl: null, partialUrl: null, partialLanded: 0, art: [], choices: [], ask: "", tape: [], source: null, error: null };
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
  const text = ldrText ?? (await bricolage.ldr(payload.version ?? undefined));
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

/** The LDraw text of the draft currently on screen, to diff the next one against. */
let lastDraft = "";
/** Stops the stream in flight. Without this a new design ran alongside the old
 *  one and both fed this store: a truck's screen showing a bird's build. */
let stopStream: (() => void) | null = null;
const countParts = (ldr: string) => (ldr ? ldr.split("\n").filter((l) => l.startsWith("1 ")).length : 0);

async function streamDesign(displayPrompt: string, fullPrompt: string) {
  stopStream?.();
  lastDraft = "";
  set({ status: "working", prompt: displayPrompt, tape: [], partialUrl: null, partialLanded: 0, art: [], choices: [], ask: "", error: null });
  try {
    const payload = await bricolage.stream(fullPrompt, (e) => {
      // a "geometry" event carries an LDraw blob (the speculative draft, or a
      // partial). Render it immediately instead of showing it as a tape row.
      const g = e as TapeEvent & { kind?: string; ldr?: string; draft?: boolean; image?: string; role?: string; choices?: Choice[]; ask?: string };
      if (g.kind === "geometry" && g.ldr) {
        const url = registerModelText(`partial-${state.tape.length}-${g.ldr.length}`, g.ldr);
        // a draft grows as the design is written: keep what is already standing
        const landed = g.draft && state.partialUrl ? countParts(lastDraft) : 0;
        lastDraft = g.draft ? g.ldr : "";
        set({ partialUrl: url, partialLanded: landed, choices: [] });
        return;
      }
      // the concept art, and the designs waiting to be picked, aren't tape rows
      if (g.kind === "art" && g.image) {
        set({ art: [...state.art.filter((a) => a.role !== g.role), { role: g.role ?? "concept", image: g.image }] });
        return;
      }
      if (g.kind === "choices") {
        set({ choices: g.choices ?? [], ask: g.ask ?? "" });
        return;
      }
      set({ tape: [...state.tape, e] });
    }, (stop) => {
      stopStream = stop;
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
  const ask = state.ask;
  set({ choices: [], ask: "", partialUrl: picked ? registerModelText(`picked-${index}-${picked.ldr.length}`, picked.ldr) : state.partialUrl });
  await bricolage.choose(index, note, ask);
}

/** Reopen something from the library as the current build. */
export const openSaved = (id: string) => run(null, () => bricolage.open(id));

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
