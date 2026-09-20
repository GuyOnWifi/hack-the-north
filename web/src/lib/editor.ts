"use client";

import { useSyncExternalStore } from "react";
import { ApiError, bricolage, type EditOp, type EditResult, type Payload, type PartsTable, type TapeEvent } from "./bricolage";
import { adoptPayload, applyEdit, getLive } from "./live";
import type { PreparedModel } from "./ldraw";
import { play } from "./sound";

// The editor session for one open model (docs/EDITING.md G.5): what the part
// table says, what is selected, what the ghost shows, and the log of turns.
// Every op goes to the server, which gates it; nothing here decides whether an
// edit is legal, and nothing here moves a real part. One per tab, like live.ts.

/** One entry in the "Change it" log: a typed line, a chip, a button or a drag. */
export interface EditTurn {
  text: string;
  /** ONLY this edit's tape (payload.edit.tape) — never the build's narration. */
  events: TapeEvent[];
  /** payload.edit.human, verbatim. null while the turn is still running. */
  result: string | null;
  /** null = running. */
  ok: boolean | null;
  offer: { cascade?: boolean } | null;
  /** The ops this turn sent, so "Remove those too" can resend them. */
  ops: EditOp[];
  path: string | null;
}

export interface GhostPlacement {
  line: number;
  origin: [number, number, number];
  matrix: number[];
}

/** What ModelView draws as a translucent preview of a pending edit. */
export interface EditGhost {
  lines: number[];
  placements: GhostPlacement[];
  /** null = waiting on the dry run; true = the server would accept it. */
  valid: boolean | null;
}

export interface EditorState {
  table: PartsTable | null;
  /** A plain sentence for why picking/toolbar are unavailable, or null. */
  notice: string | null;
  /** Part ids line up with the loaded meshes (A.3), so tapping is on. */
  linked: boolean;
  selection: string[];
  candidates: string[];
  culprits: string[];
  ghost: EditGhost | null;
  /** A commit is in flight. */
  pending: boolean;
  turns: EditTurn[];
  lastColour: number | null;
}

/** A.3: never guess which mesh is which part. */
const A3 = "I can't line this model up with its piece list, so tapping is off. Typing a change still works.";
const NO_EDITOR = "This builder doesn't have the piece editor yet, so tapping and the buttons are off. Typing a change still works.";
const OFFLINE = "Changing a model needs the builder running, and I can't reach it right now.";

const initial: EditorState = { table: null, notice: null, linked: false, selection: [], candidates: [], culprits: [], ghost: null, pending: false, turns: [], lastColour: null };

let state = initial;
const listeners = new Set<() => void>();

function set(patch: Partial<EditorState>) {
  state = { ...state, ...patch };
  listeners.forEach((l) => l());
}

export function useEditor() {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => state,
    () => initial,
  );
}

export const getEditor = () => state;

// --- the loaded model, and the id <-> line map -------------------------------

let model: PreparedModel | null = null;
/** The version the attached meshes were built from, so A.3 compares like with like. */
let modelVersion: string | null = null;
let byId = new Map<string, number>();
/** The 3x3 of each part's current LDraw matrix, for optimistic ghosts. */
let basis: number[][] = [];

/** ModelView finished loading a version: re-check A.3 and cache the bases. */
export function attachModel(m: PreparedModel | null) {
  model = m;
  modelVersion = m ? (getLive().payload?.version ?? null) : null;
  basis = m ? m.parts.map((p) => rowMajor3(p.object.matrix.elements)) : [];
  relink();
}

/** three stores matrices column-major; the LDraw line is row-major. */
function rowMajor3(e: ArrayLike<number>) {
  return [e[0], e[4], e[8], e[1], e[5], e[9], e[2], e[6], e[10]];
}

function relink() {
  const t = state.table;
  if (!model || !t) {
    if (state.linked) set({ linked: false });
    return;
  }
  // The table and the meshes must describe the SAME version. Between an accepted
  // edit (which refetches the table) and the new model finishing its load they
  // don't — that is a swap in progress, not a mismatch. Picking pauses for those
  // few frames, but the A.3 sentence (which says this model can't be lined up at
  // all) must not flash: it would be a lie about a model that lines up fine.
  if (t.version && modelVersion && t.version !== modelVersion) {
    if (state.linked) set({ linked: false });
    return;
  }
  const ok = model.parts.length === t.count && t.parts.every((row, i) => model!.parts[i]?.part === row.part);
  set({ linked: ok, notice: ok ? (state.notice === A3 ? null : state.notice) : A3 });
}

