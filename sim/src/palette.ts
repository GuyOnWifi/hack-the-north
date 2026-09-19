// Palettes built from colour-wheel harmonies in OKLCH (perceptually even hue and
// lightness), then optionally snapped to the nearest real brick colour so the
// labels stay meaningful to a model trained on real bricks.

import type { Colour } from "./parts";
import type { Rng } from "./rng";

export const HARMONIES = {
  analogous: { label: "Analogous", hues: [-30, -15, 0, 15, 30] },
  complementary: { label: "Complementary", hues: [0, 180] },
  split: { label: "Split complementary", hues: [0, 150, 210] },
  triadic: { label: "Triadic", hues: [0, 120, 240] },
  tetradic: { label: "Tetradic", hues: [0, 90, 180, 270] },
  mono: { label: "Monochrome", hues: [0] },
} as const;
export type Harmony = keyof typeof HARMONIES | "classic" | "any";

/** The colours of a basic brick box, by LDraw code. */
const CLASSIC = [4, 1, 14, 2, 15, 0, 71, 72, 25, 19];

type Lab = [number, number, number];

function hexToLab(hex: string): Lab {
  const lin = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  const l = Math.cbrt(0.4122214708 * lin[0] + 0.5363325363 * lin[1] + 0.0514459929 * lin[2]);
  const m = Math.cbrt(0.2119034982 * lin[0] + 0.6806995451 * lin[1] + 0.1073969566 * lin[2]);
  const s = Math.cbrt(0.0883024619 * lin[0] + 0.2817188376 * lin[1] + 0.6299787005 * lin[2]);
  return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s, 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s, 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s];
}

function oklchToLab(L: number, C: number, hDeg: number): Lab {
  const h = (hDeg * Math.PI) / 180;
  return [L, C * Math.cos(h), C * Math.sin(h)];
}

function labToHex([L, a, b]: Lab) {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const rgb = [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s, -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s];
  return `#${rgb
    .map((c) => {
      const v = c <= 0.0031308 ? 12.92 * c : 1.055 * Math.max(c, 0) ** (1 / 2.4) - 0.055;
      return Math.round(Math.min(Math.max(v, 0), 1) * 255).toString(16).padStart(2, "0");
    })
    .join("")}`.toUpperCase();
}

const distance = (p: Lab, q: Lab) => Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]);

export function makePalette(harmony: Harmony, size: number, library: Colour[], snap: boolean, rng: Rng): Colour[] {
  const solid = library.filter((c) => c.alpha === 1);
  if (harmony === "classic") return CLASSIC.slice(0, Math.max(size, 2)).flatMap((code) => library.find((c) => c.code === code) ?? []);
  if (harmony === "any") return [...solid].sort(() => rng.next() - 0.5).slice(0, size);

  const base = rng.range(0, 360);
  const hues = HARMONIES[harmony].hues;
  const labs = solid.map((c) => hexToLab(c.hex));
  const out: Colour[] = [];
  for (let i = 0; i < size * 6 && out.length < size; i++) {
    // Walk the harmony's hues in turn; vary lightness and chroma so repeats of a hue are tints and shades of it.
    const hue = base + hues[i % hues.length] + rng.range(-7, 7);
    const mono = harmony === "mono";
    const target = oklchToLab(rng.range(mono ? 0.28 : 0.42, mono ? 0.93 : 0.86), rng.range(mono ? 0.04 : 0.09, 0.21), hue);
    let colour: Colour;
    if (snap) {
      let best = 0;
      for (let j = 1; j < labs.length; j++) if (distance(labs[j], target) < distance(labs[best], target)) best = j;
      colour = solid[best];
    } else {
      const hex = labToHex(target);
      colour = { code: -1, name: hex, hex, alpha: 1 };
    }
    if (!out.some((c) => c.hex === colour.hex)) out.push(colour);
  }
  return out;
}
