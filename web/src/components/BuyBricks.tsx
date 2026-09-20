"use client";

import { useState } from "react";
import { ShoppingCart, Check } from "lucide-react";
import { ChunkyButton } from "@/components/ui/controls";
import { BRICKLINK_UPLOAD_URL, wantedListXml, estimateTotal, partCount } from "@/lib/bricklink";
import type { BuildPart } from "@/lib/types";

/** The closer: turn the finished model's bill of materials into a real
 * BrickLink order. Copies a Wanted List (every part, colour, quantity) to the
 * clipboard and opens BrickLink's upload page — paste to load the cart. */
export function BuyBricks({ parts }: { parts: BuildPart[] }) {
  const [copied, setCopied] = useState(false);
  if (!parts.length) return null;
  const total = estimateTotal(parts);
  const n = partCount(parts);

  const buy = async () => {
    const xml = wantedListXml(parts);
    try {
      await navigator.clipboard.writeText(xml);
      setCopied(true);
    } catch {
      /* clipboard blocked — the BrickLink tab still opens */
    }
    window.open(BRICKLINK_UPLOAD_URL, "_blank", "noopener,noreferrer");
  };

  return (
    <div className="mt-4">
      <ChunkyButton variant="green" onClick={buy} className="!text-[17px]" icon={<ShoppingCart size={22} strokeWidth={2.4} />}>
        Buy the bricks · ~${total.toFixed(2)}
      </ChunkyButton>
      <p className="mt-2 flex items-center justify-center gap-1.5 text-[13px] text-ink-soft">
        {copied ? (
          <>
            <Check size={15} strokeWidth={3} className="text-[#2fa84a]" />
            List copied — paste it on the BrickLink tab to load your cart.
          </>
        ) : (
          <>{n} pieces · opens a BrickLink wanted list · est. price</>
        )}
      </p>
    </div>
  );
}
