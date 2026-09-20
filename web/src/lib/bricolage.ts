// Client for Lane B's API (bricolage/server.py), typed to the contracts in
// HANDOFF.md / fixtures/. Requests go to /bricolage/*, which next.config.ts
// rewrites to BRICOLAGE_URL. When the API is unreachable the frozen fixtures
// in public/bricolage-fixtures stand in, so the demo survives wifi dying.

export interface BricolagePart {
  id: string;
  part: string;
  color: number;
  pos: [number, number, number];
  rot: number;
  sub: string;
}

export interface BricolageBuild {
  id: string;
  version: number;
  name: string;
  parts: BricolagePart[];
}

export interface ReportIssue {
  code: string;
  sub: string | null;
  /** Written as UI copy: render verbatim. */
  human: string;
}

export interface Report {
  ok: boolean;
  errors: ReportIssue[];
  warnings: ReportIssue[];
  stats: { parts: number; studs_used: number; subs: number };
}

export interface BuildStep {
  n: number;
  sub: string;
  layer: number;
  parts: string[];
  /** "part:color" -> count */
  elements: Record<string, number>;
}

export interface Steps {
  build_id: string;
  n_steps: number;
  steps: BuildStep[];
}

export type TapeActor = "router" | "planner" | "designer" | "builder" | "inspector" | "critic" | "repair" | "scribe";
export type TapeStatus = "ok" | "fail" | "warn" | "running";

/** Contract 4: one agent-tape event. */
export interface TapeEvent {
  t: number;
  actor: TapeActor;
  kind: string;
  text: string;
  status: TapeStatus;
  ms: number;
  tokens: number;
}

// --- Part-level editing (docs/EDITING.md sections A-E) ----------------------

/** One edit op, exactly as /edit_direct takes it. Every field is an integer. */
export interface EditOp {
  op: "move" | "rotate" | "recolour" | "delete" | "duplicate" | "add";
  ids?: string[];
  /** [studs X, plates UP, studs Z] — the server converts to LDraw units. */
  d?: [number, number, number];
  quarters?: number;
  colour?: number;
  cascade?: boolean;
  settle?: boolean;
  part?: string;
  on?: string | null;
  body?: string;
  all?: true;
}

/** Where a touched part actually ended up (read-only floats, for the ghost). */
export interface Landed {
  id: string;
  /** Line in the new text; its current line on a dry run; -1 if it doesn't exist yet. */
  line: number;
  requested: [number, number, number];
  d: [number, number, number];
  settled: boolean;
  origin: [number, number, number];
  matrix: number[];
}

export type EditPath = "direct" | "preparse" | "fast" | "brief" | "nav" | "load";

/** The `edit` key every mutation response carries. `human` is UI copy: verbatim. */
export interface EditResult {
  accepted: boolean;
  dry_run?: boolean;
  path: EditPath;
  code: string | null;
  human: string;
  ops: EditOp[];
  changed: string[];
  added: string[];
  removed: string[];
  landed: Landed[];
  candidates: string[];
  culprits: string[];
  offer: { cascade?: boolean } | null;
  tape: TapeEvent[];
}

export interface PartRow {
  id: string;
  line: number;
  part: string;
  name: string;
  kind: string;
  geometry: string;
  colour: number;
  colour_name: string;
  trans: boolean;
  body: string;
  pos: [number, number, number];
  rot: number;
  upright: boolean;
  size: [number, number, number];
  origin: [number, number, number];
  step: number;
  where: string[];
  tags: string[];
  loose: boolean;
}

export interface PartsTable {
  version: string;
  count: number;
  source: string | null;
  parts: PartRow[];
  bodies: { name: string; count: number; colours: number[] }[];
  colours: { code: number; name: string; count: number; trans: boolean }[];
  kit: { part: string; name: string; kind: string; size: [number, number, number] }[];
  palette: { code: number; name: string; hex: string; trans: boolean }[];
  suggestions: string[];
}

