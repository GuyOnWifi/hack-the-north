import type { TapeEvent } from "./bricolage";

// Turns Lane B's agent-tape lines (engineer-speak, see bricolage/pipeline.py,
// repair.py, sculpt.py) into plain words for the tower. The original line is
// kept for the "details" view; anything unrecognised is tidied, not dropped.

export interface TapeCopy {
  text: string;
  /** Sub-assemblies named in a design proposal, shown as chips. */
  parts?: string[];
}

const SUB_NAMES: Record<string, string> = {
  chassis: "Chassis",
  cabin: "Cabin",
  axle_pair: "Wheels",
  roof: "Roof",
  wall: "Wall",
  tower: "Tower",
  slab: "Base",
  wing: "Wings",
};

/** "chassis(length=8) + cabin@deck_front + axle_pair@x + axle_pair@y" -> ["Chassis", "Cabin", "Wheels ×2"] */
function subassemblies(text: string) {
  const counts = new Map<string, number>();
  for (const piece of text.split("+")) {
    const gen = piece.trim().match(/^([a-z_]+)/)?.[1];
    if (!gen) continue;
    const name = SUB_NAMES[gen] ?? gen.replace(/_/g, " ");
    counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  return [...counts].map(([name, n]) => (n > 1 ? `${name} ×${n}` : name));
}

const sentence = (s: string) => {
  const t = s.replace(/\s+—\s+/g, ". ").replace(/\s+/g, " ").trim();
  return t.charAt(0).toUpperCase() + t.slice(1);
};

export function tapeCopy(e: TapeEvent): TapeCopy {
  const t = e.text.trim();
  let m: RegExpMatchArray | null;

  if (e.actor === "router") {
    if ((m = t.match(/^'([^']+)' is a structural object/))) return { text: `Planning a ${m[1]} out of bricks` };
    if ((m = t.match(/^'([^']+)' is an organic shape/))) return { text: `Sculpting a ${m[1]} out of bricks` };
    return { text: sentence(t.replace(/\s*\(backend=[^)]*\)\s*$/, "").replace(/->.*$/, "")) };
  }

  if (e.actor === "designer") {
    if ((m = t.match(/^sketching '([^']+)'/))) return { text: `Sketching the shape of "${m[1]}"` };
    if ((m = t.match(/^proposed a (\d+)-cell shape across (\d+) layers/))) return { text: `Shaped it: ${m[1]} blocks over ${m[2]} layers` };
    if (/^rung 4/.test(t)) return { text: "Tried a smaller design instead" };
    if (/^[a-z_]+\(/.test(t)) {
      const parts = subassemblies(t);
      return { text: "Sketched the design", parts };
    }
    return { text: sentence(t) };
  }

  if (e.actor === "inspector") {
    if (/^build is valid on first try/.test(t)) return { text: "Everything fits on the first try" };
    if (/^all issues resolved/.test(t)) return { text: "Fixed. It stands up on its own" };
    if ((m = t.match(/^budget spent; returning best build with (\d+)/))) return { text: `Couldn't fix ${m[1]} issue${m[1] === "1" ? "" : "s"}, so here's the closest build` };
    if ((m = t.match(/^dropped ([a-z_]+)@[^:]+: (.*)$/))) return { text: `Left out the ${(SUB_NAMES[m[1]] ?? m[1]).toLowerCase()}: ${m[2]}` };
    if (/^composition invalid/.test(t)) return { text: "That design didn't hold together, so starting from a proven one" };
    // "OUT_OF_BUDGET: Needs 6x Brick 2x4 in dark gray; you have 0."
    if ((m = t.match(/^[A-Z_]+:\s*Needs (\d+)x (.+?) in (.+?); you have (\d+)\.?$/))) return { text: `Not enough ${m[3]} ${m[2]} (need ${m[1]}, have ${m[4]})` };
    // Every other validator code already carries a human sentence after the code.
    return { text: sentence(t.replace(/^[A-Z_]+:\s*/, "")) };
  }

  if (e.actor === "repair") {
    if ((m = t.match(/swapped (\d+) part\(s\)/))) return { text: `Swapped ${m[1]} brick${m[1] === "1" ? "" : "s"} for smaller ones you have` };
    if (/re-ran generators one size smaller/.test(t)) return { text: "Made it one size smaller to fit your bricks" };
    if ((m = t.match(/dropped (\d+) unsupported part/))) return { text: `Removed ${m[1]} brick${m[1] === "1" ? "" : "s"} that had nothing holding them up` };
    if (/new seam offset/.test(t)) return { text: "Staggered the bricks so the joins are stronger" };
    if ((m = t.match(/added (\d+) support brick/))) return { text: `Added ${m[1]} support brick${m[1] === "1" ? "" : "s"} so nothing floats` };
    return { text: sentence(t.replace(/^rung \d+:\s*/, "").replace(/^solver:\s*/, "")) };
  }

  // scribe
  if ((m = t.match(/^ordered (\d+) build steps/))) return { text: `Wrote the manual: ${m[1]} steps` };
  if ((m = t.match(/tiled layer (-?\d+) \((\d+) cells\)/))) return { text: `Laid layer ${Number(m[1]) + 1} (${m[2]} studs)` };
  if (/^UNBUILDABLE/.test(t)) return { text: "Couldn't find an order to build it in" };
  return { text: sentence(t) };
}
