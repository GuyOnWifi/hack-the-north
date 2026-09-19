// Dev-server side of the sim: reads the LDraw library on disk and hands the
// browser only what it asks for.
//
//   GET  /api/catalog          every usable part {id, name, cat} + the colour table
//   GET  /api/pack?parts=a,b   those parts and every subfile they reference, as
//                              one embedded-file text (the format LDrawLoader reads)
//   POST /api/save?run=&name=  writes a rendered photo + its labels to sim/out/;
//                              with a `split` it is added to a YOLO dataset instead
//
// The catalog is cached in sim/.cache so the 24k-file scan happens once.

import fs from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import type { IncomingMessage, ServerResponse } from "node:http";
import type { Plugin } from "vite";

const simDir = path.resolve(import.meta.dirname, "..");
const ldrawDir = (process.env.LDRAW_DIR ?? path.join(os.homedir(), "ldraw")).replace(/^~/, os.homedir());
const cacheFile = path.join(simDir, ".cache/catalog.json");
const outDir = path.join(simDir, "out");

export interface CatalogPart {
  id: string;
  name: string;
  cat: string;
}
export interface CatalogColour {
  code: number;
  name: string;
  hex: string;
  alpha: number;
}

// Categories that are not loose pieces you would find in a pile.
const SKIP_CATEGORIES = new Set(["Sticker", "Baseplate", "Sheet", "Sail", "Minifig", "Figure", "Constraction", "Duplo", "Fabuland", "Mursten", "Electric", "Train", "Boat", "Roadsign", "Flag", "Animal", "String", "Hose", "Rubber", "Cloth", "Plastic"]);