/** Structural stability of the current build (from Lane B's physics engine). */
export interface Physics {
  stable: boolean;
  com: [number, number] | null;
  base: [number, number][];
  /** Studs the centre of mass sits inside the base by (negative = outside). */
  margin?: number;
  /** "-z" | "+z" | "-x" | "+x": which way it would go over. */
  direction?: string;
  /** The ground plane's LDraw Y, in LDU. */
  ground?: number;
  topple_margin?: number;
  sturdiness?: number;
  weakest_layer?: number | null;
  /** Number of stud joints the solver checked (harness builds). */
  studs?: number;
  /** Indices of bricks the force/torque solver couldn't hold — drawn red. */
  broken?: number[];
  failures: { code: string; human: string }[];
}

/** One of the candidate designs, while the run waits for someone to pick. */
export interface Choice {
  n: number;
  /** Where this version came from: the first build, or after the critic's notes. */
  style: string;
  stands: boolean;
  /** The one the critic scored highest. */
  preferred?: boolean;
  parts?: number;
  image?: string;
  ldr: string;
}

/** A model designed on this machine, kept on disk between sessions. */
export interface SavedModel {
  id: string;
  name: string;
  idea?: string;
  parts?: number;
  score?: number | null;
  stands?: boolean;
  made?: string;
  thumb?: boolean;
}

export interface Payload {
  version: string | null;
  name?: string;
  build?: BricolageBuild;
  report?: Report;
  steps?: Steps | null;
  tape?: TapeEvent[];
  tree?: string;
  head?: string | null;
  physics?: Physics;
  /** Present on every mutation once the part-level editor is wired up. */
  edit?: EditResult;
}

const BASE = "/bricolage";
const FIXTURES = "/bricolage-fixtures";

// The SSE stream must skip the Next dev proxy (it buffers streaming responses),
// so EventSource talks to the backend origin directly. Override with
// NEXT_PUBLIC_STREAM_ORIGIN; otherwise the backend is on the same host at the
// port next.config.ts read out of BRICOLAGE_URL (8017 by default, what run.sh
// launches). Non-stream REST calls keep using the proxy.
const STREAM_PORT = process.env.NEXT_PUBLIC_STREAM_PORT || "8017";
const STREAM_ORIGIN =
  process.env.NEXT_PUBLIC_STREAM_ORIGIN ||
  (typeof window !== "undefined" ? `${window.location.protocol}//${window.location.hostname}:${STREAM_PORT}` : "");
const STREAM_BASE = STREAM_ORIGIN ? `${STREAM_ORIGIN}/api` : BASE;

