// Renders an LDraw model from fixed angles to PNGs, for brickify's critic loop.
// The model is handed to the /lab page directly (request interception), so it
// works against a dev server or a production build, and never writes to public/.
//   node scripts/render-views.mjs <model.ldr> <outDir> [base=http://localhost:3000]
import path from "node:path";
import fs from "node:fs/promises";
import { chromium } from "playwright";

const [model, outDir, base = "http://localhost:3000"] = process.argv.slice(2);
const VIEWS = { front: 0, left: 90, back: 180, right: 270 };
const text = await fs.readFile(model, "utf8");
await fs.mkdir(outDir, { recursive: true });
const browser = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
// Service workers (the PWA, in production builds) would serve requests before
// the interception below sees them, and keep the network from ever going idle.
const context = await browser.newContext({ viewport: { width: 640, height: 560 }, serviceWorkers: "block" });
const page = await context.newPage();
await page.route("**/lab/__render__.ldr*", (route) => route.fulfill({ status: 200, contentType: "text/plain", body: text }));
for (const [label, deg] of Object.entries(VIEWS)) {
  await page.goto(`${base}/lab?m=__render__&yaw=${deg}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("body[data-model-ready]", { timeout: 120000 });
  await page.waitForTimeout(2500); // camera ease settles
  const file = path.join(outDir, `${label}.png`);
  await page.screenshot({ path: file, timeout: 120000 });
  console.log(file);
}
await browser.close();
