// Bundles every LDraw file the build system can emit into one embedded-file
// pack (public/ldraw/parts.pack.ldr), so the app renders Lane B's models with
// no parts library on the machine and no network. Also fetches a Rebrickable
// render for each part in each colour the build system uses.
//
//   LDRAW_DIR=~/ldraw node scripts/build-ldraw-pack.mjs [--no-images]
//
// Re-run whenever bricolage/meta.py or the generators gain a part.

import fs from "node:fs/promises";
import path from "node:path";
import os from "node:os";

const web = path.resolve(import.meta.dirname, "..");
const bricolage = path.resolve(web, "../bricolage");
const ldrawDir = (process.env.LDRAW_DIR ?? path.join(os.homedir(), "ldraw")).replace(/^~/, os.homedir());
const outFile = path.join(web, "public/ldraw/parts.pack.ldr");
const partsOut = path.join(web, "public/parts");

// Mirror LDrawLoader's reference normalisation so embedded names match lookups.
function normalise(ref) {
  let name = ref.trim().replace(/\\/g, "/").toLowerCase();
  if (name.startsWith("s/")) name = `parts/${name}`;
  else if (name.startsWith("48/")) name = `p/${name}`;
  return name;
}

async function exists(p) {
  try {
    await fs.access(p);
    return true;
  } catch {
    return false;
  }
}

async function locate(name) {
  const bare = name.replace(/^parts\//, "").replace(/^p\//, "");
  for (const candidate of [name, `parts/${bare}`, `p/${bare}`]) {
    const full = path.join(ldrawDir, candidate);
    if (await exists(full)) return full;
  }
  return null;
}

async function sourceParts() {
  // Lane B's build system, plus brickify's catalog (mesh-to-bricks).
  const files = ["meta.py", "bricks.py", "generators.py", "sculpt.py", "demo.py", "substitute.py"].map((f) => path.join(bricolage, f));
  files.push(path.resolve(web, "../brickify/brickify/parts.py"), path.resolve(web, "../brickify/brickify/kit.py"));
  const found = new Set();
  for (const p of files) {
    if (!(await exists(p))) continue;
    const text = await fs.readFile(p, "utf8");
    for (const m of text.matchAll(/["'](\d{3,5}[a-z]?\d*[a-z]?)["']/g)) found.add(m[1]);
  }
  const real = [];
  for (const part of found) if (await locate(`${part}.dat`)) real.push(part);
  return real.sort();
}

async function main() {
  if (!(await exists(path.join(ldrawDir, "LDConfig.ldr")))) {
    console.error(`No LDraw library at ${ldrawDir}. Download https://library.ldraw.org/library/updates/complete.zip and set LDRAW_DIR.`);
    process.exit(1);
  }
  const parts = await sourceParts();
  const queue = parts.map((p) => `${p}.dat`);
  const files = new Map();
  const missing = [];
  while (queue.length) {
    const name = normalise(queue.pop());
    if (files.has(name)) continue;
    const full = await locate(name);
    if (!full) {
      missing.push(name);
      files.set(name, null);
      continue;
    }
    const text = (await fs.readFile(full, "utf8")).replace(/\r\n/g, "\n");
    files.set(name, text);
    for (const line of text.split("\n")) {
      const m = line.trim().match(/^1\s+\S+(?:\s+\S+){12}\s+(.+)$/);
      if (m) queue.push(m[1]);
    }
  }

  const config = (await fs.readFile(path.join(ldrawDir, "LDConfig.ldr"), "utf8"))
    .replace(/\r\n/g, "\n")
    .split("\n")
    .filter((l) => l.startsWith("0 !COLOUR"))
    .join("\n");

  // Layout: colour definitions, then embedded files. At load time the app puts
  // the colours ahead of the model text and the files after it (lib/ldraw.ts).
  let out = `${config}\n`;
  for (const [name, text] of [...files].sort(([a], [b]) => a.localeCompare(b))) {
    if (text) out += `0 FILE ${name}\n${text.trimEnd()}\n`;
  }
  await fs.mkdir(path.dirname(outFile), { recursive: true });
  await fs.writeFile(outFile, out);
  const kb = (Buffer.byteLength(out) / 1024).toFixed(0);
  console.log(`parts: ${parts.join(" ")}`);
  console.log(`pack: ${files.size} files, ${kb} KB -> ${path.relative(web, outFile)}${missing.length ? `; missing: ${missing.join(", ")}` : ""}`);

  // Part names as the build system knows them (meta.PART_META), for UI labels.
  const metaText = await fs.readFile(path.join(bricolage, "meta.py"), "utf8");
  const names = Object.fromEntries([...metaText.matchAll(/"(\w+)":\s*\{"name":\s*"([^"]+)"/g)].map((m) => [m[1], m[2]]));
  await fs.writeFile(path.join(web, "src/fixtures/bricolage-parts.json"), JSON.stringify(parts.map((part) => ({ part, name: names[part] ?? null })), null, 1));

  if (process.argv.includes("--no-images")) return;
  const meta = await fs.readFile(path.join(bricolage, "meta.py"), "utf8");
  const rgbBlock = meta.slice(meta.indexOf("COLOR_RGB"), meta.indexOf("}", meta.indexOf("COLOR_RGB")));
  const colours = [...rgbBlock.matchAll(/(\d+):\s*\(/g)].map((m) => Number(m[1]));
  const manifestPath = path.join(web, "src/fixtures/part-images.json");
  const manifest = new Set(JSON.parse(await fs.readFile(manifestPath, "utf8")));
  let fetched = 0;
  for (const part of parts)
    for (const colour of colours) {
      const key = `${colour}/${part}`;
      const dest = path.join(partsOut, String(colour), `${part}.png`);
      if (await exists(dest)) {
        manifest.add(key);
        continue;
      }
      const res = await fetch(`https://cdn.rebrickable.com/media/parts/ldraw/${colour}/${part}.png`);
      if (!res.ok) continue;
      await fs.mkdir(path.dirname(dest), { recursive: true });
      await fs.writeFile(dest, Buffer.from(await res.arrayBuffer()));
      manifest.add(key);
      fetched++;
    }
  await fs.writeFile(manifestPath, JSON.stringify([...manifest].sort()));
  console.log(`images: fetched ${fetched}, manifest ${manifest.size}. Run scripts/cutout-parts.py next.`);
}

main();
