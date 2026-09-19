// Scores a scanner's output against a photo's answer sheet.
//
//   node scripts/score.mjs out/photos/plate-XXXX.json predictions.json
//
// predictions.json: an array (or {items: [...]}) of {part, colour|color, count}, the
// shape the app's inventory screen consumes. Buried pieces (visible < visible_min)
// are not expected to be found, so the truth is each row's `visible_count`.

import fs from "node:fs";

const [truthFile, predFile] = process.argv.slice(2);
if (!truthFile || !predFile) {
  console.error("usage: node scripts/score.mjs <answer-sheet.json> <predictions.json>");
  process.exit(1);
}
const truth = JSON.parse(fs.readFileSync(truthFile, "utf8"));
const raw = JSON.parse(fs.readFileSync(predFile, "utf8"));
const preds = Array.isArray(raw) ? raw : raw.items ?? raw.inventory ?? [];

function tally(rows, key, count) {
  const m = new Map();
  for (const r of rows) m.set(key(r), (m.get(key(r)) ?? 0) + count(r));
  return m;
}

function score(label, truthKey, predKey) {
  const t = tally(truth.inventory, truthKey, (r) => r.visible_count);
  const p = tally(preds, predKey, (r) => r.count ?? 1);
  let hit = 0;
  for (const [k, n] of t) hit += Math.min(n, p.get(k) ?? 0);
  const nt = [...t.values()].reduce((a, b) => a + b, 0), np = [...p.values()].reduce((a, b) => a + b, 0);
  const precision = np ? hit / np : 0, recall = nt ? hit / nt : 0;
  const f1 = precision + recall ? (2 * precision * recall) / (precision + recall) : 0;
  console.log(`${label.padEnd(18)} precision ${(precision * 100).toFixed(1)}%  recall ${(recall * 100).toFixed(1)}%  F1 ${(f1 * 100).toFixed(1)}%  (${hit} of ${nt} found, ${np} claimed)`);
  return { t, p };
}

const colourOf = (r) => r.colour ?? r.color;
const { t, p } = score("piece + colour", (r) => `${r.part}/${r.colour}`, (r) => `${r.part}/${colourOf(r)}`);
score("piece only", (r) => r.part, (r) => String(r.part));
score("colour only", (r) => String(r.colour), (r) => String(colourOf(r)));

const misses = [...t].map(([k, n]) => [k, n - Math.min(n, p.get(k) ?? 0)]).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]);
if (misses.length) console.log(`\nMost missed (part/colour): ${misses.slice(0, 10).map(([k, n]) => `${k} x${n}`).join(", ")}`);
