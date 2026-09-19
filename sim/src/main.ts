import { computeLabels, VISIBLE_MIN, type SceneLabels } from "./labels";
import { HARMONIES, makePalette, type Harmony } from "./palette";
import { loadParts, type CatalogPart, type Colour } from "./parts";
import { makeRng } from "./rng";
import { World } from "./world";

const PHOTO_SIZE = 1600;
/** Physics steps per frame while making a training set: nobody is watching the fall, so run it flat out. */
const FAST_STEPS = 16;
const THUMB = (id: string) => `https://cdn.rebrickable.com/media/parts/ldraw/71/${id}.png`;

const FAMILIES: { key: string; label: string; on: boolean; test: (p: CatalogPart) => boolean }[] = [
  { key: "round", label: "Round", on: true, test: (p) => /\bRound\b/.test(p.name) || ["Cylinder", "Cone", "Dish"].includes(p.cat) },
  { key: "brick", label: "Bricks", on: true, test: (p) => p.cat === "Brick" },
  { key: "plate", label: "Plates", on: true, test: (p) => p.cat === "Plate" },
  { key: "tile", label: "Tiles", on: true, test: (p) => p.cat === "Tile" },
  { key: "slope", label: "Slopes", on: true, test: (p) => p.cat === "Slope" },
  { key: "wedge", label: "Wedges and wings", on: false, test: (p) => p.cat === "Wedge" || p.cat === "Wing" },
  { key: "technic", label: "Technic", on: false, test: (p) => p.cat === "Technic" },
  { key: "other", label: "Everything else", on: false, test: () => true },
];

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const el = {
  stage: $<HTMLCanvasElement>("stage"), answers: $<HTMLCanvasElement>("answers"), panel: $("panel"), status: $("status"),
  kinds: $<HTMLInputElement>("kinds"), families: $("families"), chosen: $("chosen"), search: $<HTMLInputElement>("search"), results: $("results"),
  harmony: $<HTMLSelectElement>("harmony"), paletteSize: $<HTMLInputElement>("palette-size"), swatches: $("swatches"), snap: $<HTMLInputElement>("snap"),
  count: $<HTMLInputElement>("count"), countRange: $<HTMLInputElement>("count-range"), crowding: $<HTMLInputElement>("crowding"),
  drop: $<HTMLButtonElement>("drop"), dropLabel: $("drop-label"), save: $<HTMLButtonElement>("save"), batch: $<HTMLButtonElement>("batch"), batchN: $<HTMLInputElement>("batch-n"),
  reshuffle: $<HTMLInputElement>("reshuffle"), vary: $<HTMLInputElement>("vary"), photoSize: $<HTMLSelectElement>("photo-size"), showAnswers: $<HTMLInputElement>("show-answers"),
  shufflePieces: $("shuffle-pieces"), shuffleColours: $("shuffle-colours"),
};

const world = new World(el.stage);
const say = (text: string) => (el.status.textContent = text);
const clampInt = (input: HTMLInputElement) => Math.min(Math.max(Math.round(Number(input.value) || Number(input.min)), Number(input.min)), Number(input.max));

let catalog: CatalogPart[] = [];
let library: Colour[] = [];
let familyOf = new Map<string, string>();
let chosen: CatalogPart[] = [];
let palette: Colour[] = [];
let seed = Math.floor(Math.random() * 1e9);
let busy = false;
let dirty = true;

/* ---------- pieces ---------- */

function shufflePieces() {
  const rng = makeRng(seed++);
  const on = new Set(FAMILIES.filter((f) => f.on).map((f) => f.key));
  const pool = catalog.filter((p) => on.has(familyOf.get(p.id)!));
  chosen = pool.sort(() => rng.next() - 0.5).slice(0, clampInt(el.kinds));
  renderChosen();
}

