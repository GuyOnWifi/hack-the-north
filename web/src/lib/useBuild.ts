"use client";

import { useEffect } from "react";
import bricolageParts from "@/fixtures/bricolage-parts.json";
import { getBuild } from "./data";
import { resumeLive, useLive } from "./live";
import type { Report } from "./bricolage";
import type { Build, BuildPart } from "./types";

/** The live design session's route id. */
export const LIVE_ID = "live";

const NAMES = new Map((bricolageParts as { part: string; name: string | null }[]).map((p) => [p.part, p.name]));

export interface BuildView {
  build: Build | null;
  /** Lane B design (editable) vs a bundled sample model. */
  live: boolean;
  report: Report | null;
  /** Still waiting on the live session. */
  pending: boolean;
}

/** Resolves a build route id to what the build screens render. */
export function useBuild(id: string): BuildView {
  const live = useLive();
  const isLive = id === LIVE_ID;

  useEffect(() => {
    if (isLive) resumeLive();
  }, [isLive]);

  if (!isLive) return { build: getBuild(id) ?? null, live: false, report: null, pending: false };

  const p = live.payload;
  if (!p?.build || !live.modelUrl) return { build: null, live: true, report: null, pending: live.status === "idle" || live.status === "working" };

  const counts = new Map<string, BuildPart>();
  for (const part of p.build.parts) {
    const key = `${part.part}@${part.color}`;
    const e = counts.get(key) ?? { part: part.part, colour: part.color, count: 0, title: NAMES.get(part.part) ?? `Part ${part.part}` };
    e.count++;
    counts.set(key, e);
  }
  const report = p.report ?? null;
  return {
    live: true,
    report,
    pending: false,
    build: {
      id: LIVE_ID,
      file: "",
      model: live.modelUrl,
      name: p.name ?? p.build.name,
      theme: live.source === "fixture" ? "Offline sample" : "Designed for your bricks",
      age: "6+",
      builders: "1-2",
      tagline: report?.warnings[0]?.human ?? (live.prompt ? `From “${live.prompt}”` : "Designed from your bricks."),
      pieces: p.build.parts.length,
      parts: [...counts.values()].sort((a, b) => a.colour - b.colour || b.count - a.count),
    },
  };
}
