"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import { useState } from "react";
import { FloatingBricks } from "@/components/ui/chrome";
import { LogoMark, Wordmark } from "@/components/ui/Logo";
import { play } from "@/lib/sound";

const GlassBrick = dynamic(() => import("@/components/three/GlassBrick").then((m) => m.GlassBrick), { ssr: false });

// Splash (IMG_1223): dark display card over a blue card, floating bricks,
// glowing rings and a slowly turning smoked brick.
export default function Splash() {
  const [ready, setReady] = useState(false);
  return (
    <main className="mx-auto flex min-h-dvh max-w-[520px] flex-col bg-page">
      <Link href="/home" aria-label="Start" className="relative flex flex-1 flex-col" onClick={() => play("connect", { delayMs: 60 })}>
        <div className="absolute inset-x-[18px] bottom-[-26px] top-0 rounded-b-[44px] bg-blue-under" />
        <div className="relative flex min-h-[calc(100dvh-110px)] flex-1 flex-col overflow-hidden rounded-b-[44px] pb-40" style={{ background: "linear-gradient(180deg,#141414 0%,#272727 50%,#3c3c3c 100%)" }}>
          <FloatingBricks tone="colour" />
          <div className="relative z-10 flex flex-col items-center gap-6" style={{ paddingTop: "calc(var(--safe-top) + 84px)" }}>
            <LogoMark size={112} className="drop-shadow-[0_12px_18px_rgba(0,0,0,0.55)]" />
            <Wordmark size={44} />
          </div>
          <div className="relative z-10 mx-auto my-2 aspect-square w-full max-w-[380px] transition-opacity duration-700" style={{ opacity: ready ? 1 : 0 }}>
            <GlassBrick brick={{ at: [0, 0], size: 0.6 }} rings={{ at: [0, 0], size: 0.9 }} onReady={() => setReady(true)} />
          </div>
          <div className="relative z-10 mb-auto -mt-2 flex flex-col items-center text-white">
            <span className="text-[26px] font-[900] italic leading-none tracking-tight">SNAP &amp;</span>
            <span className="text-[26px] font-[900] italic leading-none tracking-tight" style={{ color: "#ffd502" }}>
              BUILD
            </span>
          </div>
        </div>
      </Link>
      <Link href="/home" className="pb-[calc(var(--safe-bottom)+20px)] pt-12 text-center text-[19px] font-bold text-ink">
        Tap to start
      </Link>
    </main>
  );
}
