"use client";

import type { InventoryItem } from "@/lib/types";
import { PartImage } from "@/components/three/Snapshots";

/**
 * Stand-in for the captured photo when running on the fixture inventory: the
 * detected parts scattered on a pale table at their crop positions, so boxes
 * and evidence crops line up with something real.
 */
export function PilePhoto({ items, className = "", boxes = 0, focus }: { items: InventoryItem[]; className?: string; boxes?: number; focus?: InventoryItem["crop"] }) {
  const zoom = focus ? 1 / Math.max(focus.w, focus.h) / 1.6 : 1;
  const originX = focus ? (focus.x + focus.w / 2) * 100 : 50;
  const originY = focus ? (focus.y + focus.h / 2) * 100 : 50;
  return (
    <div className={`${/\babsolute\b|\bfixed\b/.test(className) ? "" : "relative"} overflow-hidden ${className}`} style={{ background: "radial-gradient(circle at 40% 35%,#f4f1ea,#dcd6ca)" }}>
      <div className="absolute" style={{ width: `${zoom * 100}%`, height: `${zoom * 100}%`, left: `${50 - originX * zoom}%`, top: `${50 - originY * zoom}%` }}>
        {items.map((it, i) => (
          <div key={it.id} className="absolute" style={{ left: `${it.crop.x * 100}%`, top: `${it.crop.y * 100}%`, width: `${it.crop.w * 100}%`, height: `${it.crop.h * 100}%`, transform: `rotate(${((i * 47) % 70) - 35}deg)` }}>
            <PartImage part={it.part} colour={it.colour} size={64} className="!h-full !w-full drop-shadow-[0_3px_2px_rgba(0,0,0,0.25)]" />
          </div>
        ))}
        {items.slice(0, boxes).map((it) => (
          <div
            key={`box-${it.id}`}
            className="absolute rounded-[6px] border-[2.5px]"
            style={{
              left: `${it.crop.x * 100}%`,
              top: `${it.crop.y * 100}%`,
              width: `${it.crop.w * 100}%`,
              height: `${it.crop.h * 100}%`,
              borderColor: it.status === "confident" ? "#2fbf5b" : it.status === "review" ? "#ffb400" : "#bdbdbd",
              animation: "tape-in 220ms ease-out",
            }}
          />
        ))}
      </div>
    </div>
  );
}