function renderChosen() {
  el.chosen.replaceChildren(
    ...chosen.map((p) => {
      const b = document.createElement("button");
      b.type = "button";
      b.title = `${p.name} (${p.id}). Click to remove.`;
      const img = new Image();
      img.loading = "lazy";
      img.alt = p.name;
      img.src = THUMB(p.id);
      img.onerror = () => img.replaceWith(p.id);
      b.append(img);
      b.onclick = () => {
        chosen = chosen.filter((c) => c !== p);
        renderChosen();
      };
      return b;
    }),
  );
  el.kinds.value = String(chosen.length || el.kinds.value);
}

function renderFamilies() {
  el.families.replaceChildren(
    ...FAMILIES.map((f) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = f.label;
      b.setAttribute("aria-pressed", String(f.on));
      b.onclick = () => {
        f.on = !f.on;
        if (!FAMILIES.some((x) => x.on)) f.on = true;
        renderFamilies();
        shufflePieces();
      };
      return b;
    }),
  );
}

function renderResults() {
  const q = el.search.value.trim().toLowerCase();
  const words = q.split(/\s+/);
  const hits = q ? catalog.filter((p) => p.id.toLowerCase().startsWith(q) || words.every((w) => p.name.toLowerCase().includes(w))).slice(0, 40) : [];
  el.results.hidden = !q;
  el.results.replaceChildren(
    ...(hits.length
      ? hits.map((p) => {
          const li = document.createElement("li");
          const b = document.createElement("button");
          b.type = "button";
          b.innerHTML = `<span></span><small></small>`;
          b.children[0].textContent = p.name;
          b.children[1].textContent = p.id;
          b.onclick = () => {
            if (!chosen.includes(p)) chosen = [p, ...chosen];
            el.search.value = "";
            renderResults();
            renderChosen();
          };
          li.append(b);
          return li;
        })
      : [Object.assign(document.createElement("li"), { textContent: "No piece matches that. Try a number like 3001 or a name like slope 45.", style: "padding:8px;font-size:13px;color:var(--ink-soft)" })]),
  );
}

/* ---------- colours ---------- */

function shuffleColours() {
  palette = makePalette(el.harmony.value as Harmony, clampInt(el.paletteSize), library, el.snap.checked, makeRng(seed++));
  renderSwatches();
}

function renderSwatches() {
  const add = document.createElement("label");
  add.title = "Add your own colour";
  add.append("+");
  const picker = Object.assign(document.createElement("input"), { type: "color", value: "#ff7a00" });
  picker.onchange = () => {
    const hex = picker.value.toUpperCase();
    if (!palette.some((c) => c.hex === hex)) palette.push({ code: -1, name: hex, hex, alpha: 1 });
    renderSwatches();
  };
  add.append(picker);
  el.swatches.replaceChildren(
    ...palette.map((c) => {
      const b = document.createElement("button");
      b.type = "button";
      b.style.background = c.hex;
      b.title = `${c.name}. Click to remove.`;
      b.onclick = () => {
        if (palette.length > 1) palette = palette.filter((x) => x !== c);
        renderSwatches();
      };
      return b;
    }),
    add,
  );
}

/* ---------- view ---------- */

function resize() {
  const w = window.innerWidth, h = window.innerHeight;
  world.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  world.renderer.setSize(w, h, false);
  const wide = window.matchMedia("(min-width: 761px)").matches;
  world.frame({ left: wide ? el.panel.getBoundingClientRect().right : 0, width: w, height: h });
  el.answers.width = w;
  el.answers.height = h;
  drawAnswers();
  dirty = true;
}