export const lineOf = (id: string) => byId.get(id) ?? -1;
export const idOf = (line: number) => state.table?.parts[line]?.id ?? null;
export const rowOf = (id: string) => {
  const line = byId.get(id);
  return line === undefined ? null : (state.table?.parts[line] ?? null);
};
/** Selected ids as mesh lines, for ModelView. */
export const linesOf = (ids: string[]) => ids.map((id) => byId.get(id)).filter((n): n is number => n !== undefined);

// --- session -----------------------------------------------------------------

const version = () => getLive().payload?.version ?? null;

/** Pulls the part table for the current version. Safe to call repeatedly. */
export async function refreshTable() {
  try {
    const table = await bricolage.parts();
    byId = new Map(table.parts.map((p) => [p.id, p.line]));
    const alive = new Set(table.parts.map((p) => p.id));
    set({
      table,
      notice: null,
      selection: state.selection.filter((id) => alive.has(id)),
      candidates: state.candidates.filter((id) => alive.has(id)),
      culprits: state.culprits.filter((id) => alive.has(id)),
    });
    relink();
    return table;
  } catch (e) {
    const missing = e instanceof ApiError && (e.status === 404 || e.status === 501);
    set({ table: null, linked: false, notice: missing ? NO_EDITOR : OFFLINE });
    byId = new Map();
    return null;
  }
}

/** Catch up with a server that moved on without us: model first, then table. */
async function resync() {
  try {
    await adoptPayload(await bricolage.state());
    await refreshTable();
  } catch {
    // Offline or no editor: leave the store alone and let the caller report.
  }
}

/** Clears everything when the panel closes or a different build is opened. */
export function resetEditor() {
  state = initial;
  byId = new Map();
  basis = [];
  model = null;
  listeners.forEach((l) => l());
}

// --- selection ----------------------------------------------------------------

export function pick(line: number | null, mods: { additive: boolean; body: boolean }) {
  const table = state.table;
  if (!table || !state.linked) return;
  if (line === null) {
    if (state.selection.length || state.candidates.length) {
      play("tick", { volume: 0.3 });
      set({ selection: [], candidates: [] });
    }
    return;
  }
  const row = table.parts[line];
  if (!row) return;
  let selection: string[];
  if (mods.body) selection = table.parts.filter((p) => p.body === row.body).map((p) => p.id);
  else if (mods.additive) selection = state.selection.includes(row.id) ? state.selection.filter((id) => id !== row.id) : [...state.selection, row.id];
  else selection = [row.id];
  play("tick", { volume: 0.35 });
  set({ selection, candidates: [] });
}

export function selectAll() {
  const table = state.table;
  if (!table || !state.linked) return;
  play("tick", { volume: 0.35 });
  set({ selection: table.parts.map((p) => p.id), candidates: [] });
}

export function clearSelection() {
  if (state.ghost) set({ ghost: null });
  if (!state.selection.length && !state.candidates.length) return;
  play("tick", { volume: 0.3 });
  set({ selection: [], candidates: [] });
}

// --- screen-relative directions ------------------------------------------------

export type ScreenDir = "left" | "right" | "up" | "down";

const STEPS: [number, number, number][] = [
  [1, 0, 0],
  [-1, 0, 0],
  [0, 0, 1],
  [0, 0, -1],
];

/** Where an LDraw X/Z step points on screen: [rightwards, away from the viewer]. */
function onScreen(d: [number, number, number], phi: number): [number, number] {
  const c = Math.cos(phi);
  const s = Math.sin(phi);
  if (d[0] === 1) return [c, -s];
  if (d[0] === -1) return [-c, s];
  if (d[2] === 1) return [s, c];
  return [-s, -c];
}

/**
 * The world axis a screen direction means, given `phi` = the camera's azimuth
 * minus the turntable angle. Arrows are screen-relative; the step they send is
 * always a whole stud along a model axis.
 */
export function screenAxis(dir: ScreenDir, phi: number): [number, number, number] {
  const want: [number, number] = dir === "right" ? [1, 0] : dir === "left" ? [-1, 0] : dir === "up" ? [0, 1] : [0, -1];
  let best = STEPS[0];
  let score = -Infinity;
  for (const d of STEPS) {
    const [x, y] = onScreen(d, phi);
    const dot = x * want[0] + y * want[1];
    if (dot > score) {
      score = dot;
      best = d;
    }
  }
  return [...best] as [number, number, number];
}

// --- ghosts --------------------------------------------------------------------

/** Where the selected parts would sit if the server took `d` as asked. */
function optimistic(ids: string[], d: [number, number, number]): EditGhost | null {
  const lines = linesOf(ids);
  if (!lines.length) return null;
  const placements: GhostPlacement[] = [];
  for (const line of lines) {
    const row = state.table?.parts[line];
    const m = basis[line];
    if (!row || !m) continue;
    placements.push({ line, origin: [row.origin[0] + 20 * d[0], row.origin[1] - 8 * d[1], row.origin[2] + 20 * d[2]], matrix: m });
  }
  return placements.length ? { lines, placements, valid: null } : null;
}

