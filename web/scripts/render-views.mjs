// Renders LDraw models from four fixed angles, for brickify's critic loop.
// Models are handed to the /lab page directly (request interception), so this
// works against a dev server or a production build and never writes to public/.
//
//   node scripts/render-views.mjs <model.ldr> <outDir> [base=http://localhost:3000]
//   node scripts/render-views.mjs --base <url> <model.ldr>=<outDir> ...   (several at once)
//
// Each model costs one page load and four frames: the camera framing doesn't
// change between views, so turning the model is a frame, not a reload.
import path from "node:path";
import fs from "node:fs/promises";
import { chromium } from "playwright";

const VIEWS = { front: 0, left: 90, back: 180, right: 270 };
const LANES = 3; // parallel pages; swiftshader is CPU-bound, so don't overdo it

const argv = process.argv.slice(2);
let base = "http://localhost:3000";
const jobs = [];
if (argv[0] === "--base") {
  base = argv[1];
  for (const pair of argv.slice(2)) {
    const i = pair.lastIndexOf("=");
    jobs.push({ model: pair.slice(0, i), outDir: pair.slice(i + 1) });
  }
} else {
  const [model, outDir, maybeBase] = argv;
  if (maybeBase) base = maybeBase;
  jobs.push({ model, outDir });
}

const browser = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });

async function render({ model, outDir }, lane) {
  const text = await fs.readFile(model, "utf8");
  await fs.mkdir(outDir, { recursive: true });
  // Service workers (the PWA, in production builds) would serve requests before
  // the interception below sees them, and keep the network from ever going idle.
  const context = await browser.newContext({ viewport: { width: 640, height: 560 }, serviceWorkers: "block" });
  const page = await context.newPage();
  const tag = `__render${lane}__`;
  await page.route(`**/lab/${tag}.ldr*`, (route) => route.fulfill({ status: 200, contentType: "text/plain", body: text }));
  const shoot = async (label) => {
    const file = path.join(outDir, `${label}.png`);
    await page.screenshot({ path: file, timeout: 120000 });
    console.log(file);
  };
  const [first, ...rest] = Object.entries(VIEWS);
  await page.goto(`${base}/lab?m=${tag}&yaw=${first[1]}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("body[data-model-ready]", { timeout: 120000 });
  await page.waitForTimeout(2000); // the camera eases to its framing once
  await shoot(first[0]);
  for (const [label, deg] of rest) {
    await page.evaluate((d) => window.setLabYaw?.(d), deg);
    await page.waitForTimeout(350);
    await shoot(label);
  }
  await context.close();
}

const queue = jobs.map((job, i) => ({ job, i }));
await Promise.all(
  Array.from({ length: Math.min(LANES, jobs.length) }, async (_, lane) => {
    for (;;) {
      const next = queue.shift();
      if (!next) return;
      await render(next.job, lane);
    }
  }),
);
await browser.close();