async function request<T>(path: string, init?: RequestInit, timeoutMs = 60000): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${BASE}${path}`, { ...init, signal: ctrl.signal, headers: { "Content-Type": "application/json", ...init?.headers } });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      // 400/409 carry a `human` sentence written as UI copy; prefer it.
      throw new ApiError(body.human ?? body.error ?? `HTTP ${res.status}`, res.status, body.human ?? null);
    }
    const type = res.headers.get("content-type") ?? "";
    return (type.includes("json") ? res.json() : res.text()) as Promise<T>;
  } finally {
    clearTimeout(timer);
  }
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status = 0,
    /** The server's own user-facing sentence, when it sent one. */
    readonly human: string | null = null,
  ) {
    super(message);
  }
}

const post = (path: string, body: unknown = {}, timeoutMs?: number) => request<Payload>(path, { method: "POST", body: JSON.stringify(body) }, timeoutMs);

// Pipeline C revises a brief for an edit (1-3 min) and redesigns from scratch
// for "try another" (6-10 min), so those calls get room to finish.
const DESIGN_TIMEOUT = 15 * 60 * 1000;
/** A part-level edit is geometry, not a model call: it answers in well under a second. */
const EDIT_TIMEOUT = 20 * 1000;

export const bricolage = {
  state: () => request<Payload>("/state"),
  /** Everything designed here, newest first. */
  library: () => request<{ models: SavedModel[] }>("/library"),
  /** A saved model's picture (its front render). */
  thumb: (id: string) => `${BASE}/library/thumb?id=${encodeURIComponent(id)}`,
  /** Make a saved model the current one, so every build screen works on it. */
  open: (id: string) => post("/open", { id }, DESIGN_TIMEOUT),
  ldr: (version?: string) => request<string>(`/ldr${version ? `?version=${encodeURIComponent(version)}` : ""}`),
  build: (prompt: string) => post("/build", { prompt }),
  /** Natural language. The router decides between the instant path and a rebuild. */
  edit: (text: string, selection: string[] = [], base?: string | null) => post("/edit", { text, selection, base, mode: "auto" }, DESIGN_TIMEOUT),
  /** Buttons, keys and drags: resolved ops, gated server-side. */
  editDirect: (ops: EditOp[], opts: { dryRun?: boolean; base: string }) => post("/edit_direct", { ops, dry_run: !!opts.dryRun, base: opts.base }, EDIT_TIMEOUT),
  /** The part table the editor picks against. */
  parts: () => request<PartsTable>("/parts", undefined, EDIT_TIMEOUT),
  /** Seeds a session from LDraw text (a sample model, a lab model). No model call. */
  loadLdr: (body: { name: string; ldr: string; source?: string }) => post("/load_ldr", body, 60 * 1000),
  /** Pick a candidate design mid-run; null hands it back to the critic. */
  choose: (index: number | null, note = "", ask = "") => request<{ ok: boolean }>("/choose", { method: "POST", body: JSON.stringify({ index, note, ask }) }),
  tryAnother: () => post("/try_another", {}, DESIGN_TIMEOUT),
  undo: () => post("/undo"),
  redo: () => post("/redo"),

  /** Upload a reference sketch (data URL) for the next sketch-guided build. */
  uploadSketch: (image: string) => request<{ ok: boolean }>("/sketch", { method: "POST", body: JSON.stringify({ image }) }),

  /** Live build: tape events arrive as they fire; resolves with the final
   *  payload. `opts.sketch` makes the designer build toward the uploaded
   *  sketch; `opts.onOpen` hands back a stop function, so starting another
   *  design can end this one instead of running both into the same screen. */
  stream(prompt: string, onEvent: (e: TapeEvent) => void, opts?: { sketch?: boolean; onOpen?: (stop: () => void) => void }): Promise<Payload> {
    return new Promise((resolve, reject) => {
      // Connect the SSE stream DIRECTLY to the backend, bypassing the Next dev
      // proxy — that proxy buffers streaming responses for the browser, so live
      // tape events never arrive until the build finishes. The backend sends
      // Access-Control-Allow-Origin:* so cross-origin EventSource is fine.
      const es = new EventSource(`${STREAM_BASE}/build_stream?prompt=${encodeURIComponent(prompt)}${opts?.sketch ? "&sketch=1" : ""}`);
      let settled = false;
      const done = (fn: () => void) => {
        if (settled) return;
        settled = true;
        es.close();
        fn();
      };
      es.onmessage = (m) => {
        const data = JSON.parse(m.data);
        if (data.event === "done") done(() => resolve(data as Payload));
        else if (data.event === "error") done(() => reject(new ApiError(data.error ?? "The builder hit an error")));
        else onEvent(data as TapeEvent);
      };
      es.onerror = () => done(() => reject(new ApiError("Lost connection to the builder")));
      opts?.onOpen?.(() => done(() => reject(new ApiError("Replaced by a newer design"))));
    });
  },
};

/** The frozen fixtures, shaped like a live payload. */
export async function fixturePayload(): Promise<{ payload: Payload; ldr: string }> {
  const [build, report, steps, ldr, tape] = await Promise.all([
    fetch(`${FIXTURES}/build.json`).then((r) => r.json()),
    fetch(`${FIXTURES}/report.json`).then((r) => r.json()),
    fetch(`${FIXTURES}/steps.json`).then((r) => r.json()),
    fetch(`${FIXTURES}/model.ldr`).then((r) => r.text()),
    fetch(`${FIXTURES}/tape.sse`).then((r) => r.text()),
  ]);
  return { payload: { version: "fixture", name: build.name, build, report, steps, tape: parseSse(tape) }, ldr };
}

export function parseSse(text: string): TapeEvent[] {
  return text
    .split("\n")
    .filter((l) => l.startsWith("data:"))
    .map((l) => JSON.parse(l.slice(5)))
    .filter((e) => e && e.actor);
}
