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
  stats: { parts: number; studs_used: number; subs: number; inventory_remaining: number };
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

export type TapeActor = "designer" | "inspector" | "repair" | "scribe" | "router";
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

export interface Payload {
  version: string | null;
  name?: string;
  build?: BricolageBuild;
  report?: Report;
  steps?: Steps | null;
  tape?: TapeEvent[];
  tree?: string;
  head?: string | null;
}

const BASE = "/bricolage";
const FIXTURES = "/bricolage-fixtures";

async function request<T>(path: string, init?: RequestInit, timeoutMs = 60000): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${BASE}${path}`, { ...init, signal: ctrl.signal, headers: { "Content-Type": "application/json", ...init?.headers } });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new ApiError(body.error ?? `HTTP ${res.status}`, res.status);
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
  ) {
    super(message);
  }
}

const post = (path: string, body: unknown = {}) => request<Payload>(path, { method: "POST", body: JSON.stringify(body) });

export const bricolage = {
  state: () => request<Payload>("/state"),
  ldr: () => request<string>("/ldr"),
  build: (prompt: string) => post("/build", { prompt }),
  edit: (text: string) => post("/edit", { text }),
  tryAnother: () => post("/try_another"),
  undo: () => post("/undo"),
  redo: () => post("/redo"),
  setInventory: (items: { part: string; color: number; count: number }[]) => request<{ ok: boolean; elements: number }>("/inventory", { method: "POST", body: JSON.stringify({ items }) }),

  /** Live build: tape events arrive as they fire; resolves with the final payload.
   *
   *  stallMs is a watchdog, not a deadline: it re-arms on every event, so a slow
   *  build that is still emitting tape lines is never cut off. EventSource.onerror
   *  only fires on a CLOSED connection, never on an OPEN-but-silent one, so without
   *  this a server stuck mid-request leaves "Designing…" on screen forever and
   *  designBuild's fixture fallback is unreachable — the one case it exists for.
   *  Sits above the server's own ceiling (45 s deadline) so the server's honest
   *  degrade-to-template wins the race and this stays a last resort. */
  stream(prompt: string, onEvent: (e: TapeEvent) => void, stallMs = 60000): Promise<Payload> {
    return new Promise((resolve, reject) => {
      const es = new EventSource(`${BASE}/build_stream?prompt=${encodeURIComponent(prompt)}`);
      let settled = false;
      let watchdog: ReturnType<typeof setTimeout> | undefined;
      const done = (fn: () => void) => {
        if (settled) return;
        settled = true;
        clearTimeout(watchdog);
        es.close();
        fn();
      };
      const arm = () => {
        clearTimeout(watchdog);
        watchdog = setTimeout(
          () => done(() => reject(new ApiError("The builder stopped responding"))),
          stallMs,
        );
      };
      arm();
      es.onmessage = (m) => {
        arm();
        let data: Payload & { event?: string };
        try {
          data = JSON.parse(m.data);
        } catch {
          return; // a torn frame is not a stall; the watchdog is already re-armed
        }
        if (data.event === "done") done(() => resolve(data as Payload));
        else onEvent(data as unknown as TapeEvent);
      };
      es.onerror = () => done(() => reject(new ApiError("Lost connection to the builder")));
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
