// Turn a finished build's bill of materials into a real BrickLink order — the
// "now go build it for real" step that closes the imagination→physical loop.
//
// BrickLink takes a "Wanted List" as XML you paste at
// https://www.bricklink.com/v2/wanted/upload.page — it loads every part in the
// right colour and quantity, ready to buy. Our part IDs are LDraw numbers, which
// match BrickLink for basic System bricks; colours need an LDraw→BrickLink map.

import type { BuildPart } from "./types";

export const BRICKLINK_UPLOAD_URL = "https://www.bricklink.com/v2/wanted/upload.page";

// LDraw colour code -> BrickLink colour id (the ones the harness emits, plus the
// common steer colours). Unmapped falls back to Light Bluish Gray.
const LDRAW_TO_BL: Record<number, number> = {
  0: 11, // Black
  1: 7, // Blue
  2: 6, // Green
  3: 39, // Dark Turquoise -> Dark Turquoise
  4: 5, // Red
  5: 47, // Dark Pink
  6: 88, // Brown -> Reddish Brown (the purchasable modern brown)
  7: 9, // Light Gray
  8: 10, // Dark Gray
  14: 3, // Yellow
  15: 1, // White
  19: 2, // Tan
  25: 4, // Orange
  27: 34, // Lime
  28: 69, // Dark Tan
  70: 88, // Reddish Brown
  71: 86, // Light Bluish Gray
  72: 85, // Dark Bluish Gray
  73: 42, // Medium Blue
  191: 110, // Bright Light Orange
  226: 103, // Bright Light Yellow
  320: 59, // Dark Red
};
const BL_FALLBACK = 86; // Light Bluish Gray

const blColour = (ldraw: number) => LDRAW_TO_BL[ldraw] ?? BL_FALLBACK;

/** Rough per-part price (USD) so we can show a ballpark total. Not live pricing —
 * a small base plus a little per stud of footprint. Labelled "est." in the UI. */
export function estimatePart(part: BuildPart): number {
  const studs = STUDS[part.part] ?? 2;
  return part.count * (0.06 + 0.025 * studs);
}
const STUDS: Record<string, number> = {
  "3005": 1, "3004": 2, "3622": 3, "3010": 4, "3009": 6, "3008": 8,
  "3003": 4, "3002": 6, "3001": 8, "2456": 12, "3007": 16,
};

export function estimateTotal(parts: BuildPart[]): number {
  return parts.reduce((s, p) => s + estimatePart(p), 0);
}

export function partCount(parts: BuildPart[]): number {
  return parts.reduce((s, p) => s + p.count, 0);
}

/** BrickLink Wanted List XML for the whole build. */
export function wantedListXml(parts: BuildPart[]): string {
  const items = parts
    .map(
      (p) =>
        `  <ITEM>\n    <ITEMTYPE>P</ITEMTYPE>\n    <ITEMID>${p.part}</ITEMID>\n` +
        `    <COLOR>${blColour(p.colour)}</COLOR>\n    <MINQTY>${p.count}</MINQTY>\n  </ITEM>`,
    )
    .join("\n");
  return `<INVENTORY>\n${items}\n</INVENTORY>\n`;
}