function ghostFrom(lines: number[], edit: EditResult): EditGhost {
  const placements = edit.landed.filter((l) => l.line >= 0 && l.matrix?.length === 9).map((l) => ({ line: l.line, origin: l.origin, matrix: l.matrix }));
  return { lines, placements, valid: edit.accepted };
}

// --- the dry run (drags) ---------------------------------------------------------

let dryRunning = false;
let dryQueued: { ops: EditOp[]; lines: number[]; token: number } | null = null;
let dryToken = 0;

/** At most one dry run in flight; the newest request wins, stale replies are dropped. */
function dryRun(ops: EditOp[], lines: number[]) {
  const base = version();
  if (!base) return;
  const token = ++dryToken;
  if (dryRunning) {
    dryQueued = { ops, lines, token };
    return;
  }
  dryRunning = true;
  bricolage
    .editDirect(ops, { dryRun: true, base })
    .then((p) => {
      if (token !== dryToken || !p.edit) return;
      set({ ghost: ghostFrom(lines, p.edit) });
    })
    .catch(() => {})
    .finally(() => {
      dryRunning = false;
      const next = dryQueued;
      dryQueued = null;
      if (next && next.token === dryToken) dryRun(next.ops, next.lines);
    });
}

// --- committing -------------------------------------------------------------------

let queued: { label: string; ops: EditOp[] } | null = null;

function startTurn(text: string, ops: EditOp[]): number {
  const turn: EditTurn = { text, events: [], result: null, ok: null, offer: null, ops, path: null };
  set({ turns: [...state.turns, turn] });
  return state.turns.length - 1;
}

function finishTurn(index: number, patch: Partial<EditTurn>) {
  set({ turns: state.turns.map((t, i) => (i === index ? { ...t, ...patch } : t)) });
}

/** What the panel's caller needs to know after a turn (e.g. to replay a rebuild). */
export type TurnOutcome = { accepted: boolean; path: string | null; human: string };

let onOutcome: ((o: TurnOutcome) => void) | null = null;
export const onTurnDone = (fn: ((o: TurnOutcome) => void) | null) => {
  onOutcome = fn;
};

async function send(label: string, ops: EditOp[], call: (base: string) => Promise<Payload>, optimisticGhost?: EditGhost | null) {
  const base = version();
  if (!base) {
    const i = startTurn(label, ops);
    finishTurn(i, { ok: false, result: OFFLINE });
    return;
  }
  if (state.pending) {
    queued = { label, ops }; // depth 1: the newest queued action replaces the last
    return;
  }
  const index = startTurn(label, ops);
  set({ pending: true, ghost: optimisticGhost ?? state.ghost });
  try {
    let payload = await call(base);
    let edit = await applyEdit(payload);
    // STALE means the server moved on without us (another tab, a reload, a
    // stream). Telling the user to "try again" is a dead end: our base never
    // changes, so every retry is stale too. Catch up and replay it once.
    if (edit && !edit.accepted && edit.code === "STALE") {
      await resync();
      const fresh = version();
      if (fresh && fresh !== base) {
        payload = await call(fresh);
        edit = await applyEdit(payload);
      }
    }
    if (!edit) {
      // A server without the editor: adopt what it did send, say what we know.
      await adoptPayload(payload);
      finishTurn(index, { ok: true, result: payload.version ? `Now on ${payload.version}` : null });
      set({ ghost: null });
    } else if (edit.accepted) {
      finishTurn(index, { events: edit.tape ?? [], result: edit.human, ok: true, offer: null, path: edit.path });
      set({
        ghost: null,
        candidates: [],
        culprits: [],
        selection: edit.added.length ? edit.added : state.selection.filter((id) => !edit.removed.includes(id)),
      });
      play("connect", { volume: 0.45 });
      await refreshTable();
    } else {
      finishTurn(index, { events: edit.tape ?? [], result: edit.human, ok: false, offer: edit.offer, path: edit.path });
      // The ghost springs back where ModelView can show it, then clears.
      set({ ghost: null, candidates: edit.candidates ?? [], culprits: edit.culprits ?? [] });
      play("tick", { volume: 0.4 });
    }
    onOutcome?.({ accepted: !!edit?.accepted, path: edit?.path ?? null, human: edit?.human ?? "" });
  } catch (e) {
    const missing = e instanceof ApiError && (e.status === 404 || e.status === 501);
    finishTurn(index, { ok: false, result: e instanceof ApiError ? (missing ? NO_EDITOR : e.message) : OFFLINE });
    set({ ghost: null });
  } finally {
    set({ pending: false });
    const next = queued;
    queued = null;
    if (next) void commit(next.label, next.ops);
  }
}

