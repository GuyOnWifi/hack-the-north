"use client";

import Link from "next/link";
import { IsoBrick } from "@/components/ui/IsoBrick";

export default function Error({ reset }: { error: Error; reset: () => void }) {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-parts-bg px-8 text-center">
      <IsoBrick w={2} d={2} h={3} color="#e3000b" size={80} />
      <h1 className="text-[28px] font-[900] tracking-[-0.02em] text-ink">Something came apart</h1>
      <p className="max-w-[320px] text-[16px] text-ink-soft">That screen hit a snag. Your bricks and builds are safe.</p>
      <div className="mt-2 flex w-full max-w-[340px] gap-3">
        <button onClick={reset} className="chunky h-[58px] flex-1 rounded-[16px] bg-white text-[18px] font-bold text-ink" style={{ ["--rim" as string]: "#cccccc" } as React.CSSProperties}>
          Try again
        </button>
        <Link href="/home" className="chunky flex h-[58px] flex-1 items-center justify-center rounded-[16px] bg-blue text-[18px] font-bold text-white" style={{ ["--rim" as string]: "#034aa9" } as React.CSSProperties}>
          Home
        </Link>
      </div>
    </main>
  );
}
