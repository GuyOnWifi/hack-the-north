"use client";

import type { PartsTable } from "@/lib/bricolage";
import { partImageUrl } from "@/lib/data";

// The pieces `add` accepts, in Minecraft-style grey inventory slots (taste rule
// 7). Tapping one adds it on the first selected piece, or on top of the model.

export function PartTray({ kit, colour, onAdd, disabled }: { kit: PartsTable["kit"]; colour: number; onAdd: (part: string) => void; disabled?: boolean }) {
  if (!kit.length) return null;
  return (
    <div data-sound="off" className="no-scrollbar flex max-w-full gap-2 overflow-x-auto rounded-[14px] bg-white/85 px-3 py-2.5" style={{ animation: "tape-in 180ms ease-out" }}>
      {kit.map((k) => {
        const img = partImageUrl(k.part, colour);
        return (
          <button
            key={k.part}
            type="button"
            aria-label={`Add a ${k.name}`}
            title={k.name}
            disabled={disabled}
            onClick={() => onAdd(k.part)}
            className="grid h-[58px] w-[58px] shrink-0 place-items-center rounded-[6px] p-1 text-[10px] font-[800] leading-tight text-white transition-transform active:scale-95 disabled:opacity-40"
            style={{ background: "#8b8b8b", boxShadow: "inset 2px 2px 0 rgba(0,0,0,0.28), inset -2px -2px 0 rgba(255,255,255,0.3)" }}
          >
            {img ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={img} alt="" className="h-full w-full object-contain drop-shadow-[0_1px_2px_rgba(0,0,0,0.35)]" />
            ) : (
              <span className="text-center [overflow-wrap:anywhere]">{k.name.replace(/^Brick /, "").replace(/^Plate /, "")}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
