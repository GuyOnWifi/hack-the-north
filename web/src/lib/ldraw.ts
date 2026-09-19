"use client";

import * as THREE from "three";
import { LDrawLoader } from "three/examples/jsm/loaders/LDrawLoader.js";
import { LDrawConditionalLineMaterial } from "three/examples/jsm/materials/LDrawConditionalLineMaterial.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";

/** World units per LDraw unit: 1 stud (20 LDU) = 1 world unit. */
export const LDU = 1 / 20;

export interface PartNode {
  object: THREE.Object3D;
  part: string;
  colour: number;
  /** Index into the model's list of non-empty steps. */
  step: number;
  /** Resting local position, used for drop-in animation. */
  home: THREE.Vector3;
  meshes: THREE.Mesh[];
}

export interface PreparedModel {
  root: THREE.Group;
  parts: PartNode[];
  stepCount: number;
  /** Bounding box of the whole model in root space. */
  box: THREE.Box3;
}

const sourceCache = new Map<string, Promise<THREE.Group>>();

// Models that arrive as text (Lane B's /api/ldr) are registered under a
// pseudo-URL so every consumer keeps passing a plain string around.
const TEXT_SCHEME = "ldraw-text:";
const texts = new Map<string, string>();
let pack: Promise<{ colours: string; files: string }> | null = null;

export function registerModelText(key: string, text: string) {
  texts.set(key, text);
  return `${TEXT_SCHEME}${key}`;
}

/** Text models carry their own sequenced steps; only packed sample models get auto-stepped. */
export function isAuthoredModel(url: string) {
  return url.startsWith(TEXT_SCHEME);
}

/** The bundled library subset (scripts/build-ldraw-pack.mjs): colours + embedded part files. */
function partsPack() {
  // ?v bust: the pack is a static file the browser caches hard; bump this
  // whenever build-ldraw-pack.mjs regenerates it so a stale cache can't strand
  // a model on a missing part (the "Couldn't load this model" bug).
  pack ??= fetch("/ldraw/parts.pack.ldr?v=3")
    .then((r) => {
      if (!r.ok) throw new Error("Missing /ldraw/parts.pack.ldr");
      return r.text();
    })
    .then((text) => {
      const i = text.indexOf("\n0 FILE ");
      return { colours: text.slice(0, i), files: text.slice(i + 1) };
    });
  pack.catch(() => (pack = null));
  return pack;
}

function newLoader() {
  const loader = new LDrawLoader();
  loader.setConditionalLineMaterial(LDrawConditionalLineMaterial);
  loader.smoothNormals = true;
  return loader;
}

function loadSource(url: string) {
  let p = sourceCache.get(url);
  if (!p) {
    if (url.startsWith(TEXT_SCHEME)) {
      const text = texts.get(url.slice(TEXT_SCHEME.length));
      p = text === undefined ? Promise.reject(new Error(`Unknown model ${url}`)) : partsPack().then(({ colours, files }) => new Promise<THREE.Group>((resolve, reject) => newLoader().parse(`${colours}\n${text}\n${files}`, resolve, reject)));
    } else {
      p = newLoader().loadAsync(url) as Promise<THREE.Group>;
    }
    p.catch(() => sourceCache.delete(url));
    sourceCache.set(url, p);
  }
  return p;
}

