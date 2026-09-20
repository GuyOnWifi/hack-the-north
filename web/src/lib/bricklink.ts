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

// LDraw part number -> BrickLink part number, where they differ. Verified against
// BrickLink's catalog (a valid P=<id> renders; an invalid one 302s to notFound):
//   3068b/3069b/4865a  — BrickLink dropped the mold-variant letter for these
//   6141               — LEGO design id; BrickLink numbers the round 1x1 plate 4073
//   3842a              — renumbered to 193a2
//   3829a              — only sold as the complete assembly 3829c01
//   3626bp01           — legacy print code doesn't resolve; use the plain head
// (Do NOT blanket-strip suffixes: 2412b, 3044a, 3794a, 4865b, most pNN prints are
// valid BrickLink parts. Only these specific ids are wrong.)
const PART_REMAP: Record<string, string> = {
  "3068b": "3068",
  "3069b": "3069",
  "4865a": "4865",
  "6141": "4073",
  "3842a": "193a2",
  "3829a": "3829c01",
  "3626bp01": "3626",
};

// LDraw parts with NO BrickLink Part equivalent — omitted so the whole upload
// isn't rejected for a few unmatchable pieces: `20` (unidentifiable), `3828`
// (steering wheel sub-part, only sold inside 3829c01), `u9132` (unofficial part).
const PART_SKIP = new Set<string>(["20", "3828", "u9132"]);

const blPart = (ldraw: string) => PART_REMAP[ldraw] ?? ldraw;
export const isBuyable = (ldraw: string) => !PART_SKIP.has(ldraw);

/** How many pieces map to BrickLink vs. can't — for an honest UI line. */
export function buyableSummary(parts: BuildPart[]): { buyable: number; skipped: number } {
  let buyable = 0;
  let skipped = 0;
  for (const p of parts) (isBuyable(p.part) ? (buyable += p.count) : (skipped += p.count));
  return { buyable, skipped };
}

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

/** BrickLink Wanted List XML for the whole build. BrickLink allows only ONE
 * entry per (item, colour), so we merge — two LDraw colours can map to the same
 * BrickLink colour (unknowns fall back to Light Bluish Gray), which would
 * otherwise be a rejected duplicate. Quantities are summed. */
export function wantedListXml(parts: BuildPart[]): string {
  const merged = new Map<string, { id: string; colour: number; qty: number }>();
  for (const p of parts) {
    if (!isBuyable(p.part)) continue; // no BrickLink match — omit, don't fail the upload
    const id = blPart(p.part);
    const colour = blColour(p.colour);
    const key = `${id}|${colour}`;
    const e = merged.get(key);
    if (e) e.qty += p.count;
    else merged.set(key, { id, colour, qty: p.count });
  }
  const items = [...merged.values()]
    .map(
      (e) =>
        `  <ITEM>\n    <ITEMTYPE>P</ITEMTYPE>\n    <ITEMID>${e.id}</ITEMID>\n` +
        `    <COLOR>${e.colour}</COLOR>\n    <MINQTY>${e.qty}</MINQTY>\n  </ITEM>`,
    )
    .join("\n");
  return `<INVENTORY>\n${items}\n</INVENTORY>\n`;
}