function drawAnswers() {
  const ctx = el.answers.getContext("2d")!;
  const w = el.answers.width, h = el.answers.height;
  ctx.clearRect(0, 0, w, h);
  if (!el.showAnswers.checked || world.phase !== "settled") return;
  const labels = computeLabels(world, world.camera, w, h, seed, "");
  ctx.lineWidth = 1.5;
  for (const l of labels.pieces) {
    if (!l.bbox) continue;
    ctx.setLineDash(l.visible >= VISIBLE_MIN ? [] : [4, 3]);
    ctx.strokeStyle = "rgb(24 32 44 / 0.85)";
    ctx.strokeRect(l.bbox.x * w + 0.5, l.bbox.y * h + 0.5, l.bbox.w * w, l.bbox.h * h);
  }
}

function tick() {
  if (world.phase === "dropping" || world.phase === "slumping") {
    if (world.advance(busy ? FAST_STEPS : World.STEPS_PER_FRAME)) onSettled();
    dirty = true;
  }
  if (dirty) {
    world.render();
    dirty = false;
  }
  requestAnimationFrame(tick);
}

let settled: (() => void) | null = null;
function onSettled() {
  el.save.disabled = false;
  if (!busy) say(`${world.pieces.length} pieces on the plate. Save the photo to get its answer sheet.`);
  drawAnswers();
  settled?.();
}

/* ---------- actions ---------- */

interface Pile {
  kinds: CatalogPart[];
  colours: Colour[];
  count: number;
  crowding: number;
}
const pileFromPanel = (): Pile => ({ kinds: chosen, colours: palette, count: clampInt(el.count), crowding: Number(el.crowding.value) });

async function drop(pile = pileFromPanel()) {
  if (!pile.kinds.length) return say("Pick at least one piece first.");
  el.drop.disabled = true;
  el.save.disabled = true;
  const { loaded, skipped } = await loadParts(pile.kinds, (done, total) => say(`Fetching piece shapes: ${done} of ${total}`));
  if (skipped.length) {
    // Oversized or empty shapes never reach the plate; keep the tray honest about it.
    chosen = chosen.filter((p) => !skipped.includes(p));
    renderChosen();
  }
  if (!loaded.length) {
    el.drop.disabled = false;
    return say("None of those pieces could be loaded. Shuffle for a different set.");
  }
  world.drop(loaded, pile.colours, pile.count, pile.crowding, makeRng(seed));
  resize();
  ctxClear();
  if (!busy) say(skipped.length ? `Dropping ${pile.count} pieces. Left out ${skipped.length} that were too big for a plate.` : `Dropping ${pile.count} pieces`);
  await new Promise<void>((resolve) => (settled = resolve));
  settled = null;
  el.drop.disabled = false;
}

function ctxClear() {
  el.answers.getContext("2d")!.clearRect(0, 0, el.answers.width, el.answers.height);
}

async function savePhoto(run: string, name: string, set?: { size: number; split: "train" | "val"; handheld: boolean }) {
  const size = set?.size ?? PHOTO_SIZE;
  const camera = world.photoCamera(set?.handheld ? makeRng(seed ^ 0x9e3779b9) : undefined);
  const image = world.photo(size, camera, Boolean(set));
  const labels: SceneLabels = computeLabels(world, camera, size, size, seed, `${name}.${set ? "jpg" : "png"}`);
  dirty = true;
  const res = await fetch(`/api/save?run=${encodeURIComponent(run)}&name=${encodeURIComponent(name)}`, { method: "POST", body: JSON.stringify({ image, labels, split: set?.split }) });
  if (!res.ok) throw new Error(await res.text());
  return (await res.json()) as { dir: string; name: string };
}

const stamp = () => new Date().toISOString().replace(/[-:]/g, "").replace("T", "-").slice(0, 15);

el.drop.onclick = () => {
  seed++;
  void drop();
};

el.save.onclick = async () => {
  try {
    const { dir, name } = await savePhoto("photos", `plate-${stamp()}`);
    say(`Saved sim/${dir}/${name}.png and its answer sheet, ${name}.json`);
  } catch (err) {
    say(`Could not save the photo: ${String(err)}`);
  }
};

