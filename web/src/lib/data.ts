import buildsJson from "@/fixtures/builds.json";
import inventoryJson from "@/fixtures/inventory.json";
import coloursJson from "@/fixtures/colours.json";
import partImages from "@/fixtures/part-images.json";
import type { Build, InventoryItem } from "./types";

export const BUILDS = buildsJson as Build[];
export const INVENTORY_FIXTURE = inventoryJson as InventoryItem[];

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

/** How many of a build's pieces the inventory covers. */
export function coverage(build: Build, inventory: InventoryItem[]) {
  const have = new Map<string, number>();
  for (const item of inventory) have.set(`${item.part}@${item.colour}`, (have.get(`${item.part}@${item.colour}`) ?? 0) + item.count);
  let used = 0;
  for (const p of build.parts) used += Math.min(p.count, have.get(`${p.part}@${p.colour}`) ?? 0);
  return { used, total: build.pieces };
}
