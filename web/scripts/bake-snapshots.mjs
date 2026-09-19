// Pre-renders the bundled sample models' card pictures (every size the UI asks
// for) to public/snapshots, plus any part pictures missing from public/parts, so those screens show plain images instead of
// spinning up WebGL. Needs the dev server running:
//
//   npm run dev -- -p 3210 &  node scripts/bake-snapshots.mjs [http://localhost:3210]
//
// Re-run when a sample model, a card size or the snapshot lighting changes.
import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";

const web = path.resolve(import.meta.dirname, "..");
const base = process.argv[2] ?? "http://localhost:3210";
const builds = JSON.parse(await fs.readFile(path.join(web, "src/fixtures/builds.json"), "utf8"));
// Sizes requested by <ModelSnapshot> for sample builds (home Themes, Build ideas).
const SIZES = [
  [420, 520],
  [480, 360],
  [560, 420],
];

const browser = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const page = await browser.newPage();
await page.goto(`${base}/builds`, { waitUntil: "networkidle" });
await page.waitForFunction(() => typeof window.__bakeSnapshot === "function", null, { timeout: 60000 });
const keys = [];
for (const b of builds)
  for (const [w, h] of SIZES) {
    // Rendered at 2x for sharp phones; the <img> scales it down.
    const data = await page.evaluate(([u, w, h]) => window.__bakeSnapshot(u, w * 2, h * 2), [b.model, w, h]);
    const key = `${b.model.replace(/^.*\//, "").replace(/\.[a-z]+$/, "")}-${w}x${h}`;
    await fs.writeFile(path.join(web, "public/snapshots", `${key}.png`), Buffer.from(data.split(",")[1], "base64"));
    keys.push(key);
    console.log("baked", key);
  }
await fs.writeFile(path.join(web, "src/fixtures/snapshots.json"), JSON.stringify(keys.sort(), null, 1));

// Parts with no Rebrickable image would otherwise make the manual open a
// second WebGL context just to draw them; bake those pictures too.
const manifestPath = path.join(web, "src/fixtures/part-images.json");
const manifest = new Set(JSON.parse(await fs.readFile(manifestPath, "utf8")));
for (const b of builds) {
  const missing = await page.evaluate((u) => window.__bakeMissingParts(u), b.model);
  for (const m of missing) {
    const dir = path.join(web, "public/parts", String(m.colour));
    await fs.mkdir(dir, { recursive: true });
    await fs.writeFile(path.join(dir, `${m.part}.png`), Buffer.from(m.data.split(",")[1], "base64"));
    manifest.add(`${m.colour}/${m.part}`);
    console.log("baked part", `${m.colour}/${m.part}`);
  }
}
await fs.writeFile(manifestPath, JSON.stringify([...manifest].sort()));
await browser.close();
