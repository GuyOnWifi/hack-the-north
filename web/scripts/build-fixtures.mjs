// Parses the packed LDraw models in public/models into JSON fixtures the UI consumes
// (catalog of builds + a scanned-inventory fixture), and downloads Rebrickable part
// renders into public/parts so the app works offline.
//
//   node scripts/build-fixtures.mjs [--no-images]

import fs from "node:fs/promises";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const modelsDir = path.join(root, "public/models");
const outDir = path.join(root, "src/fixtures");
const partsDir = path.join(root, "public/parts");

const BUILDS = [
  { id: "car", file: "car.mpd", name: "Street Racer", theme: "Vehicles", age: "6+", builders: "1-2", tagline: "A low, fast hatchback with chunky tyres." },
  { id: "radar-truck", file: "radar-truck.mpd", name: "Radar Truck", theme: "Vehicles", age: "7+", builders: "1-2", tagline: "A service truck with a rotating radar dish." },
  { id: "lunar", file: "lunar.mpd", name: "Lunar Rover", theme: "Space", age: "8+", builders: "1-3", tagline: "A six-wheeled moon buggy with a crane arm." },
];

function parseMpd(text) {
  const files = new Map();
  const colours = new Map();
  // In a packed MPD the main model is the content before the first FILE header.
  let current = { name: "__root__", title: null, type: "Root", refs: [], steps: 0 };
  files.set(current.name, current);
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    const colour = line.match(/^0 !COLOUR (\S+)\s+CODE\s+(\d+)\s+VALUE\s+(#[0-9A-Fa-f]{6})/);
    if (colour) {
      colours.set(Number(colour[2]), { name: colour[1].replace(/_/g, " "), hex: colour[3].toUpperCase() });
      continue;
    }
    const file = line.match(/^0 FILE (.+)$/);
    if (file) {
      current = { name: normalise(file[1]), title: null, type: null, refs: [], steps: 0 };
      files.set(current.name, current);
      continue;
    }
    if (current.title === null && current.name !== "__root__" && line.startsWith("0 ") && !line.startsWith("0 Name:") && !line.startsWith("0 FILE")) {
      current.title = line.slice(2).trim();
    }
    const type = line.match(/^0 !LDRAW_ORG (\S+)/);
    if (type && current.name !== "__root__") current.type = type[1];
    if (line === "0 STEP") current.steps++;
    const ref = line.match(/^1\s+(\d+)\s+(?:\S+\s+){12}(.+)$/);
    if (ref) current.refs.push({ colour: Number(ref[1]), file: normalise(ref[2]) });
  }
  return { files, colours };
}

function normalise(name) {
  return name.trim().toLowerCase().replace(/\\/g, "/").replace(/^parts\//, "");
}

function isPart(file) {
  return file && /part/i.test(file.type ?? "") && !/subpart|primitive/i.test(file.type ?? "");
}

// Expand submodels recursively; colour 16 means "inherit from parent".
function countParts(files, name, inherited, counts) {
  const file = files.get(name);
  if (!file) return;
  for (const ref of file.refs) {
    const colour = ref.colour === 16 ? inherited : ref.colour;
    const child = files.get(ref.file);
    if (isPart(child) || !child) {
      const partNum = ref.file.replace(/\.dat$/, "").replace(/^s\//, "");
      const key = `${partNum}@${colour}`;
      const entry = counts.get(key) ?? { part: partNum, colour, count: 0, title: child?.title ?? partNum };
      entry.count++;
      counts.set(key, entry);
    } else {
      countParts(files, ref.file, colour, counts);
    }
  }
}

function cleanTitle(title) {
  return title.replace(/^[~=_]+/, "").replace(/\s+/g, " ").trim();
}

// Non-overlapping jittered grid, so each detection's crop contains its piece.
function gridCrop(i, n) {
  const cols = Math.ceil(Math.sqrt(n * 1.33));
  const rows = Math.ceil(n / cols);
  const w = 1 / cols;
  const h = 1 / rows;
  const jx = (((i * 37) % 7) - 3) / 7 * w * 0.12;
  const jy = (((i * 53) % 7) - 3) / 7 * h * 0.12;
  const r = (v) => Number(v.toFixed(4));
  return { x: r((i % cols) * w + w * 0.05 + jx), y: r(Math.floor(i / cols) * h + h * 0.05 + jy), w: r(w * 0.9), h: r(h * 0.9) };
}

async function main() {
  const withImages = !process.argv.includes("--no-images");
  await fs.mkdir(outDir, { recursive: true });
  const builds = [];
  const allParts = new Map();
  let colourTable = new Map();

  for (const build of BUILDS) {
    const text = await fs.readFile(path.join(modelsDir, build.file), "utf8");
    const { files, colours } = parseMpd(text);
    colourTable = new Map([...colourTable, ...colours]);
    const mainFile = files.get("__root__");
    const counts = new Map();
    countParts(files, mainFile.name, 7, counts);
    const parts = [...counts.values()]
      .map((p) => ({ ...p, title: cleanTitle(p.title) }))
      .sort((a, b) => a.colour - b.colour || b.count - a.count);
    const pieces = parts.reduce((n, p) => n + p.count, 0);
    builds.push({ ...build, model: `/models/${build.file}`, pieces, parts });
    for (const p of parts) {
      const key = `${p.part}@${p.colour}`;
      const entry = allParts.get(key) ?? { ...p, count: 0 };
      entry.count = Math.max(entry.count, p.count);
      allParts.set(key, entry);
    }
  }

  const colourJson = Object.fromEntries([...colourTable].map(([code, c]) => [code, c]));

  // Scanned-inventory fixture: a plausible pile made of the parts and colours
  // Lane B's build system can actually use (src/fixtures/bricolage-parts.json,
  // written by build-ldraw-pack.mjs), so "Try a sample pile" leads to real
  // designs. Deterministic spread of confidences exercises every chip state.
  const bricolageParts = JSON.parse(await fs.readFile(path.join(outDir, "bricolage-parts.json"), "utf8"));
  const names = Object.fromEntries(bricolageParts.map((p) => [p.part, p.name ?? (p.part === "4073" ? "Round Plate 1x1" : p.part)]));
  const pileParts = ["3001", "3003", "3004", "3005", "3010", "3009", "3002", "3020", "3022", "3023", "3024", "3039", "3040", "4073"].filter((p) => names[p]);
  // Core colours are well stocked (a real kid's bin skews this way, and it's what
  // the build system needs to succeed); the rest are sparse.
  const coreColours = [4, 15, 72, 14, 71];
  const pileColours = [...coreColours, 1, 0, 19];
  const family = (part) => (names[part] ?? "").split(" ")[0];
  const inventory = [];
  let i = 0;
  for (const colour of pileColours)
    for (const part of pileParts) {
      const h = (Number(part.replace(/\D/g, "")) * 7 + colour * 13) % 10;
      const core = coreColours.includes(colour);
      if (!core && h > 5) continue;
      const r = (i * 37) % 100;
      const status = r < 72 ? "confident" : r < 92 ? "review" : "unknown";
      const confidence = status === "confident" ? 0.9 + (r % 9) / 100 : status === "review" ? 0.55 + (r % 20) / 100 : 0.2 + (r % 15) / 100;
      inventory.push({ id: `inv-${i}`, part, colour, title: names[part], count: core ? 8 + ((h * 5 + i) % 13) : 2 + ((h * 5 + i) % 7), status, confidence: Number(confidence.toFixed(2)), crop: null, alternatives: [] });
      i++;
    }
  inventory.forEach((item, k) => (item.crop = gridCrop(k, inventory.length)));
  for (const item of inventory) {
    if (item.status === "confident") continue;
    const pool = pileParts.filter((p) => p !== item.part && family(p) === family(item.part));
    const fallback = pileParts.filter((p) => p !== item.part && !pool.includes(p));
    item.alternatives = [...pool, ...fallback].slice(0, 3).map((part, k) => ({ part, colour: item.colour, title: names[part], confidence: Number((item.confidence * (0.7 - k * 0.2)).toFixed(2)) }));
  }

  await fs.writeFile(path.join(outDir, "builds.json"), JSON.stringify(builds, null, 2));
  await fs.writeFile(path.join(outDir, "inventory.json"), JSON.stringify(inventory, null, 2));
  await fs.writeFile(path.join(outDir, "colours.json"), JSON.stringify(colourJson, null, 2));
  console.log(`builds: ${builds.map((b) => `${b.id}=${b.pieces}pcs/${b.parts.length}types`).join(", ")}`);
  console.log(`inventory rows: ${inventory.length} (${inventory.reduce((n, x) => n + x.count, 0)} pieces), colours: ${colourTable.size}`);

  if (!withImages) return;
  let ok = 0;
  let missing = [];
  const jobs = [...allParts.values()];
  await Promise.all(
    Array.from({ length: 8 }, async () => {
      while (jobs.length) {
        const p = jobs.pop();
        const dest = path.join(partsDir, String(p.colour), `${p.part}.png`);
        try {
          await fs.access(dest);
          ok++;
          continue;
        } catch {}
        const res = await fetch(`https://cdn.rebrickable.com/media/parts/ldraw/${p.colour}/${p.part}.png`);
        if (!res.ok) {
          missing.push(`${p.part}@${p.colour}`);
          continue;
        }
        await fs.mkdir(path.dirname(dest), { recursive: true });
        await fs.writeFile(dest, Buffer.from(await res.arrayBuffer()));
        ok++;
      }
    }),
  );
  const manifest = [...allParts.values()].filter((p) => !missing.includes(`${p.part}@${p.colour}`)).map((p) => `${p.colour}/${p.part}`);
  await fs.writeFile(path.join(outDir, "part-images.json"), JSON.stringify(manifest));
  console.log(`images: ${ok} ok, ${missing.length} missing${missing.length ? ` (${missing.slice(0, 12).join(", ")}${missing.length > 12 ? ", ..." : ""})` : ""}`);
}

main();
