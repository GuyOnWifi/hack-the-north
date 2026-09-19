"use client";

import { useEffect, useRef, useState } from "react";
import { PartImage } from "@/components/three/Snapshots";

export interface PartCell {
  key: string;
  part: string;
  colour: number;
  count: number;
  /** Optional corner badge (confidence chip, missing marker). */
  badge?: React.ReactNode;
  /** Visual emphasis ring. */
  ring?: string;
  onClick?: () => void;
}

/**
 * The parts page layout (IMG_1243 / IMG_1244): columns of part renders with
 * "12x" counts, scrolling sideways, with a thin white-thumb scrollbar.
 */
export function PartsScroller({ cells, size = 60 }: { cells: PartCell[]; size?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [thumb, setThumb] = useState({ left: 0, width: 100 });
  const [rows, setRows] = useState(4);
  const cellH = size + 30;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setRows(Math.max(1, Math.floor(el.clientHeight / cellH))));
    ro.observe(el);
    return () => ro.disconnect();
  }, [cellH]);

  const columns: PartCell[][] = [];
  for (let i = 0; i < cells.length; i += rows) columns.push(cells.slice(i, i + rows));

  const measure = () => {
    const el = ref.current;
    if (!el) return;
    const width = Math.min(100, (el.clientWidth / Math.max(1, el.scrollWidth)) * 100);
    const left = (el.scrollLeft / Math.max(1, el.scrollWidth)) * 100;
    setThumb({ left, width });
  };
  useEffect(() => {
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [cells.length, rows]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div ref={ref} onScroll={measure} className="no-scrollbar flex min-h-0 flex-1 gap-2 overflow-x-auto overflow-y-hidden px-[calc(var(--safe-left)+24px)]">
        {columns.map((col, i) => (
          <div key={i} className="flex shrink-0 flex-col justify-center" style={{ width: size * 1.9 }}>
            {col.map((c) => (
              <button
                key={c.key}
                onClick={c.onClick}
                disabled={!c.onClick}
                className="relative flex flex-col items-start rounded-[16px] p-1 text-left transition-transform enabled:active:scale-95"
                style={{ height: cellH, boxShadow: c.ring ? `inset 0 0 0 3px ${c.ring}` : undefined }}
              >
                <div className="flex w-full justify-center">
                  <PartImage part={c.part} colour={c.colour} size={size} />
                </div>
                <span className="-mt-1 text-[13px] font-[700] text-ink">{c.count}x</span>
                {c.badge && <span className="absolute right-1 top-1">{c.badge}</span>}
              </button>
            ))}
          </div>
        ))}
      </div>
      {thumb.width < 100 && (
        <div className="mx-[calc(var(--safe-left)+76px)] mb-[calc(var(--safe-bottom)+18px)] mt-3 h-[10px] rounded-full bg-black/20">
          <div className="h-full rounded-full bg-white" style={{ marginLeft: `${thumb.left}%`, width: `${thumb.width}%` }} />
        </div>
      )}
    </div>
  );
}
