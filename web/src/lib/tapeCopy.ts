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

/** Pipeline C names sub-assemblies like "earL" / "wingR" / "body". */
function bodyName(n: string) {
  const side = n.match(/^(.+?)([LR])$/);
  const base = (side ? side[1] : n).replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase();
  return side ? `${side[2] === "L" ? "left" : "right"} ${base}` : base;
}

const plural = (n: string, word: string) => `${n} ${word}${n === "1" ? "" : "s"}`;

/** Lines from pipeline C (brickify/brickify/pipeline.py). */
function pipelineC(e: TapeEvent, t: string): TapeCopy | null {
  let m: RegExpMatchArray | null;
  switch (e.actor) {
    case "router":
      if ((m = t.match(/^'([^']+)': distill, concept.*x(\d+) max$/))) return { text: `Designing "${m[1]}": concept art, a brick plan, then up to ${m[2]} builds` };
      return null;
    case "planner":
      if ((m = t.match(/^making '([^']+)' buildable/))) return { text: `Working out how "${m[1]}" can be built in bricks` };
      if ((m = t.match(/^concept: (.*?)(?: \(changed: .*\))?$/))) return { text: `The plan: ${m[1]}` };
      return null;
    case "designer":
      if (/^drawing the concept/.test(t)) return { text: "Drawing the concept art" };
      if (/^concept ready/.test(t)) return { text: "The concept art is ready" };
      if (/^turning the concept/.test(t)) return { text: "Drawing it from the side and the back" };
      if ((m = t.match(/^got (\d+) extra view/))) return { text: m[1] === "0" ? "Couldn't draw the other sides, so going from the front" : "Got the side and back views" };
      if (/^reading the concept and writing/.test(t)) return { text: "Turning the art into a brick plan" };
      if ((m = t.match(/^brief written: (\d+) sub-assemblies/))) return { text: `Brick plan ready: ${plural(m[1], "section")}` };
      if ((m = t.match(/^changing it: (.*)$/))) return { text: `Changing it: ${m[1]}` };
      if (/^image generation failed/.test(t)) return { text: "Couldn't draw the concept art" };
      return null;
    case "inspector": {
      if (/would tip over/.test(t)) return { text: "It would tip over, so the base needs to grow" };
      const hits = [...t.matchAll(/in body '([^']+)' collides with \S+ in body '([^']+)'/g)];
      if (hits.length) {
        const pairs = [...new Set(hits.map((h) => [bodyName(h[1]), bodyName(h[2])].sort().join(" and ")))];
        return pairs.length > 1 ? { text: `Pieces overlap in ${pairs.length} places`, parts: pairs } : { text: `Pieces overlap where the ${pairs[0]} meet` };
      }
      if (/could not be built/.test(t)) return { text: "That plan didn't make sense to the builder" };
      if (/still unbuildable/.test(t)) return { text: "Couldn't turn the plan into bricks" };
      if (/couldn't build that change/.test(t)) return { text: "Couldn't build that change, so keeping the last model" };
      return null;
    }
    case "repair":
      if (/revised the brief/.test(t)) return { text: "Reworked the plan so every brick fits" };
      return null;
    case "builder":
      if ((m = t.match(/^round (\d+): (\d+) parts, (\d+) collisions, (stands|tips [^(]*)(?: \(trimmed (\d+)\))?$/))) {
        const notes = [
          m[5] ? `trimmed ${plural(m[5], "piece")} where sections met` : "",
          m[3] === "0" ? "" : `${plural(m[3], "piece")} still overlapping`,
          m[4].startsWith("stands") ? "stands up" : "it would tip over",
        ].filter(Boolean);
        return { text: `Built version ${Number(m[1]) + 1}: ${plural(m[2], "brick")}, ${notes.join(", ")}` };
      }
      return null;
    case "critic":
      if (/^comparing the renders/.test(t)) return { text: "Comparing the build with the concept art" };
      if ((m = t.match(/^score ([\d.]+)\/10: (.*)$/))) {
        const first = m[2].split(";")[0].trim();
        return { text: `Scored it ${m[1]}/10${first ? `. Next: ${first.charAt(0).toLowerCase()}${first.slice(1)}` : ""}` };
      }
      if (/^critique failed/.test(t)) return { text: "Couldn't review it, so keeping the best so far" };
      return null;
    case "scribe":
      if ((m = t.match(/^best: round (\d+) scored ([\d.]+|None)\/10 \((\d+) parts\)/)))
        return { text: m[2] === "None" ? `Picked version ${Number(m[1]) + 1} (${plural(m[3], "brick")})` : `Picked version ${Number(m[1]) + 1}: ${Number(m[2])}/10, ${plural(m[3], "brick")}` };
      if (/^no buildable model/.test(t)) return { text: "Nothing buildable came out of this one" };
      return null;
  }
  return null;
}

export function tapeCopy(e: TapeEvent): TapeCopy {
  // Edit events (docs/EDITING.md E.5) are already written as plain words —
  // rewriting them here would only mangle them.
  if (e.kind.startsWith("edit.")) return { text: e.text };

  const t = e.text.trim();
  let m: RegExpMatchArray | null;

  const c = pipelineC(e, t);
  if (c) return c;

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
