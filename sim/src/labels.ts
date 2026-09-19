// Ground truth for a rendered photo. Every piece is drawn in a flat colour that
// encodes its id; the pixels that survive give its visible box, and drawing it
// alone gives how much of it the others hide.

import * as THREE from "three";
import type { Piece, World } from "./world";

/** A piece counts as findable when at least this share of it is unobstructed. */
export const VISIBLE_MIN = 0.25;

export interface PieceLabel {
  id: number;
  part: string;
  name: string;
  /** LDraw colour code, -1 for a custom colour (see `hex`). */
  colour: number;
  colour_name: string;
  hex: string;
  /** Visible extent, normalised to the image (same convention as the app's `crop`). Null when fully hidden. */
  bbox: { x: number; y: number; w: number; h: number } | null;
  pixels: number;
  /** Share of the piece not hidden behind other pieces, 0..1. */
  visible: number;
}

export interface SceneLabels {
  image: string;
  width: number;
  height: number;
  seed: number;
  visible_min: number;
  pieces: PieceLabel[];
  inventory: { part: string; name: string; colour: number; hex: string; count: number; visible_count: number }[];
}

const idMaterials = new Map<number, THREE.MeshBasicMaterial>();
function idMaterial(id: number) {
  let m = idMaterials.get(id);
  if (!m) {
    m = new THREE.MeshBasicMaterial();
    m.color.setRGB((id & 255) / 255, ((id >> 8) & 255) / 255, 0); // working space, so it reaches the target unchanged
    m.toneMapped = false;
    idMaterials.set(id, m);
  }
  return m;
}

function projectedRect(piece: Piece, camera: THREE.Camera, width: number, height: number) {
  const corner = new THREE.Vector3();
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  piece.object.updateMatrixWorld();
  for (const child of piece.object.children) {
    const box = (child as THREE.Mesh).geometry.boundingBox!;
    for (let i = 0; i < 8; i++) {
      corner.set(i & 1 ? box.max.x : box.min.x, i & 2 ? box.max.y : box.min.y, i & 4 ? box.max.z : box.min.z).applyMatrix4(child.matrixWorld).project(camera);
      const px = (corner.x * 0.5 + 0.5) * width, py = (corner.y * 0.5 + 0.5) * height;
      x0 = Math.min(x0, px); x1 = Math.max(x1, px);
      y0 = Math.min(y0, py); y1 = Math.max(y1, py);
    }
  }
  const x = Math.max(Math.floor(x0) - 2, 0), y = Math.max(Math.floor(y0) - 2, 0);
  return { x, y, w: Math.min(Math.ceil(x1) + 2, width) - x, h: Math.min(Math.ceil(y1) + 2, height) - y };
}

export function computeLabels(world: World, camera: THREE.Camera, width: number, height: number, seed: number, image: string): SceneLabels {
  const { renderer, scene, pieces } = world;
  const target = new THREE.WebGLRenderTarget(width, height, { depthBuffer: true });
  const background = scene.background;
  const hidden = scene.children.filter((c) => c.visible && c !== world.pieceRoot);
  const originals = new Map<THREE.Mesh, THREE.Material | THREE.Material[]>();
  scene.background = null;
  for (const c of hidden) c.visible = false;
  for (const p of pieces)
    for (const child of p.object.children as THREE.Mesh[]) {
      originals.set(child, child.material);
      child.material = idMaterial(p.id);
    }
  const clear = renderer.getClearAlpha();
  renderer.setClearColor(0x000000, 0);
  renderer.setRenderTarget(target);

  // Pass 1: everything together -> what the camera actually sees of each piece.
  renderer.render(scene, camera);
  const all = new Uint8Array(width * height * 4);
  renderer.readRenderTargetPixels(target, 0, 0, width, height, all);
  const seen = new Map<number, { n: number; x0: number; y0: number; x1: number; y1: number }>();
  for (let y = 0, i = 0; y < height; y++)
    for (let x = 0; x < width; x++, i += 4) {
      const id = all[i] | (all[i + 1] << 8);
      if (!id) continue;
      const s = seen.get(id);
      if (!s) seen.set(id, { n: 1, x0: x, y0: y, x1: x, y1: y });
      else {
        s.n++;
        if (x < s.x0) s.x0 = x;
        if (x > s.x1) s.x1 = x;
        if (y > s.y1) s.y1 = y; // rows only ever increase
      }
    }

  // Pass 2: each partly covered candidate alone -> its full silhouette.
  for (const p of pieces) p.object.visible = false;
  const labels: PieceLabel[] = pieces.map((p) => {
    const s = seen.get(p.id);
    let full = s?.n ?? 0;
    const rect = projectedRect(p, camera, width, height);
    if (rect.w > 0 && rect.h > 0) {
      p.object.visible = true;
      renderer.render(scene, camera);
      p.object.visible = false;
      const solo = new Uint8Array(rect.w * rect.h * 4);
      renderer.readRenderTargetPixels(target, rect.x, rect.y, rect.w, rect.h, solo);
      full = 0;
      for (let i = 0; i < solo.length; i += 4) if (solo[i] | solo[i + 1]) full++;
    }
    return {
      id: p.id,
      part: p.type.id,
      name: p.type.name,
      colour: p.colour.code,
      colour_name: p.colour.name,
      hex: p.colour.hex,
      // The render target's rows start at the bottom; images start at the top.
      bbox: s ? { x: s.x0 / width, y: (height - 1 - s.y1) / height, w: (s.x1 - s.x0 + 1) / width, h: (s.y1 - s.y0 + 1) / height } : null,
      pixels: s?.n ?? 0,
      visible: full ? Math.min((s?.n ?? 0) / full, 1) : 0,
    };
  });

  for (const p of pieces) p.object.visible = true;
  for (const [mesh, material] of originals) mesh.material = material;
  for (const c of hidden) c.visible = true;
  scene.background = background;
  renderer.setRenderTarget(null);
  renderer.setClearColor(0x000000, clear);
  target.dispose();

  const inventory = new Map<string, SceneLabels["inventory"][number]>();
  for (const l of labels) {
    const key = `${l.part}/${l.hex}`;
    const row = inventory.get(key) ?? { part: l.part, name: l.name, colour: l.colour, hex: l.hex, count: 0, visible_count: 0 };
    row.count++;
    if (l.visible >= VISIBLE_MIN) row.visible_count++;
    inventory.set(key, row);
  }
  return { image, width, height, seed, visible_min: VISIBLE_MIN, pieces: labels, inventory: [...inventory.values()].sort((a, b) => b.count - a.count) };
}