function partNumber(name: string) {
  return name
    .toLowerCase()
    .replace(/\\/g, "/")
    .replace(/^.*\//, "")
    .replace(/\.dat$/, "");
}

function resolveColour(obj: THREE.Object3D): number {
  let o: THREE.Object3D | null = obj;
  while (o) {
    const code = o.userData?.colorCode;
    if (code !== undefined && String(code) !== "16" && String(code) !== "24") return Number(code);
    o = o.parent;
  }
  let fallback = 7;
  obj.traverse((c) => {
    const m = (c as THREE.Mesh).material as THREE.Material | THREE.Material[] | undefined;
    const mat = Array.isArray(m) ? m[0] : m;
    if ((c as THREE.Mesh).isMesh && mat?.userData?.code !== undefined) fallback = Number(mat.userData.code);
  });
  return fallback;
}

/**
 * Loads an LDraw file and returns an independent, upright, centred copy with its
 * parts and building steps indexed. Geometry and materials are shared with the
 * cached source, so preparing the same model twice is cheap.
 */
export async function prepareModel(url: string): Promise<PreparedModel> {
  const source = await loadSource(url);
  const model = source.clone(true);
  model.rotation.x = Math.PI; // LDraw is -Y up
  const root = new THREE.Group();
  root.add(model);
  root.scale.setScalar(LDU);
  root.updateMatrixWorld(true);

  // Sit the model on y=0, centred on the origin. model.position lives in root
  // space (LDU), so the world box divided by LDU is the offset to remove.
  const box = new THREE.Box3().setFromObject(root);
  const centre = box.getCenter(new THREE.Vector3());
  model.position.set(-centre.x / LDU, -box.min.y / LDU, -centre.z / LDU);
  root.updateMatrixWorld(true);

  const raw: { object: THREE.Object3D; building: number }[] = [];
  const walk = (o: THREE.Object3D) => {
    for (const child of o.children) {
      if ((child as THREE.Group).isGroup && /\.dat$/i.test(child.name)) {
        raw.push({ object: child, building: child.userData.buildingStep ?? 0 });
      } else {
        walk(child);
      }
    }
  };
  walk(model);

  const stepOf = isAuthoredModel(url) ? authoredSteps(raw) : autoStep(raw);
  const parts: PartNode[] = raw.map(({ object }, i) => {
    const meshes: THREE.Mesh[] = [];
    object.traverse((c) => {
      if ((c as THREE.Mesh).isMesh) meshes.push(c as THREE.Mesh);
    });
    return { object, part: partNumber(object.name), colour: resolveColour(object), step: stepOf[i], home: object.position.clone(), meshes };
  });

  return { root, parts, stepCount: Math.max(...stepOf) + 1, box: new THREE.Box3().setFromObject(root) };
}

/** Lane B's sequencer already grouped steps (0 STEP): keep them, just compact the indices. */
function authoredSteps(raw: { building: number }[]) {
  const order = [...new Set(raw.map((r) => r.building))].sort((a, b) => a - b);
  const index = new Map(order.map((s, i) => [s, i]));
  return raw.map((r) => index.get(r.building)!);
}

const MAX_PER_STEP = 4;
const SPLIT_ABOVE = 6;
const PLATE = 8 * LDU;

/**
 * Keeps the author's STEP order but splits any step with too many parts into
 * manual-sized steps: bottom-up by plate layer, identical parts together, at
 * most MAX_PER_STEP parts each. Models with no STEP markers become one big
 * authored step and get fully auto-stepped.
 */
function autoStep(raw: { object: THREE.Object3D; building: number }[]) {
  const box = new THREE.Box3();
  const info = raw.map((r, i) => {
    box.setFromObject(r.object);
    const c = box.getCenter(new THREE.Vector3());
    return { i, building: r.building, layer: Math.round(box.min.y / PLATE), part: partNumber(r.object.name), x: c.x, z: c.z };
  });
  const authored = [...new Set(info.map((p) => p.building))].sort((a, b) => a - b);
  const out = new Array<number>(raw.length);
  let step = 0;
  for (const b of authored) {
    const group = info.filter((p) => p.building === b);
    if (group.length <= SPLIT_ABOVE) {
      for (const p of group) out[p.i] = step;
      step++;
      continue;
    }
    group.sort((a, c) => a.layer - c.layer || a.part.localeCompare(c.part) || a.x - c.x || a.z - c.z);
    let n = 0;
    let layer = group[0].layer;
    for (const p of group) {
      if (n > 0 && (p.layer !== layer || n >= MAX_PER_STEP)) {
        step++;
        n = 0;
      }
      layer = p.layer;
      out[p.i] = step;
      n++;
    }
    step++;
  }
  return out;
}

/** Parts introduced at a step, grouped as "2x brick 2x4 red". */
export function stepParts(model: PreparedModel, step: number) {
  const groups = new Map<string, { part: string; colour: number; count: number; sample: PartNode }>();
  for (const p of model.parts) {
    if (p.step !== step) continue;
    const key = `${p.part}@${p.colour}`;
    const g = groups.get(key);
    if (g) g.count++;
    else groups.set(key, { part: p.part, colour: p.colour, count: 1, sample: p });
  }
  return [...groups.values()];
}

/** Every part in the model grouped by part+colour, sorted like a parts page. */
export function allParts(model: PreparedModel) {
  const groups = new Map<string, { part: string; colour: number; count: number; sample: PartNode }>();
  for (const p of model.parts) {
    const key = `${p.part}@${p.colour}`;
    const g = groups.get(key);
    if (g) g.count++;
    else groups.set(key, { part: p.part, colour: p.colour, count: 1, sample: p });
  }
  return [...groups.values()].sort((a, b) => a.colour - b.colour || b.count - a.count);
}

// ---------------------------------------------------------------------------
// Offscreen snapshots: one shared WebGL context renders part thumbnails and
// model cards to data URLs, so lists never spin up a canvas per item.

let snap: { renderer: THREE.WebGLRenderer; scene: THREE.Scene; camera: THREE.PerspectiveCamera } | null = null;
const snapCache = new Map<string, Promise<string>>();

function snapper() {
  if (snap) return snap;
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(1);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.setClearColor(0x000000, 0);
  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  const key = new THREE.DirectionalLight(0xffffff, 1.2);
  key.position.set(-3, 6, 4);
  scene.add(key);
  const camera = new THREE.PerspectiveCamera(22, 1, 0.01, 1000);
  snap = { renderer, scene, camera };
  return snap;
}

function render(object: THREE.Object3D, width: number, height: number, direction: THREE.Vector3) {
  const { renderer, scene, camera } = snapper();
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  scene.add(object);
  object.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(object);
  const sphere = box.getBoundingSphere(new THREE.Sphere());
  const fov = THREE.MathUtils.degToRad(camera.fov);
  const fit = Math.min(fov, 2 * Math.atan(Math.tan(fov / 2) * camera.aspect));
  const dist = (sphere.radius / Math.sin(fit / 2)) * 1.02;
  camera.position.copy(sphere.center).addScaledVector(direction.clone().normalize(), dist);
  camera.near = dist / 100;
  camera.far = dist * 10;
  camera.lookAt(sphere.center);
  camera.updateProjectionMatrix();
  renderer.render(scene, camera);
  scene.remove(object);
  return renderer.domElement.toDataURL("image/png");
}

/** Thumbnail of a single part in its world orientation (fallback for missing Rebrickable images). */
export function partThumbnail(node: PartNode, size = 200) {
  const key = `part:${node.part}@${node.colour}:${size}`;
  let p = snapCache.get(key);
  if (!p) {
    p = new Promise<string>((resolve) => {
      const clone = node.object.clone(true);
      const wrapper = new THREE.Group();
      const q = new THREE.Quaternion();
      node.object.getWorldQuaternion(q);
      clone.position.set(0, 0, 0);
      clone.quaternion.copy(q);
      clone.scale.setScalar(LDU);
      wrapper.add(clone);
      resolve(render(wrapper, size, size, new THREE.Vector3(-1, 0.9, 1.25)));
    });
    snapCache.set(key, p);
  }
  return p;
}

/** Beauty shot of a whole model for cards. */
export function modelSnapshot(url: string, width = 640, height = 480) {
  const key = `model:${url}:${width}x${height}`;
  let p = snapCache.get(key);
  if (!p) {
    p = prepareModel(url).then((m) => render(m.root, width, height, new THREE.Vector3(-1.6, 1.05, 1.9)));
    p.catch(() => snapCache.delete(key));
    snapCache.set(key, p);
  }
  return p;
}

/**
 * Printed-manual view of one step: everything placed so far from a fixed
 * isometric camera framed on the finished model, so pages don't jump.
 */
export function renderStep(model: PreparedModel, step: number, width = 1200, height = 900) {
  const saved = model.parts.map((p) => p.object.visible);
  model.parts.forEach((p) => (p.object.visible = p.step <= step));
  const url = renderFramed(model.root, model.box, width, height);
  model.parts.forEach((p, i) => (p.object.visible = saved[i]));
  return url;
}

function renderFramed(object: THREE.Object3D, box: THREE.Box3, width: number, height: number) {
  const { renderer, scene, camera } = snapper();
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  scene.add(object);
  object.updateMatrixWorld(true);
  const sphere = box.getBoundingSphere(new THREE.Sphere());
  const fov = THREE.MathUtils.degToRad(camera.fov);
  const fit = Math.min(fov, 2 * Math.atan(Math.tan(fov / 2) * camera.aspect));
  const dist = (sphere.radius / Math.sin(fit / 2)) * 1.02;
  camera.position.copy(sphere.center).addScaledVector(new THREE.Vector3(-1.35, 1.0, 1.55).normalize(), dist);
  camera.near = dist / 100;
  camera.far = dist * 10;
  camera.lookAt(sphere.center);
  camera.updateProjectionMatrix();
  renderer.render(scene, camera);
  scene.remove(object);
  return renderer.domElement.toDataURL("image/png");
}
