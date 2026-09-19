"use client";

import { LogoLockup } from "@/components/ui/Logo";

import { useBuild } from "@/lib/useBuild";
import { BuildMissing } from "@/components/BuildMissing";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Check, X } from "lucide-react";
import { FloatingBricks, PlateProgress } from "@/components/ui/chrome";
import { ChunkyButton, IconTile } from "@/components/ui/controls";


type State = { kind: "working"; done: number; total: number } | { kind: "done" } | { kind: "error" };

// PDF export: renders every step off-screen and saves a printable manual.
export default function PrintPage() {
  const { id } = useParams<{ id: string }>();
  const { build, live, pending } = useBuild(id);
  const [state, setState] = useState<State>({ kind: "working", done: 0, total: 1 });
  const started = useRef(false);

  const run = () => {
    if (!build) return;
    setState({ kind: "working", done: 0, total: 1 });
    import("@/lib/pdf")
      .then((m) => m.exportManual(build, (done, total) => setState({ kind: "working", done, total })))
      .then(
        () => setState({ kind: "done" }),
        () => setState({ kind: "error" }),
      );
  };

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!build) return <BuildMissing pending={pending} live={live} />;

  return (
    <main className="fixed inset-0 flex flex-col items-center justify-center gap-6 overflow-hidden px-8 text-center text-white" style={{ background: "linear-gradient(180deg,#6e6e6e 0%,#959595 100%)" }}>
      <FloatingBricks tone="grey" />
      <div className="absolute left-5 top-5 z-10" style={{ marginTop: "calc(var(--safe-top) + 14px)" }}>
        <LogoLockup size={26} ink="#ffffff" />
      </div>
      <div className="absolute right-5 top-5 z-10" style={{ marginTop: "var(--safe-top)" }}>
        <IconTile tone="glass-light" label="Close" href={`/build/${id}`} size={60}>
          <X size={32} strokeWidth={2.6} />
        </IconTile>
      </div>
      <div className="relative z-10 flex max-w-[380px] flex-col items-center gap-5">
        {state.kind === "working" && (
          <>
            <p className="text-[26px] font-[900] tracking-[-0.02em]">Printing your manual…</p>
            <p className="text-[16px] font-semibold text-white/80">{state.done <= 2 ? "Cover and pieces" : `Step ${state.done - 2} of ${state.total - 2}`}</p>
            <PlateProgress value={state.done / state.total} count={14} />
          </>
        )}
        {state.kind === "done" && (
          <>
            <span className="grid h-20 w-20 place-items-center rounded-full bg-white/20">
              <Check size={44} strokeWidth={3} />
            </span>
            <p className="text-[26px] font-[900] tracking-[-0.02em]">Manual downloaded</p>
            <ChunkyButton variant="yellow" href={`/build/${id}/steps`}>
              Start building
            </ChunkyButton>
          </>
        )}
        {state.kind === "error" && (
          <>
            <p className="text-[24px] font-[900]">That didn&apos;t print</p>
            <ChunkyButton variant="white" onClick={run}>
              Try again
            </ChunkyButton>
            <Link href={`/build/${id}`} className="font-bold underline">
              Back to the build
            </Link>
          </>
        )}
      </div>
    </main>
  );
}