/** The one path for every button, key and drag. */
export function commit(label: string, ops: EditOp[], optimisticGhost?: EditGhost | null) {
  return send(label, ops, (base) => bricolage.editDirect(ops, { base }), optimisticGhost);
}

/** The "Change it" box: the server routes it (instant / fast model / rebuild). */
export function say(text: string) {
  const trimmed = text.trim();
  if (!trimmed) return Promise.resolve();
  return send(trimmed, [], (base) => bricolage.edit(trimmed, state.selection, base));
}

// --- the toolbar's ops --------------------------------------------------------------

const has = () => state.selection.length > 0 && !!state.table;

const plural = (n: number) => `${n} piece${n === 1 ? "" : "s"}`;

export function nudge(dir: ScreenDir, phi: number) {
  if (!has()) return;
  const d = screenAxis(dir, phi);
  const ids = [...state.selection];
  return commit(`Move ${dir === "up" ? "away" : dir === "down" ? "closer" : dir}`, [{ op: "move", ids, d, settle: true }], optimistic(ids, d));
}

export function raise(plates: number) {
  if (!has()) return;
  const d: [number, number, number] = [0, plates, 0];
  const ids = [...state.selection];
  return commit(plates > 0 ? "Up one plate" : "Down one plate", [{ op: "move", ids, d, settle: true }], optimistic(ids, d));
}

export function rotate() {
  if (!has()) return;
  return commit("Turn a quarter", [{ op: "rotate", ids: [...state.selection], quarters: 1, settle: true }]);
}

export function recolour(colour: number) {
  if (!has()) return;
  set({ lastColour: colour });
  const name = state.table?.palette.find((c) => c.code === colour)?.name ?? `colour ${colour}`;
  return commit(`Paint ${name}`, [{ op: "recolour", ids: [...state.selection], colour }]);
}

export function duplicate() {
  if (!has()) return;
  return commit(`Copy ${plural(state.selection.length)}`, [{ op: "duplicate", ids: [...state.selection], settle: true }]);
}

export function remove(cascade = false) {
  if (!has()) return;
  return commit(cascade ? "Remove those too" : `Delete ${plural(state.selection.length)}`, [{ op: "delete", ids: [...state.selection], cascade }]);
}

/** Re-sends the last turn's ops with cascade on (the WOULD_FALL offer). */
export function acceptCascade(turn: EditTurn) {
  const ops = turn.ops.map((o) => (o.op === "delete" ? { ...o, cascade: true } : o));
  if (!ops.length) return;
  return commit("Remove those too", ops);
}

export function addPart(part: string, colour: number) {
  if (!state.table) return;
  set({ lastColour: colour });
  const name = state.table.kit.find((k) => k.part === part)?.name ?? `part ${part}`;
  return commit(`Add a ${name}`, [{ op: "add", part, colour, on: state.selection[0] ?? null, quarters: 0, settle: true }]);
}

// --- dragging -----------------------------------------------------------------------

let dragIds: string[] = [];
let dragLines: number[] = [];
let dragLast: [number, number] = [0, 0];

export function dragStart() {
  if (!has()) return;
  dragIds = [...state.selection];
  dragLines = linesOf(dragIds);
  dragLast = [0, 0];
  set({ ghost: optimistic(dragIds, [0, 0, 0]) });
}

export function dragMove(d: [number, number]) {
  if (!dragIds.length) return;
  dragLast = d;
  const step: [number, number, number] = [d[0], 0, d[1]];
  const ghost = optimistic(dragIds, step);
  if (ghost) set({ ghost: { ...ghost, valid: state.ghost?.valid ?? null } });
  dryRun([{ op: "move", ids: dragIds, d: step, settle: true }], dragLines);
}

export function dragEnd() {
  const ids = dragIds;
  const [dx, dz] = dragLast;
  dragIds = [];
  dragLines = [];
  if (!ids.length) return;
  if (!dx && !dz) {
    set({ ghost: null });
    return;
  }
  dryToken++; // any dry run still in flight is stale now
  const d: [number, number, number] = [dx, 0, dz];
  return commit("Drag", [{ op: "move", ids, d, settle: true }], optimistic(ids, d));
}

export function dragCancel() {
  dragIds = [];
  dragLines = [];
  dryToken++;
  set({ ghost: null });
}

// --- undo / redo ---------------------------------------------------------------------

export function undo() {
  return send("Undo", [], () => bricolage.undo());
}

export function redo() {
  return send("Redo", [], () => bricolage.redo());
}

/** Only means anything on a build the designer made; loaded models say so. */
export function tryAnother() {
  return send("Try another", [], () => bricolage.tryAnother());
}