async function buildCatalog(): Promise<{ parts: CatalogPart[]; colours: CatalogColour[] }> {
  const dir = path.join(ldrawDir, "parts");
  const names = (await fs.readdir(dir)).filter((f) => f.endsWith(".dat"));
  const parts: CatalogPart[] = [];
  const buf = Buffer.alloc(700);
  for (const file of names) {
    const fh = await fs.open(path.join(dir, file), "r");
    const { bytesRead } = await fh.read(buf, 0, buf.length, 0);
    await fh.close();
    const head = buf.toString("utf8", 0, bytesRead).replace(/\r/g, "").split("\n");
    const name = (head[0] ?? "").replace(/^0\s+/, "").replace(/\s+/g, " ").trim();
    if (!name || /^[~=_|]/.test(name)) continue;
    if (/\b(Pattern|Sticker|Needs Work)\b/i.test(name)) continue;
    const org = head.find((l) => l.startsWith("0 !LDRAW_ORG"));
    if (!org || !/!LDRAW_ORG\s+(Unofficial_)?Part\b/.test(org)) continue;
    const cat = name.split(" ")[0];
    if (SKIP_CATEGORIES.has(cat)) continue;
    parts.push({ id: file.slice(0, -4), name, cat });
  }
  parts.sort((a, b) => a.name.localeCompare(b.name, "en", { numeric: true }));

  const colours: CatalogColour[] = [];
  const config = await fs.readFile(path.join(ldrawDir, "LDConfig.ldr"), "utf8");
  for (const line of config.split("\n")) {
    const m = line.match(/^0 !COLOUR\s+(\S+)\s+CODE\s+(\d+)\s+VALUE\s+(#[0-9A-Fa-f]{6})/);
    if (!m) continue;
    const code = Number(m[2]);
    if (code === 16 || code === 24) continue;
    // Solid and transparent plastic only: metallic, chrome, rubber, glitter etc. need their own shading.
    if (/\b(CHROME|PEARLESCENT|METAL|RUBBER|MATERIAL|LUMINANCE)\b/.test(line)) continue;
    const alpha = Number(line.match(/ALPHA\s+(\d+)/)?.[1] ?? 255) / 255;
    colours.push({ code, name: m[1].replace(/_/g, " "), hex: m[3].toUpperCase(), alpha });
  }
  return { parts, colours };
}

let catalog: Promise<string> | null = null;
function getCatalog() {
  catalog ??= (async () => {
    try {
      return await fs.readFile(cacheFile, "utf8");
    } catch {
      const text = JSON.stringify(await buildCatalog());
      await fs.mkdir(path.dirname(cacheFile), { recursive: true });
      await fs.writeFile(cacheFile, text);
      return text;
    }
  })();
  catalog.catch(() => (catalog = null));
  return catalog;
}

// Mirror LDrawLoader's reference normalisation so embedded names match lookups.
function normalise(ref: string) {
  let name = ref.trim().replace(/\\/g, "/").toLowerCase();
  if (name.startsWith("s/")) name = `parts/${name}`;
  else if (name.startsWith("48/") || name.startsWith("8/")) name = `p/${name}`;
  return name;
}

const fileCache = new Map<string, Promise<string | null>>();
function readLibraryFile(name: string) {
  let p = fileCache.get(name);
  if (!p) {
    const bare = name.replace(/^parts\//, "").replace(/^p\//, "");
    p = (async () => {
      for (const candidate of [name, `parts/${bare}`, `p/${bare}`]) {
        try {
          return (await fs.readFile(path.join(ldrawDir, candidate), "utf8")).replace(/\r\n/g, "\n");
        } catch {
          // try the next location
        }
      }
      return null;
    })();
    fileCache.set(name, p);
  }
  return p;
}

async function buildPack(parts: string[]) {
  const queue = parts.map((p) => `${p}.dat`);
  const files = new Map<string, string | null>();
  while (queue.length) {
    const name = normalise(queue.pop()!);
    if (files.has(name)) continue;
    const text = await readLibraryFile(name);
    files.set(name, text);
    if (!text) continue;
    for (const line of text.split("\n")) {
      const m = line.trim().match(/^1\s+\S+(?:\s+\S+){12}\s+(.+)$/);
      if (m) queue.push(m[1]);
    }
  }
  let out = "";
  for (const [name, text] of files) if (text) out += `0 FILE ${name}\n${text.trimEnd()}\n`;
  return out;
}

function readBody(req: IncomingMessage) {
  return new Promise<Buffer>((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on("data", (c: Buffer) => chunks.push(c));
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}

const safe = (s: string | null, fallback: string) => (s ?? fallback).replace(/[^\w.-]/g, "_").slice(0, 80) || fallback;

interface SavedLabels {
  visible_min: number;
  pieces: { part: string; name: string; bbox: { x: number; y: number; w: number; h: number } | null; visible: number }[];
  inventory: { part: string; name: string; colour: number; hex: string; count: number; visible_count: number }[];
}

/**
 * Adds one photo to a YOLO-format dataset (the layout Ultralytics trains on directly):
 *   images/{train,val}/NAME.jpg   labels/{train,val}/NAME.txt   meta/NAME.json
 *   data.yaml (class list)        classes.json                   counts.csv
 * The class is the piece shape (LDraw part number); colour lives in meta/. Classes are
 * numbered in the order they first appear, so the list only ever grows within a run.
 */
async function saveToDataset(dir: string, name: string, ext: string, image: Buffer, labels: SavedLabels, split: "train" | "val") {
  for (const sub of [`images/${split}`, `labels/${split}`, "meta"]) await fs.mkdir(path.join(dir, sub), { recursive: true });
  const classesFile = path.join(dir, "classes.json");
  const classes: { part: string; name: string }[] = JSON.parse(await fs.readFile(classesFile, "utf8").catch(() => "[]"));
  const index = new Map(classes.map((c, i) => [c.part, i]));
  const rows: string[] = [];
  for (const p of labels.pieces) {
    if (!index.has(p.part)) {
      index.set(p.part, classes.length);
      classes.push({ part: p.part, name: p.name });
    }
    // Pieces buried under others are left unlabelled: a box the model cannot see teaches it to hallucinate.
    if (!p.bbox || p.visible < labels.visible_min) continue;
    const { x, y, w, h } = p.bbox;
    rows.push(`${index.get(p.part)} ${(x + w / 2).toFixed(6)} ${(y + h / 2).toFixed(6)} ${w.toFixed(6)} ${h.toFixed(6)}`);
  }
  await fs.writeFile(path.join(dir, `images/${split}/${name}.${ext}`), image);
  await fs.writeFile(path.join(dir, `labels/${split}/${name}.txt`), rows.join("\n") + "\n");
  await fs.writeFile(path.join(dir, `meta/${name}.json`), JSON.stringify(labels, null, 1));
  await fs.writeFile(classesFile, JSON.stringify(classes, null, 1));
  const yaml = [`path: ${dir}`, "train: images/train", "val: images/val", `nc: ${classes.length}`, "names:", ...classes.map((c, i) => `  ${i}: "${c.part}"  # ${c.name}`)];
  await fs.writeFile(path.join(dir, "data.yaml"), yaml.join("\n") + "\n");
  const countsFile = path.join(dir, "counts.csv");
  const header = (await fs.access(countsFile).then(() => true, () => false)) ? "" : "image,split,part,name,colour,hex,count,visible_count\n";
  await fs.appendFile(countsFile, header + labels.inventory.map((r) => [`${name}.${ext}`, split, r.part, `"${r.name.replace(/"/g, '""')}"`, r.colour, r.hex, r.count, r.visible_count].join(",")).join("\n") + "\n");
}

async function handle(req: IncomingMessage, res: ServerResponse, url: URL) {
  if (url.pathname === "/api/catalog") {
    res.setHeader("Content-Type", "application/json");
    return res.end(await getCatalog());
  }
  if (url.pathname === "/api/colours") {
    // Raw colour definitions: LDrawLoader needs them ahead of any model text.
    const config = await fs.readFile(path.join(ldrawDir, "LDConfig.ldr"), "utf8");
    res.setHeader("Content-Type", "text/plain; charset=utf-8");
    return res.end(config.replace(/\r\n/g, "\n").split("\n").filter((l) => l.startsWith("0 !COLOUR")).join("\n"));
  }
  if (url.pathname === "/api/pack") {
    const parts = (url.searchParams.get("parts") ?? "").split(",").filter((p) => /^[\w-]+$/.test(p));
    res.setHeader("Content-Type", "text/plain; charset=utf-8");
    return res.end(await buildPack(parts));
  }
  if (url.pathname === "/api/save" && req.method === "POST") {
    const { image, labels, split } = JSON.parse((await readBody(req)).toString("utf8")) as { image: string; labels: SavedLabels; split?: "train" | "val" };
    const dir = path.join(outDir, safe(url.searchParams.get("run"), "run"));
    const name = safe(url.searchParams.get("name"), "scene");
    const ext = image.startsWith("data:image/jpeg") ? "jpg" : "png";
    const bytes = Buffer.from(image.slice(image.indexOf(",") + 1), "base64");
    if (split) await saveToDataset(dir, name, ext, bytes, labels, split);
    else {
      await fs.mkdir(dir, { recursive: true });
      await fs.writeFile(path.join(dir, `${name}.${ext}`), bytes);
      await fs.writeFile(path.join(dir, `${name}.json`), JSON.stringify(labels, null, 1));
    }
    res.setHeader("Content-Type", "application/json");
    return res.end(JSON.stringify({ dir: path.relative(simDir, dir), name }));
  }
  res.statusCode = 404;
  res.end("not found");
}

export function ldrawPlugin(): Plugin {
  return {
    name: "brick-sim-ldraw",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = new URL(req.url ?? "/", "http://localhost");
        if (!url.pathname.startsWith("/api/")) return next();
        handle(req, res, url).catch((err: unknown) => {
          res.statusCode = 500;
          res.end(String(err));
        });
      });
    },
  };
}
