"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef } from "react";
import { X } from "lucide-react";
import { FloatingBricks, PlateProgress } from "@/components/ui/chrome";
import { ChunkyButton, IconTile } from "@/components/ui/controls";
import { AgentTape } from "@/components/AgentTape";
import { designBuild, tryAnother, useLive } from "@/lib/live";
import { LIVE_ID } from "@/lib/useBuild";

export default function CreatePage() {
  return (
    <Suspense>
      <Create />
    </Suspense>
  );
}

const EXPECTED_EVENTS = 6;

// Designing (IMG_1230 studio): the agent tape streams in live while Lane B
// routes, designs, inspects, repairs and sequences; then we open the build.
function Create() {
  const params = useSearchParams();
  const router = useRouter();
  const prompt = params.get("prompt")?.trim() || "build a rover";
  const live = useLive();
  const started = useRef<string | null>(null);

  useEffect(() => {
    if (started.current === prompt) return;
    started.current = prompt;
    designBuild(prompt);
  }, [prompt]);

  const valid = live.payload?.report?.ok !== false;
  useEffect(() => {
    if (live.status !== "ready" || live.prompt !== prompt || !valid) return;
    const t = setTimeout(() => router.replace(`/build/${LIVE_ID}`), 900);
    return () => clearTimeout(t);
  }, [live.status, live.prompt, prompt, router, valid]);

  const events = live.prompt === prompt ? live.tape : [];
  const done = live.status === "ready" && live.prompt === prompt;
  const failed = live.status === "error" && live.prompt === prompt;
  const progress = done ? 1 : Math.min(0.92, events.length / EXPECTED_EVENTS);

  return (
    <main className="fixed inset-0 flex flex-col items-center overflow-hidden" style={{ background: "linear-gradient(180deg,#6e6e6e 0%,#838383 50%,#959595 100%)" }}>
      <FloatingBricks tone="grey" />
      <div className="absolute right-5 top-5 z-10" style={{ marginTop: "var(--safe-top)" }}>
        <IconTile tone="glass-light" label="Cancel" href="/builds" size={60}>
          <X size={32} strokeWidth={2.6} />
        </IconTile>
      </div>

      <div className="relative z-10 flex w-full max-w-[520px] flex-1 flex-col px-5" style={{ paddingTop: "calc(var(--safe-top) + 96px)" }}>
        <p className="text-center text-[15px] font-bold uppercase tracking-wide text-white/70">{done ? (valid ? "Designed" : "Almost") : "Designing"}</p>
        <h1 className="mt-1 text-center text-[28px] font-[900] leading-tight tracking-[-0.02em] text-white">&ldquo;{prompt}&rdquo;</h1>
        {live.source === "fixture" && live.prompt === prompt && <p className="mt-2 text-center text-[14px] font-semibold text-white/80">The builder is offline, so this is the saved sample.</p>}

        <div className="no-scrollbar mt-6 min-h-0 flex-1 overflow-auto rounded-[24px] bg-[#eef0f2]/90 p-3 shadow-[0_18px_40px_rgba(0,0,0,0.25)]">
          {failed ? (
            <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
              <p className="text-[19px] font-[800] text-ink">The builder didn&apos;t answer</p>
              <p className="text-[15px] text-ink-soft">{live.error}</p>
              <div className="mt-2 flex w-full gap-3">
                <ChunkyButton variant="white" href="/builds">
                  Back
                </ChunkyButton>
                <ChunkyButton variant="blue" onClick={() => designBuild(prompt)}>
                  Try again
                </ChunkyButton>
              </div>
            </div>
          ) : events.length === 0 ? (
            <div className="flex h-full items-center justify-center gap-2 text-[15px] font-semibold text-ink-soft">
              <span className="h-2 w-2 animate-pulse rounded-full bg-purple" /> Reading your bricks…
            </div>
          ) : (
            <AgentTape events={events} live={!done} />
          )}
        </div>
        {done && !valid && (
          <div className="mt-4 rounded-[20px] bg-white p-4" style={{ animation: "tape-in 260ms ease-out" }}>
            <p className="text-[17px] font-[800] text-ink">That design doesn&apos;t fit your bricks yet</p>
            <ul className="mt-2 flex flex-col gap-1.5">
              {live.payload?.report?.errors.map((e, i) => (
                <li key={i} className="rounded-[12px] bg-[#fde8ea] px-3 py-2 text-[14px] font-semibold text-[#9b1020]">
                  {e.human}
                </li>
              ))}
            </ul>
            <div className="mt-4 flex gap-3">
              <ChunkyButton variant="white" href="/builds" className="!text-[16px]">
                New idea
              </ChunkyButton>
              <ChunkyButton variant="blue" className="!text-[16px]" onClick={() => tryAnother().catch(() => {})}>
                Try another
              </ChunkyButton>
            </div>
          </div>
        )}
        {done && valid && (
          <Link href={`/build/${LIVE_ID}`} className="mt-4 text-center text-[16px] font-bold text-white underline-offset-4 hover:underline">
            Open the build
          </Link>
        )}
      </div>

      <div className="relative z-10 pt-6" style={{ paddingBottom: "calc(var(--safe-bottom) + 30px)" }}>
        <PlateProgress value={progress} count={14} />
      </div>
    </main>
  );
}
