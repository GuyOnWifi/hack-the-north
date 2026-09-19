import * as THREE from "three";
import RAPIER from "@dimforge/rapier3d-compat";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { buildPiece, type Colour, type PartType } from "./parts";
import type { Rng } from "./rng";

export interface Piece {
  /** 1-based, also the colour it is drawn with in the label pass. */
  id: number;
  type: PartType;
  colour: Colour;
  object: THREE.Group;
  body: RAPIER.RigidBody;
}

export type Phase = "idle" | "dropping" | "slumping" | "settled";

// The engine's resting and sleep tolerances assume gravity near 10 on objects about 1 unit big. Much more
// than this and resting pieces are kicked harder each step than the solver can cancel, so they never sleep.
const GRAVITY = -40;
const DT = 1 / 120;
const RIM_WIDTH = 2.6;
const RIM_HEIGHT = 1.1;
const WALL_SEGMENTS = 48;
/** Share of a spawn layer's area that pieces may cover; low enough that they never start interlocked. */
const LAYER_FILL = 0.32;
const FOV = 32;
/** Table tops a plate might sit on; the first is the studio default. */
const TABLES = ["#aeb6c0", "#d8d2c4", "#8a6f55", "#c9a67c", "#3c4148", "#e9ebee", "#6f8a7a", "#5b6b8c"];

await RAPIER.init();

export class World {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene = new THREE.Scene();
  readonly camera = new THREE.PerspectiveCamera(FOV, 1, 1, 2000);
  pieces: Piece[] = [];
  phase: Phase = "idle";
  plateRadius = 14;

  private physics = new RAPIER.World({ x: 0, y: GRAVITY, z: 0 });
  private wall: RAPIER.Collider[] = [];
  private plate: THREE.Mesh;
  private table: THREE.MeshStandardMaterial;
  private key: THREE.DirectionalLight;
  private steps = 0;
  private calm = 0;
  /** Set before a drop to vary the look of the scene; null keeps the studio default. */
  varyRng: Rng | null = null;
  private inset = { left: 0, width: 1, height: 1 };
  readonly pieceRoot = new THREE.Group();

  constructor(canvas: HTMLCanvasElement) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
    this.renderer.toneMapping = THREE.NeutralToneMapping; // keeps brick colours true; filmic curves wash them out
    this.renderer.toneMappingExposure = 1;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    this.scene.environmentIntensity = 0.4;
    this.scene.background = new THREE.Color(TABLES[0]);

    this.table = new THREE.MeshStandardMaterial({ color: TABLES[0], roughness: 0.95 });
    const table = new THREE.Mesh(new THREE.PlaneGeometry(4000, 4000), this.table);
    table.rotation.x = -Math.PI / 2;
    table.position.y = -0.35;
    table.receiveShadow = true;
    this.scene.add(table);

