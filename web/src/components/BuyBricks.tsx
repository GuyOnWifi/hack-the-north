"use client";

import { useState } from "react";
import { ShoppingCart, X, ExternalLink } from "lucide-react";
import { ChunkyButton } from "@/components/ui/controls";
import { BRICKLINK_UPLOAD_URL, wantedListXml, estimateTotal, estimatePart, partCount } from "@/lib/bricklink";
import { colourHex, colourName } from "@/lib/data";
import type { BuildPart } from "@/lib/types";

/** The closer: turn the model's bill of materials into a real order. Clicking
 * opens an in-app panel with every part, colour, quantity and an estimated
 * total — then downloads a BrickLink Wanted List you upload to buy the lot. */
export function BuyBricks({ parts, name = "model" }: { parts: BuildPart[]; name?: string }) {
  const [open, setOpen] = useState(false);
  if (!parts.length) return null;
  const total = estimateTotal(parts);
  const n = partCount(parts);
  const rows = [...parts].sort((a, b) => estimatePart(b) - estimatePart(a));

  const exportToBrickLink = () => {
    const xml = wantedListXml(parts);
    // download the wanted list as a file — works with no login and no clipboard,
    // then open BrickLink's upload page to drop it in.
    const url = URL.createObjectURL(new Blob([xml], { type: "application/xml" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}-bricklink.xml`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    window.open(BRICKLINK_UPLOAD_URL, "_blank", "noopener,noreferrer");
  };

  return (
    <>
      <ChunkyButton variant="green" onClick={() => setOpen(true)} className="mt-4 !text-[17px]" icon={<ShoppingCart size={22} strokeWidth={2.4} />}>
        Buy the bricks · ~${total.toFixed(2)}
      </ChunkyButton>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onClick={() => setOpen(false)}>
          <div className="flex max-h-[92vh] w-full max-w-[440px] flex-col rounded-[24px] bg-white p-4 text-left shadow-[0_20px_60px_rgba(0,0,0,0.4)]" onClick={(e) => e.stopPropagation()}>
            <div className="flex shrink-0 items-center justify-between">
              <h2 className="text-[19px] font-[800] text-ink">Buy the bricks</h2>
              <button onClick={() => setOpen(false)} aria-label="Close" className="grid h-9 w-9 place-items-center rounded-full text-ink hover:bg-black/5 active:scale-95">
                <X size={22} strokeWidth={2.4} />
              </button>
            </div>
            <p className="mt-1 shrink-0 text-[14px] text-ink-soft">
              {n} pieces · <span className="font-[700] text-ink">~${total.toFixed(2)}</span> est.
            </p>

            <div className="no-scrollbar mt-3 min-h-0 flex-1 overflow-y-auto rounded-[14px] border border-[#ececec]">
              {rows.map((p) => (
                <div key={`${p.part}@${p.colour}`} className="flex items-center gap-3 border-b border-[#f1f1f1] px-3 py-2 last:border-0">
                  <span className="h-6 w-6 shrink-0 rounded-[6px] border border-black/10" style={{ background: colourHex(p.colour) }} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[14px] font-[700] text-ink">{p.title}</p>
                    <p className="text-[12px] text-ink-soft">{colourName(p.colour)}</p>
                  </div>
                  <span className="shrink-0 text-[13px] font-[800] text-ink">×{p.count}</span>
                  <span className="w-14 shrink-0 text-right text-[13px] text-ink-soft">${estimatePart(p).toFixed(2)}</span>
                </div>
              ))}
            </div>

            <ChunkyButton variant="green" onClick={exportToBrickLink} className="mt-3 w-full shrink-0 !text-[16px]" icon={<ExternalLink size={20} strokeWidth={2.4} />}>
              Get it on BrickLink
            </ChunkyButton>
            <p className="mt-2 shrink-0 text-center text-[12px] text-ink-soft">Downloads your parts list — upload it on BrickLink to load your cart.</p>
          </div>
        </div>
      )}
    </>
  );
}
