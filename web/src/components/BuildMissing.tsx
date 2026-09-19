"use client";

import { BrickLoader } from "@/components/ui/Logo";

import { notFound } from "next/navigation";
import { ChunkyButton } from "@/components/ui/controls";
import { IsoBrick, BrickGlyph } from "@/components/ui/IsoBrick";

/** What a build screen shows when its build isn't available (yet). */
export function BuildMissing({ pending, live }: { pending: boolean; live: boolean }) {
  if (!live) notFound();
  if (pending)
    return (
      <main className="grid min-h-dvh place-items-center bg-parts-bg">
        <BrickLoader label="Loading your build…" />
      </main>
    );
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-parts-bg px-8 text-center">
      <IsoBrick w={2} d={2} h={3} color="#b5b5b5" size={80} />
      <h1 className="text-[26px] font-[900] tracking-[-0.02em] text-ink">No design yet</h1>
      <p className="max-w-[320px] text-[16px] text-ink-soft">Tell the builder what you want and it&apos;ll design one from your bricks.</p>
      <div className="mt-2 w-full max-w-[320px]">
        <ChunkyButton variant="yellow" href="/builds" icon={<BrickGlyph size={34} />}>
          Design a build
        </ChunkyButton>
      </div>
    </main>
  );
}