let stopRequested = false;
el.batch.onclick = async () => {
  if (busy) {
    stopRequested = true;
    el.batch.textContent = "Stopping after this photo";
    return;
  }
  if (!chosen.length) return say("Pick at least one piece first.");
  const n = clampInt(el.batchN);
  const size = Number(el.photoSize.value);
  const run = `set-${stamp()}`;
  const base = pileFromPanel();
  const kinds = [...chosen];
  busy = true;
  stopRequested = false;
  el.batch.textContent = "Stop";
  let made = 0;
  try {
    for (let i = 1; i <= n && !stopRequested; i++) {
      seed++;
      const rng = makeRng(seed ^ 0x51ed270b);
      const pile = { ...base };
      if (el.reshuffle.checked) {
        // Same classes throughout, but every photo shows a different mix, palette, pile size and crowding.
        pile.kinds = [...kinds].sort(() => rng.next() - 0.5).slice(0, Math.max(1, Math.round(kinds.length * rng.range(0.35, 1))));
        pile.colours = makePalette(el.harmony.value as Harmony, clampInt(el.paletteSize), library, el.snap.checked, rng);
        pile.count = Math.max(1, Math.round(base.count * rng.range(0.4, 1.3)));
        pile.crowding = Math.min(Math.max(base.crowding * rng.range(0.6, 1.6), 0.2), 1.4);
      }
      world.varyRng = el.vary.checked ? rng : null;
      await drop(pile);
      // Every seventh photo is held back for validation.
      await savePhoto(run, String(i).padStart(5, "0"), { size, split: i % 7 === 0 ? "val" : "train", handheld: el.vary.checked });
      made = i;
      say(`Training set: photo ${i} of ${n}`);
    }
    say(made ? `Saved ${made} photos to sim/out/${run}. Train with its data.yaml.` : "Stopped before the first photo.");
  } catch (err) {
    say(`The set stopped early after ${made} photos: ${String(err)}`);
  }
  world.varyRng = null;
  busy = false;
  el.batch.textContent = "Make training set";
};

function syncCount(from: HTMLInputElement) {
  const n = clampInt(from);
  if (from !== el.count) el.count.value = String(n);
  if (from !== el.countRange) el.countRange.value = String(n);
  el.dropLabel.textContent = `Drop ${n} ${n === 1 ? "piece" : "pieces"}`;
}
el.count.oninput = () => syncCount(el.count);
el.count.onchange = () => (el.count.value = String(clampInt(el.count)));
el.countRange.oninput = () => syncCount(el.countRange);
el.kinds.onchange = shufflePieces;
el.shufflePieces.onclick = shufflePieces;
el.shuffleColours.onclick = shuffleColours;
el.harmony.onchange = shuffleColours;
el.paletteSize.onchange = shuffleColours;
el.snap.onchange = shuffleColours;
el.search.oninput = renderResults;
el.search.onkeydown = (e) => {
  if (e.key === "Escape") {
    el.search.value = "";
    renderResults();
  }
};
el.showAnswers.onchange = drawAnswers;
window.addEventListener("resize", resize);

/* ---------- start ---------- */

for (const [value, label] of [...Object.entries(HARMONIES).map(([k, h]) => [k, h.label]), ["classic", "Classic brick box"], ["any", "Anything goes"]]) el.harmony.add(new Option(label, value));
el.harmony.value = "triadic";
renderFamilies();
resize();
requestAnimationFrame(tick);
say("Reading the parts library");

try {
  const data = (await (await fetch("/api/catalog")).json()) as { parts: CatalogPart[]; colours: Colour[] };
  catalog = data.parts;
  library = data.colours;
  familyOf = new Map(catalog.map((p) => [p.id, FAMILIES.find((f) => f.test(p))!.key]));
  shufflePieces();
  shuffleColours();
  await drop();
} catch (err) {
  say(`Could not read the parts library. Is the LDraw folder at ~/ldraw? (${String(err)})`);
}