    this.plate = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshPhysicalMaterial({ color: "#f1f1ee", roughness: 0.4, clearcoat: 0.35, clearcoatRoughness: 0.2, side: THREE.DoubleSide }));
    this.plate.receiveShadow = true;
    this.plate.castShadow = true;
    this.scene.add(this.plate);

    this.key = new THREE.DirectionalLight("#ffffff", 2.2);
    this.key.castShadow = true;
    this.key.shadow.mapSize.set(4096, 4096);
    this.key.shadow.radius = 5;
    this.key.shadow.bias = -0.0004;
    this.key.shadow.normalBias = 0.03;
    this.scene.add(this.key, this.key.target);

    this.scene.add(this.pieceRoot);
    this.layoutPlate(this.plateRadius);
  }

  /** Rebuilds the plate, the light and the camera framing for a plate of inner radius `r`. */
  private layoutPlate(r: number) {
    this.plateRadius = r;
    const outer = r + RIM_WIDTH;
    const profile = [
      [0, 0], [r - 0.6, 0], [r + 0.5, 0.18], [outer - 0.3, RIM_HEIGHT - 0.06], [outer, RIM_HEIGHT], [outer + 0.12, RIM_HEIGHT - 0.12],
      [r + 0.9, -0.2], [r * 0.62, -0.35], [0, -0.35],
    ].map(([x, y]) => new THREE.Vector2(x, y));
    this.plate.geometry.dispose();
    this.plate.geometry = new THREE.LatheGeometry(profile, 128);

    const cam = this.key.shadow.camera;
    cam.left = cam.bottom = -outer * 1.15;
    cam.right = cam.top = outer * 1.15;
    cam.near = 1;
    cam.far = outer * 6;
    cam.updateProjectionMatrix();
    this.vary(this.varyRng);
    this.frame();
  }

  /** Points the camera straight down with the whole plate in view. `inset` (px) keeps the plate clear of an overlaid panel. */
  frame(inset = this.inset) {
    this.inset = inset;
    const free = Math.max(inset.width - inset.left, 1);
    const aspect = inset.width / inset.height;
    const fit = (this.plateRadius + RIM_WIDTH) * 1.1;
    const half = THREE.MathUtils.degToRad(FOV / 2);
    // The plate has to fit the free area to the right of the panel, in both directions.
    const needV = fit / Math.tan(half);
    const needH = (fit * (inset.width / free)) / (Math.tan(half) * aspect);
    const d = Math.max(needV, needH);
    this.camera.aspect = aspect;
    this.camera.position.set(0, d, 0);
    this.camera.up.set(0, 0, -1);
    this.camera.lookAt(0, 0, 0);
    this.camera.clearViewOffset();
    if (inset.left > 0) this.camera.setViewOffset(inset.width, inset.height, -inset.left / 2, 0, inset.width, inset.height);
    this.camera.updateProjectionMatrix();
  }

  private clear() {
    this.pieceRoot.clear();
    this.pieces = [];
    this.physics.free();
    this.physics = new RAPIER.World({ x: 0, y: GRAVITY, z: 0 });
    this.physics.timestep = DT;
    this.physics.numSolverIterations = 8;
    this.wall = [];
  }

  private buildPlateColliders(columnHeight: number) {
    const r = this.plateRadius;
    const fixed = this.physics.createRigidBody(RAPIER.RigidBodyDesc.fixed());
    this.physics.createCollider(RAPIER.ColliderDesc.cuboid(500, 5, 500).setTranslation(0, -5.35, 0).setFriction(0.7), fixed); // table
    this.physics.createCollider(RAPIER.ColliderDesc.cylinder(0.175, r + 0.6).setTranslation(0, -0.175, 0).setFriction(0.5), fixed); // plate base

    const slope = Math.atan2(RIM_HEIGHT, RIM_WIDTH);
    const rimLen = Math.hypot(RIM_WIDTH, RIM_HEIGHT);
    const segW = (2 * Math.PI * (r + RIM_WIDTH)) / WALL_SEGMENTS;
    for (let i = 0; i < WALL_SEGMENTS; i++) {
      const a = (i / WALL_SEGMENTS) * Math.PI * 2;
      const spin = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), -a);
      // Sloped rim the pieces can rest against.
      const mid = r + RIM_WIDTH / 2;
      const tilt = spin.clone().multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), slope));
      this.physics.createCollider(
        RAPIER.ColliderDesc.cuboid(rimLen / 2, 0.15, segW / 2 + 0.05).setTranslation(Math.cos(a) * mid, RIM_HEIGHT / 2 - 0.15, Math.sin(a) * mid).setRotation(tilt).setFriction(0.5),
        fixed,
      );
      // Invisible chute that keeps the falling column over the plate; removed once things calm down.
      const wr = r + 0.4;
      this.wall.push(
        this.physics.createCollider(
          RAPIER.ColliderDesc.cuboid(0.5, columnHeight / 2 + 10, segW / 2 + 0.3).setTranslation(Math.cos(a) * (wr + 0.5), columnHeight / 2, Math.sin(a) * (wr + 0.5)).setRotation(spin).setFriction(0.05),
          fixed,
        ),
      );
    }
  }

  /**
   * Drops `count` pieces. `crowding` is the share of the plate the pieces would cover lying flat:
   * ~0.3 leaves every piece in the clear, 1+ piles them up.
   */
  drop(types: PartType[], colours: Colour[], count: number, crowding: number, rng: Rng) {
    this.clear();
    // Every chosen kind appears before any repeats.
    const order = [...types].sort(() => rng.next() - 0.5);
    const picks = Array.from({ length: count }, (_, i) => ({ type: order[i % order.length], colour: rng.pick(colours) }));
    const area = picks.reduce((sum, p) => sum + p.type.footprint, 0);
    const longest = picks.reduce((m, p) => Math.max(m, p.type.size.length()), 0);
    this.layoutPlate(Math.max(8, longest * 0.75, Math.sqrt(area / (Math.PI * crowding))));

    // Stack the pieces in sparse layers above the plate so nothing starts out overlapping, then let it all go at once.
    const spawnR = this.plateRadius - 0.6;
    const budget = Math.PI * spawnR * spawnR * LAYER_FILL;
    const placed: { x: number; z: number; r: number }[] = [];
    let y = 3, used = 0, layerTall = 0;
    const spots = picks.map(({ type }) => {
      const rad = type.size.length() / 2;
      const cover = Math.PI * rad * rad;
      if (used + cover > budget && placed.length) {
        y += layerTall + 0.6;
        placed.length = 0;
        used = layerTall = 0;
      }
      let x = 0, z = 0;
      for (let attempt = 0; attempt < 40; attempt++) {
        const reach = Math.max(spawnR - rad, 0) * Math.sqrt(rng.next());
        const a = rng.range(0, Math.PI * 2);
        x = Math.cos(a) * reach;
        z = Math.sin(a) * reach;
        if (placed.every((p) => Math.hypot(p.x - x, p.z - z) > p.r + rad)) break;
      }
      placed.push({ x, z, r: rad });
      used += cover;
      layerTall = Math.max(layerTall, rad * 2);
      return { x, y: y + rad, z };
    });
    this.buildPlateColliders(y + layerTall);

    picks.forEach(({ type, colour }, i) => {
      const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(rng.range(0, 6.28), rng.range(0, 6.28), rng.range(0, 6.28)));
      const body = this.physics.createRigidBody(
        RAPIER.RigidBodyDesc.dynamic()
          .setTranslation(spots[i].x, spots[i].y, spots[i].z)
          .setRotation(q)
          .setLinvel(rng.range(-2, 2), -14, rng.range(-2, 2))
          .setAngvel({ x: rng.range(-5, 5), y: rng.range(-5, 5), z: rng.range(-5, 5) })
          .setLinearDamping(0.35)
          .setAngularDamping(1.6), // stands in for rolling resistance: domes and cylinders would otherwise roll forever
      );
      const shape = RAPIER.ColliderDesc.convexHull(type.hull) ?? RAPIER.ColliderDesc.cuboid(Math.max(type.size.x / 2, 0.05), Math.max(type.size.y / 2, 0.05), Math.max(type.size.z / 2, 0.05));
      this.physics.createCollider(shape.setFriction(0.55).setRestitution(0.1).setDensity(1), body);
      const object = buildPiece(type, colour);
      this.pieceRoot.add(object);
      this.pieces.push({ id: i + 1, type, colour, object, body });
    });
    this.steps = this.calm = 0;
    this.phase = "dropping";
    this.sync();
  }

  private isCalm() {
    for (const p of this.pieces) {
      if (p.body.isSleeping()) continue;
      const v = p.body.linvel(), w = p.body.angvel();
      if (v.x * v.x + v.y * v.y + v.z * v.z > 0.04 || w.x * w.x + w.y * w.y + w.z * w.z > 0.25) return false;
    }
    return true;
  }

  /** Advances the simulation by up to `n` steps; returns true once everything has come to rest. */
  advance(n: number) {
    for (let i = 0; i < n && (this.phase === "dropping" || this.phase === "slumping"); i++) {
      this.physics.step();
      this.steps++;
      this.calm = this.isCalm() ? this.calm + 1 : 0;
      const timeout = this.steps > (this.phase === "dropping" ? 6 : 2) / DT;
      if (this.calm < 30 && !timeout) continue;
      if (this.phase === "dropping") {
        // Take the chute away: anything leaning on it slumps onto the rim like it would in real life.
        for (const c of this.wall) this.physics.removeCollider(c, true);
        this.wall = [];
        for (const p of this.pieces) p.body.wakeUp();
        this.phase = "slumping";
        this.steps = this.calm = 0;
      } else {
        this.phase = "settled";
      }
    }
    this.sync();
    return this.phase === "settled";
  }

  private sync() {
    for (const p of this.pieces) {
      const t = p.body.translation(), r = p.body.rotation();
      p.object.position.set(t.x, t.y, t.z);
      p.object.quaternion.set(r.x, r.y, r.z, r.w);
    }
  }

  /** Steps to run per rendered frame. */
  static readonly STEPS_PER_FRAME = Math.round(1.5 / 60 / DT); // 1.5x real time: gentle gravity, brisk drop

  render() {
    this.renderer.render(this.scene, this.camera);
  }

  /**
   * A square camera over the plate: what a phone held above it would see. With `rng` the hand is
   * imperfect: a little tilt, a little off-centre, a little further away.
   */
  photoCamera(rng?: Rng) {
    const cam = new THREE.PerspectiveCamera(FOV, 1, 1, 2000);
    const d = (((this.plateRadius + RIM_WIDTH) * 1.06) / Math.tan(THREE.MathUtils.degToRad(FOV / 2))) * (rng ? rng.range(1, 1.18) : 1);
    const tilt = rng ? THREE.MathUtils.degToRad(rng.range(0, 9)) : 0;
    const around = rng ? rng.range(0, Math.PI * 2) : 0;
    cam.position.set(Math.sin(tilt) * Math.cos(around) * d, Math.cos(tilt) * d, Math.sin(tilt) * Math.sin(around) * d);
    const roll = rng ? rng.range(0, Math.PI * 2) : 0;
    cam.up.set(Math.sin(roll), 0, -Math.cos(roll));
    const drift = rng ? this.plateRadius * 0.05 : 0;
    cam.lookAt(rng ? rng.range(-drift, drift) : 0, 0, rng ? rng.range(-drift, drift) : 0);
    cam.updateMatrixWorld();
    return cam;
  }

  /** Changes the things a model should not rely on: light direction, strength and warmth, exposure, the table. */
  vary(rng: Rng | null) {
    const outer = this.plateRadius + RIM_WIDTH;
    const around = rng ? rng.range(0, Math.PI * 2) : 0.62;
    // Leaning light: a flat piece under a vertical light casts no shadow you can see, and looks pasted on.
    const lean = THREE.MathUtils.degToRad(rng ? rng.range(18, 48) : 32);
    this.key.position.set(Math.sin(lean) * Math.cos(around), Math.cos(lean), Math.sin(lean) * Math.sin(around)).multiplyScalar(outer * 3);
    this.key.intensity = rng ? rng.range(1.6, 2.8) : 2.2;
    this.key.color.setHSL(rng ? rng.pick([0.08, 0.1, 0.58]) : 0, rng ? rng.range(0, 0.25) : 0, 1 - (rng ? rng.range(0, 0.06) : 0));
    this.scene.environmentIntensity = rng ? rng.range(0.25, 0.55) : 0.4;
    this.renderer.toneMappingExposure = rng ? rng.range(0.85, 1.15) : 1;
    const table = rng ? rng.pick(TABLES) : TABLES[0];
    this.table.color.set(table);
    (this.scene.background as THREE.Color).set(table);
  }

  /** Renders a `size` x `size` photo and returns it as a data URL. The on-screen view is restored afterwards. */
  photo(size: number, camera: THREE.Camera, jpeg = false) {
    const before = this.renderer.getSize(new THREE.Vector2());
    const ratio = this.renderer.getPixelRatio();
    this.renderer.setPixelRatio(1);
    this.renderer.setSize(size, size, false);
    this.renderer.render(this.scene, camera);
    const image = jpeg ? this.renderer.domElement.toDataURL("image/jpeg", 0.93) : this.renderer.domElement.toDataURL("image/png");
    this.renderer.setPixelRatio(ratio);
    this.renderer.setSize(before.x, before.y, false);
    this.render();
    return image;
  }
}
