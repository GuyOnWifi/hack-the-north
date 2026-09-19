import * as THREE from "three";
import { LDrawLoader } from "three/examples/jsm/loaders/LDrawLoader.js";
import { LDrawConditionalLineMaterial } from "three/examples/jsm/materials/LDrawConditionalLineMaterial.js";
import { ConvexHull } from "three/examples/jsm/math/ConvexHull.js";

/** World units per LDraw unit: 1 stud (20 LDU) = 1 world unit. */
const LDU = 1 / 20;
const MAIN_COLOUR = "16";
/** Parts longer than this (in studs) are hulls, track and plates no one throws in a pile. */
export const MAX_PART_SIZE = 12;

export interface CatalogPart {
  id: string;
  name: string;
  cat: string;
}
export interface Colour {
  /** LDraw colour code, or -1 for a custom colour. */
  code: number;
  name: string;
  hex: string;
  alpha: number;
}

export interface PartType {
  id: string;
  name: string;
  /** Geometry centred on the bounding-box centre, upright, in studs. `fixed[i]` is null where the piece colour applies. */
  meshes: { geometry: THREE.BufferGeometry; fixed: (THREE.Material | null)[] }[];
  /** Convex hull vertices (xyz triples) for the physics collider. */
  hull: Float32Array;
  size: THREE.Vector3;
  /** Area the piece covers lying flat, in square studs. */
  footprint: number;
}

const loader = new LDrawLoader();
loader.setConditionalLineMaterial(LDrawConditionalLineMaterial); // required even though the sim drops edge lines
loader.smoothNormals = true;
const cache = new Map<string, PartType | null>();
let colourDefs: Promise<string> | null = null;

function hullPoints(geometries: THREE.BufferGeometry[]) {
  const seen = new Set<string>();
  const points: THREE.Vector3[] = [];
  for (const g of geometries) {
    const pos = g.getAttribute("position");
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i), y = pos.getY(i), z = pos.getZ(i);
      const key = `${Math.round(x * 200)},${Math.round(y * 200)},${Math.round(z * 200)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      points.push(new THREE.Vector3(x, y, z));
    }
  }
  const out = new Set<THREE.Vector3>();
  for (const face of new ConvexHull().setFromPoints(points).faces) {
    let edge = face.edge;
    do {
      out.add(edge.head().point);
      edge = edge.next;
    } while (edge !== face.edge);
  }
  const flat = new Float32Array(out.size * 3);
  let i = 0;
  for (const p of out) {
    flat[i++] = p.x;
    flat[i++] = p.y;
    flat[i++] = p.z;
  }
  return flat;
}

function toPartType(part: CatalogPart, group: THREE.Object3D): PartType | null {
  // LDraw is -Y up and in LDU: flip and scale once, here, so everything downstream is in studs.
  const fix = new THREE.Matrix4().makeRotationX(Math.PI).multiply(new THREE.Matrix4().makeScale(LDU, LDU, LDU));
  group.updateMatrixWorld(true);
  const meshes: PartType["meshes"] = [];
  group.traverse((o) => {
    const mesh = o as THREE.Mesh;
    if (!mesh.isMesh) return;
    const geometry = mesh.geometry.clone().applyMatrix4(new THREE.Matrix4().multiplyMatrices(fix, mesh.matrixWorld));
    const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    meshes.push({ geometry, fixed: mats.map((m) => (String(m.userData.code) === MAIN_COLOUR ? null : m)) });
  });
  if (!meshes.length) return null;

  const box = new THREE.Box3();
  for (const m of meshes) {
    m.geometry.computeBoundingBox();
    box.union(m.geometry.boundingBox!);
  }
  const centre = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  if (Math.max(size.x, size.y, size.z) > MAX_PART_SIZE) return null;
  for (const m of meshes) {
    m.geometry.translate(-centre.x, -centre.y, -centre.z);
    m.geometry.computeBoundingBox();
    m.geometry.computeBoundingSphere();
  }
  const dims = [size.x, size.y, size.z].sort((a, b) => b - a);
  return { id: part.id, name: part.name, meshes, hull: hullPoints(meshes.map((m) => m.geometry)), size, footprint: dims[0] * dims[1] };
}

async function loadBatch(parts: CatalogPart[]) {
  colourDefs ??= fetch("/api/colours").then((r) => r.text());
  const [colours, files] = await Promise.all([colourDefs, fetch(`/api/pack?parts=${parts.map((p) => p.id).join(",")}`).then((r) => r.text())]);
  const model = parts.map((p) => `1 16 0 0 0 1 0 0 0 1 0 0 0 1 ${p.id}.dat`).join("\n");
  const root = await new Promise<THREE.Group>((resolve, reject) => loader.parse(`${colours}\n${model}\n${files}`, resolve, reject));
  const byFile = new Map<string, THREE.Object3D>();
  for (const child of root.children) byFile.set(String(child.userData.fileName ?? "").toLowerCase().replace(/^.*\//, ""), child);
  parts.forEach((p, i) => {
    const group = byFile.get(`${p.id.toLowerCase()}.dat`) ?? (root.children.length === parts.length ? root.children[i] : undefined);
    let type: PartType | null = null;
    try {
      type = group ? toPartType(p, group) : null;
    } catch (err) {
      console.warn(`Skipping ${p.id}:`, err); // degenerate geometry (flat or empty): not throwable
    }
    cache.set(p.id, type);
  });
}

/** Loads (and caches) the given part types. Parts that are too big or have no usable geometry come back in `skipped`. */
export async function loadParts(parts: CatalogPart[], onProgress: (done: number, total: number) => void) {
  const todo = parts.filter((p) => !cache.has(p.id));
  const BATCH = 12;
  for (let i = 0; i < todo.length; i += BATCH) {
    const batch = todo.slice(i, i + BATCH);
    try {
      await loadBatch(batch);
    } catch {
      // One bad file fails the whole parse: retry the batch one part at a time.
      for (const p of batch)
        await loadBatch([p]).catch((err: unknown) => {
          console.warn(`Could not load ${p.id}:`, err);
          cache.set(p.id, null);
        });
    }
    onProgress(Math.min(i + BATCH, todo.length), todo.length);
  }
  const loaded: PartType[] = [];
  const skipped: CatalogPart[] = [];
  for (const p of parts) {
    const t = cache.get(p.id);
    if (t) loaded.push(t);
    else skipped.push(p);
  }
  return { loaded, skipped };
}

const materials = new Map<string, THREE.Material>();
/** Glossy ABS plastic in the given colour. */
export function plastic(colour: Colour) {
  const key = `${colour.hex}/${colour.alpha}`;
  let m = materials.get(key);
  if (!m) {
    const trans = colour.alpha < 1;
    // ABS reads as two things at once: a soft, fully opaque, saturated body (the rough base)
    // under a thin hard skin that gives small crisp highlights (the clearcoat).
    m = new THREE.MeshPhysicalMaterial({
      color: colour.hex,
      roughness: trans ? 0.1 : 0.52,
      metalness: 0,
      clearcoat: trans ? 0.4 : 0.28,
      clearcoatRoughness: 0.1,
      envMapIntensity: 0.8,
      transparent: trans,
      opacity: trans ? 0.62 : 1,
    });
    materials.set(key, m);
  }
  return m;
}

export function buildPiece(type: PartType, colour: Colour) {
  const group = new THREE.Group();
  const main = plastic(colour);
  for (const { geometry, fixed } of type.meshes) {
    const mats = fixed.map((m) => m ?? main);
    const mesh = new THREE.Mesh(geometry, mats.length === 1 ? mats[0] : mats);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    group.add(mesh);
  }
  return group;
}
