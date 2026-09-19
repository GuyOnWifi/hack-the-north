import buildsJson from "@/fixtures/builds.json";
import coloursJson from "@/fixtures/colours.json";
import partImages from "@/fixtures/part-images.json";
import type { Build } from "./types";

export const BUILDS = buildsJson as Build[];

const COLOURS = coloursJson as Record<string, { name: string; hex: string }>;
const IMAGES = new Set(partImages as string[]);

export function getBuild(id: string) {
  return BUILDS.find((b) => b.id === id);
}

export function colourName(code: number) {
  return COLOURS[code]?.name ?? `Colour ${code}`;
}

export function colourHex(code: number) {
  return COLOURS[code]?.hex ?? "#9BA19D";
}

/** Local copy of the Rebrickable LDraw render, or null when we have none. */
export function partImageUrl(part: string, colour: number) {
  return IMAGES.has(`${colour}/${part}`) ? `/parts/${colour}/${part}.png` : null;
}

export const THEMES = [
  { id: "Vehicles", label: "Vehicles", bg: "linear-gradient(180deg,#f3d64b,#e9cc3f)", ink: "#1a1a1a", model: "car" },
  { id: "Space", label: "Space", bg: "linear-gradient(180deg,#1a1a1a,#2b2b2b)", ink: "#ffffff", model: "lunar" },
  { id: "Trucks", label: "Trucks", bg: "linear-gradient(180deg,#2a2a2a,#3a3a3a)", ink: "#ffffff", model: "radar-truck" },
  { id: "Anything", label: "Surprise me", bg: "linear-gradient(180deg,#8fc3ec,#cfe6f8)", ink: "#10284e", model: "car" },
] as const;
