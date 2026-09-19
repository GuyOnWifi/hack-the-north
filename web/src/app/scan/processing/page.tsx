"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { FloatingBricks, PlateProgress } from "@/components/ui/chrome";
import { IconTile } from "@/components/ui/controls";
import { PilePhoto } from "@/components/PilePhoto";
import { INVENTORY_FIXTURE } from "@/lib/data";
import { setSession, useSession } from "@/lib/store";

const DURATION = 4800;
const TIMEOUT = 20000;

// Scanning (IMG_1230): grey studio with drifting brick silhouettes, the photo
// card in the middle with detections popping in, plate-stack progress below.
export default function Processing() {
  const router = useRouter();
  const session = useSession();
  const [t, setT] = useState(0);
  const [error, setError] = useState(false);
  const items = INVENTORY_FIXTURE;

  useEffect(() => {
    const start = performance.now();
    let raf = 0;
    const tick = () => {
      const e = performance.now() - start;
      setT(Math.min(1, e / DURATION));
      if (e < DURATION) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    // Fixture pipeline: resolves after the animation. The real endpoint swaps in here.
    const done = setTimeout(() => {
      setSession((s) => ({ inventory: INVENTORY_FIXTURE, scanned: true, photo: s.photo }));
      router.replace("/inventory");
    }, DURATION + 400);
    const timeout = setTimeout(() => setError(true), TIMEOUT);
    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(done);
      clearTimeout(timeout);
    };
  }, [router]);

  const found = Math.round(items.reduce((n, i) => n + i.count, 0) * Math.min(1, t * 1.15));
  const boxes = Math.round(items.length * Math.min(1, t * 1.1));

  return (
    <main className="fixed inset-0 flex flex-col items-center overflow-hidden" style={{ background: "linear-gradient(180deg,#6e6e6e 0%,#838383 50%,#959595 100%)" }}>
      <FloatingBricks tone="grey" />
      <div className="absolute right-5 top-5 z-10" style={{ marginTop: "var(--safe-top)" }}>
        <IconTile tone="glass-light" label="Cancel" href="/scan" size={60}>
          <X size={32} strokeWidth={2.6} />
        </IconTile>
      </div>

      <div className="relative z-10 flex flex-1 flex-col items-center justify-center gap-6 px-8">
        <div className="relative aspect-[4/3] w-[min(78vw,420px)] overflow-hidden rounded-[18px] shadow-[0_18px_40px_rgba(0,0,0,0.35)]">
          {session.photo ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={session.photo} alt="Your bricks" className="absolute inset-0 h-full w-full object-cover" />
          ) : (
            <PilePhoto items={items} boxes={boxes} className="absolute inset-0" />
          )}
          <div className="pointer-events-none absolute inset-x-0 h-[3px] bg-[#ffd502] shadow-[0_0_18px_4px_rgba(255,213,2,0.6)]" style={{ top: `${(Math.sin(t * Math.PI * 3) * 0.5 + 0.5) * 100}%` }} />
        </div>
        <div className="text-center text-white">
          {error ? (
            <>
              <p className="text-[22px] font-[800]">This is taking a while</p>
              <div className="mt-3 flex justify-center gap-4 text-[16px] font-bold">
                <Link href="/scan" className="underline">
                  Try again
                </Link>
                <Link href="/inventory" className="underline">
                  Add pieces by hand
                </Link>
              </div>
            </>
          ) : (
            <>
              <p className="text-[26px] font-[900] tracking-[-0.02em]">{found} pieces found</p>
              <p className="mt-1 text-[16px] font-semibold text-white/75">{t < 0.4 ? "Finding bricks…" : t < 0.8 ? "Matching shapes and colours…" : "Double-checking the tricky ones…"}</p>
            </>
          )}
        </div>
      </div>

      <div className="relative z-10 pb-[calc(var(--safe-bottom)+34px)]">
        <PlateProgress value={t} count={14} />
      </div>
    </main>
  );
}
