// Renders a lab model (public/lab/<name>.ldr) from fixed angles to PNGs, for
// brickify's critic loop. Needs the dev server running.
//   node scripts/render-views.mjs <name> <outDir> [base=http://localhost:3210]
import path from "node:path";
import fs from "node:fs/promises";
import { chromium } from "playwright";

const [name, outDir, base = "http://localhost:3210"] = process.argv.slice(2);
const VIEWS = { front: 0, left: 90, back: 180, right: 270 };
await fs.mkdir(outDir, { recursive: true });
const browser = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const page = await browser.newPage({ viewport: { width: 640, height: 560 } });
for (const [label, deg] of Object.entries(VIEWS)) {
  await page.goto(`${base}/lab?m=${encodeURIComponent(name)}&yaw=${deg}`, { waitUntil: "networkidle" });
  await page.waitForSelector("body[data-model-ready]", { timeout: 120000 });
  await page.waitForTimeout(2500); // camera ease settles
  const file = path.join(outDir, `${label}.png`);
  await page.screenshot({ path: file, timeout: 120000 });
  console.log(file);
}
await browser.close();
