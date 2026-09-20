"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { X, Eraser } from "lucide-react";
import { ChunkyButton } from "@/components/ui/controls";
import { bricolage } from "@/lib/bricolage";

/** Draw a rough shape → the harness's planner builds a 3D LEGO model toward that
 * silhouette (uploaded to the backend, referenced with claude -p @image). */
export function SketchPad({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const ref = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);
  const [prompt, setPrompt] = useState("");
  const [hasInk, setHasInk] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const ctx = ref.current!.getContext("2d")!;
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, ref.current!.width, ref.current!.height);
    ctx.strokeStyle = "#1a1a1a";
    ctx.lineWidth = 7;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
  }, []);

  const at = (e: React.PointerEvent) => {
    const c = ref.current!;
    const r = c.getBoundingClientRect();
    return { x: (e.clientX - r.left) * (c.width / r.width), y: (e.clientY - r.top) * (c.height / r.height) };
  };
  const down = (e: React.PointerEvent) => {
    drawing.current = true;
    setHasInk(true);
    const ctx = ref.current!.getContext("2d")!;
    const { x, y } = at(e);
    ctx.beginPath();
    ctx.moveTo(x, y);
  };
  const move = (e: React.PointerEvent) => {
    if (!drawing.current) return;
    const ctx = ref.current!.getContext("2d")!;
    const { x, y } = at(e);
    ctx.lineTo(x, y);
    ctx.stroke();
  };
  const stop = () => (drawing.current = false);
  const clear = () => {
    const ctx = ref.current!.getContext("2d")!;
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, ref.current!.width, ref.current!.height);
    setHasInk(false);
  };

  const build = async () => {
    if (!hasInk || busy) return;
    setBusy(true);
    try {
      await bricolage.uploadSketch(ref.current!.toDataURL("image/png"));
    } catch {
      /* if upload fails we still build from the text prompt */
    }
    const q = prompt.trim() || "this shape";
    router.push(`/create?prompt=${encodeURIComponent(q)}&sketch=1`);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className="w-full max-w-[440px] rounded-[24px] bg-white p-4 shadow-[0_20px_60px_rgba(0,0,0,0.35)]" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h2 className="text-[19px] font-[800] text-ink">Sketch it</h2>
          <button onClick={onClose} aria-label="Close" className="grid h-9 w-9 place-items-center rounded-full hover:bg-black/5">
            <X size={22} />
          </button>
        </div>
        <p className="mt-1 text-[14px] text-ink-soft">Draw a rough shape — the builder matches your silhouette.</p>
        <canvas
          ref={ref}
          width={420}
          height={420}
          onPointerDown={down}
          onPointerMove={move}
          onPointerUp={stop}
          onPointerLeave={stop}
          className="mt-3 aspect-square w-full touch-none rounded-[16px] border-2 border-[#e4e4e4] bg-white"
        />
        <div className="mt-3 flex items-center gap-2">
          <input
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="What is it? (e.g. a flower)"
            className="h-11 min-w-0 flex-1 rounded-[12px] border border-[#e4e4e4] px-3 text-[15px] text-ink outline-none placeholder:text-[#949494]"
          />
          <button onClick={clear} aria-label="Clear" className="grid h-11 w-11 shrink-0 place-items-center rounded-[12px] border border-[#e4e4e4] active:scale-95">
            <Eraser size={20} />
          </button>
        </div>
        <ChunkyButton variant="blue" onClick={build} disabled={!hasInk || busy} className="mt-3 w-full !text-[16px]">
          {busy ? "Building…" : "Build from sketch"}
        </ChunkyButton>
      </div>
    </div>
  );
}
