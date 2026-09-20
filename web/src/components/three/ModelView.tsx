"use client";

import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { ContactShadows, OrbitControls } from "@react-three/drei";
import { forwardRef, useEffect, useEffectEvent, useImperativeHandle, useRef, useState } from "react";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { prepareModel, type PreparedModel } from "@/lib/ldraw";
import { play } from "@/lib/sound";
import { StudioEnvironment } from "./StudioEnvironment";

export type ViewMode = "display" | "steps" | "timeline";

export interface ModelViewHandle {
  resetView: () => void;
  /** Camera azimuth minus the turntable angle: what "left" means on screen. */
  viewAngle: () => number;
}

/** A pending edit drawn as translucent clones, in LDraw model coordinates. */
export interface EditGhost {
  /** PartNode indices whose meshes are cloned for the ghost. */
  lines: number[];
  placements: { line: number; origin: [number, number, number]; matrix: number[] }[];
  /** null = waiting for the dry run; true = green; false = red. */
  valid: boolean | null;
}

export interface EditProps {
  enabled: boolean;
  /** Lines outlined in the HIGHLIGHT purple. */
  selected: number[];
  /** Same purple, pulsing: "tap the one you mean". */
  candidates?: number[];
  /** Outlined in the joint red: what an edit would have broken. */
  culprits?: number[];
  ghost?: EditGhost | null;
  onPick?: (line: number | null, mods: { additive: boolean; body: boolean }) => void;
  /** [dx, dz] in whole studs along the model's own axes. */
  onDrag?: (phase: "start" | "move" | "end" | "cancel", d: [number, number]) => void;
  stability?: { com: [number, number]; base: [number, number][]; ground: number; stable: boolean } | null;
}

type Props = {
  url: string;
  mode: ViewMode;
  /** Current step index (steps / timeline modes); -1 ghosts everything in timeline. */
  step?: number;
  /** Continuous turntable rotation in rad/s (display mode). */
  spin?: number;
  /** Show a connection node on every placed brick (the physics joints). */
  joints?: boolean;
  /** Indices of bricks the physics couldn't hold — drawn red. */
  broken?: number[];
  interactive?: boolean;
  shadow?: boolean;
  /** Framing multiplier: above 1 pushes in, so a preview can overflow and clip its card. */
  zoom?: number;
  /** Fixed turntable angle in radians (with spin 0): for rendering set views. */
  yaw?: number;
  /** false pauses animation (one still frame stays up), for previews scrolled out of view. */
  active?: boolean;
  /** Picking, dragging and ghosts. Absent = today's behaviour, untouched. */
  edit?: EditProps;
  /** Keep camera and turntable when `url` changes (an edit landed). */
  preserveView?: boolean;
  /** Parts already on screen from the previous version of a model that is still
   *  being written: everything after them drops in, and the camera eases to the
   *  new size instead of snapping to it. */
  landed?: number;
  onLoaded?: (model: PreparedModel) => void;
  onError?: (err: unknown) => void;
  className?: string;
};

const HIGHLIGHT = 0x9840b0;
const CULPRIT = 0xf83b3b;
const GHOST_OK = 0x2fd66f;
/** How long a rejected ghost takes to ease back onto the real part. */
const SPRING_MS = 180;
/** A tap: within this many pixels and milliseconds of the pointer going down. */
const TAP_PX = 6;
const TAP_MS = 300;
const HOLD_MS = 450;
const DROP_MS = 260;
const DROP_LDU = 40;
const ISO = new THREE.Vector3(-1.35, 1.0, 1.55).normalize();
const OUTLINE_LAYER = 7;

/** One WebGL canvas that renders a prepared LDraw model in either look. */
export const ModelView = forwardRef<ModelViewHandle, Props>(function ModelView(props, ref) {
  const { className, mode, interactive = true, active = true } = props;
  const controls = useRef<OrbitControlsImpl | null>(null);
  const rig = useRef<Rig | null>(null);
  useImperativeHandle(
    ref,
    () => ({
      resetView: () => rig.current?.snapCamera(),
      viewAngle: () => (controls.current?.getAzimuthalAngle() ?? 0) - (rig.current?.yaw ?? 0),
    }),
    [],
  );

  return (
    <Canvas
      className={className}
      dpr={[1, 1.5]}
      frameloop={active && mode !== "steps" ? "always" : "demand"}
      gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
      camera={{ fov: mode === "steps" ? 20 : 28, near: 0.05, far: 2000, position: [-8, 6, 9] }}
      style={{ touchAction: interactive ? "none" : "auto" }}
    >
      <StudioEnvironment />
      <directionalLight position={[-6, 12, 8]} intensity={1.1} />
      <ambientLight intensity={0.15} />
      <Scene {...props} controls={controls} rig={rig} />
      <OrbitControls ref={controls} makeDefault enabled={interactive} enablePan={false} enableDamping dampingFactor={0.12} rotateSpeed={0.7} minPolarAngle={0.15} maxPolarAngle={mode === "steps" ? Math.PI - 0.15 : Math.PI / 2 - 0.04} />
    </Canvas>
  );
});

/**
 * Imperative state for one loaded model: visibility per step, ghosting, the
 * drop-in animation, turntable and camera framing. React only feeds it props.
 */
class Rig {
  readonly turntable = new THREE.Group();
  readonly selection: THREE.Object3D[] = [];
  /** Edit mode's three outline groups (selected / tap-one-of-these / broke it). */
  readonly editSelection: THREE.Object3D[] = [];
  readonly candidateSel: THREE.Object3D[] = [];
  readonly culpritSel: THREE.Object3D[] = [];
  /** Every pickable mesh, and which part line it belongs to. */
  readonly pickables: THREE.Mesh[] = [];
  readonly lineOfMesh = new Map<THREE.Object3D, number>();
  /** The group whose local coordinates ARE LDraw model coordinates. */
  private readonly ldrFrame: THREE.Object3D;
  private readonly ghostGroup = new THREE.Group();
  private readonly stabilityGroup = new THREE.Group();
  private ghostKey = "";
  private ghostClones: { line: number; object: THREE.Object3D }[] = [];
  private spring: { start: number; from: THREE.Matrix4; to: THREE.Matrix4; object: THREE.Object3D }[] = [];
  private readonly ghostMats = {
    idle: new THREE.MeshBasicMaterial({ color: 0xf4f4f4, transparent: true, opacity: 0.45, depthWrite: false }),
    ok: new THREE.MeshBasicMaterial({ color: GHOST_OK, transparent: true, opacity: 0.5, depthWrite: false }),
    bad: new THREE.MeshBasicMaterial({ color: CULPRIT, transparent: true, opacity: 0.5, depthWrite: false }),
  };
  private readonly ghost = new THREE.MeshBasicMaterial({ color: 0xf4f4f4, transparent: true, opacity: 0.38, depthWrite: true });
  private readonly lifts = new Map<THREE.Object3D, THREE.Vector3>();
  private drop = { start: 0, parts: [] as PreparedModel["parts"] };
  private goal = { target: new THREE.Vector3(), dist: 10, snap: true };
  private landed = 0;
  private dragging = false;
  private resumeAt = 0;

  // joint markers: one glowing node per brick, at the seam where it connects.
  readonly jointGroup = new THREE.Group();
  private markers: (THREE.Mesh | null)[] = [];
  private showJoints = false;
  private broken = new Set<number>();
  private readonly markerGeo = new THREE.SphereGeometry(1, 14, 14);
  private readonly greenMat = new THREE.MeshBasicMaterial({ color: GHOST_OK, transparent: true, opacity: 0.95 });
  private readonly redMat = new THREE.MeshBasicMaterial({ color: CULPRIT });
  private readonly lineOk = new THREE.LineBasicMaterial({ color: GHOST_OK });
  private readonly lineBad = new THREE.LineBasicMaterial({ color: CULPRIT });
  private stabilityGeo: THREE.BufferGeometry | null = null;
  private stabilityKey = "";

  constructor(readonly model: PreparedModel) {
    this.turntable.add(model.root);
    this.turntable.add(this.jointGroup);
    const q = new THREE.Quaternion();
    for (const p of model.parts) {
      p.object.parent!.getWorldQuaternion(q);
      this.lifts.set(p.object, new THREE.Vector3(0, DROP_LDU, 0).applyQuaternion(q.invert()));
    }
    // prepareModel puts exactly one child under root: the model group, whose
    // children sit at their LDraw coordinates. Ghosts and the stability
    // overlay live there, so the server's numbers can be used as they come.
    this.ldrFrame = model.root.children[0] ?? model.root;
    this.ldrFrame.add(this.ghostGroup);
    this.ldrFrame.add(this.stabilityGroup);
    model.parts.forEach((p, line) => {
      for (const mesh of p.meshes) {
        this.pickables.push(mesh);
        this.lineOfMesh.set(mesh, line);
      }
    });
    this.buildMarkers();
  }

  get yaw() {
    return this.turntable.rotation.y;
  }

  /** Carry the previous version's turntable angle and ease (never snap) to the new framing. */
  preserveFrom(yaw: number) {
    this.turntable.rotation.y = yaw;
    this.goal.snap = false;
  }

  /** Which meshes each outline pass draws around. */
  setEditSelection(selected: number[], candidates: number[], culprits: number[]) {
    const fill = (into: THREE.Object3D[], lines: number[]) => {
      into.length = 0;
      for (const line of lines) {
        const part = this.model.parts[line];
        if (part) into.push(...part.meshes);
      }
    };
    fill(this.editSelection, selected);
    fill(this.candidateSel, candidates);
    fill(this.culpritSel, culprits);
  }

  /** The base polygon and centre of mass, drawn on the ground in LDraw units. */
  setStability(s: EditProps["stability"] | undefined | null) {
    const key = s ? `${s.stable}|${s.ground}|${s.com.join(",")}|${s.base.map((p) => p.join(",")).join(";")}` : "";
    if (key === this.stabilityKey) return;
    this.stabilityKey = key;
    this.stabilityGroup.clear();
    this.stabilityGeo?.dispose();
    this.stabilityGeo = null;
    if (!s || s.base.length < 3) return;
    const points = s.base.map(([x, z]) => new THREE.Vector3(x * 20, s.ground, z * 20));
    points.push(points[0].clone());
    this.stabilityGeo = new THREE.BufferGeometry().setFromPoints(points);
    const loop = new THREE.Line(this.stabilityGeo, s.stable ? this.lineOk : this.lineBad);
    loop.renderOrder = 5;
    this.stabilityGroup.add(loop);
    const dot = new THREE.Mesh(this.markerGeo, s.stable ? this.greenMat : this.redMat);
    dot.scale.setScalar(10);
    dot.position.set(s.com[0] * 20, s.ground, s.com[1] * 20);
    dot.renderOrder = 5;
    this.stabilityGroup.add(dot);
    this.wake(300);
  }

  /**
   * Translucent copies of the parts an edit would move, where the server says
   * they would land. The real parts never move until an edit is accepted; a
   * rejected ghost eases back onto them and disappears.
   */
  setEditGhost(ghost: EditGhost | null | undefined) {
    const key = ghost ? ghost.lines.join(",") : "";
    if (!ghost) {
      if (this.ghostClones.length) {
        const now = performance.now();
        this.spring = this.ghostClones.map(({ line, object }) => ({ start: now, object, from: object.matrix.clone(), to: this.homeMatrix(line) }));
        this.ghostClones = [];
        this.wake(SPRING_MS + 60);
      }
      this.ghostKey = "";
      return;
    }
    if (key !== this.ghostKey) {
      this.clearGhost();
      this.ghostKey = key;
      for (const line of ghost.lines) {
        const part = this.model.parts[line];
        if (!part) continue;
        const clone = part.object.clone(true);
        clone.matrixAutoUpdate = false;
        clone.matrix.copy(this.homeMatrix(line));
        clone.renderOrder = 3;
        this.ghostGroup.add(clone);
        this.ghostClones.push({ line, object: clone });
      }
    }
    const material = ghost.valid === null ? this.ghostMats.idle : ghost.valid ? this.ghostMats.ok : this.ghostMats.bad;
    const place = new Map(ghost.placements.map((p) => [p.line, p]));
    for (const { line, object } of this.ghostClones) {
      const p = place.get(line);
      if (p) object.matrix.copy(ldrMatrix(p.origin, p.matrix));
      object.traverse((c) => {
        const any = c as THREE.Mesh;
        if (any.isMesh) any.material = material;
        else if ((c as THREE.LineSegments).isLineSegments) c.visible = false;
      });
    }
    this.wake(400);
  }

  private clearGhost() {
    for (const { object } of this.ghostClones) this.ghostGroup.remove(object);
    this.ghostClones = [];
    for (const s of this.spring) this.ghostGroup.remove(s.object);
    this.spring = [];
  }

  /** Where part `line` actually is, as a matrix in the LDraw frame. */
  private homeMatrix(line: number) {
    const part = this.model.parts[line];
    const m = new THREE.Matrix4();
    if (!part) return m;
    this.ldrFrame.updateMatrixWorld(true);
    part.object.updateMatrixWorld(true);
    return m.copy(this.ldrFrame.matrixWorld).invert().multiply(part.object.matrixWorld);
  }

  /** Eases a rejected ghost back onto the real part, then drops it. */
  private tickSpring(now: number) {
    if (!this.spring.length) return;
    const from = new THREE.Vector3();
    const to = new THREE.Vector3();
    const qa = new THREE.Quaternion();
    const qb = new THREE.Quaternion();
    const sa = new THREE.Vector3();
    const sb = new THREE.Vector3();
    this.spring = this.spring.filter((s) => {
      const t = Math.min(1, (now - s.start) / SPRING_MS);
      const ease = 1 - Math.pow(1 - t, 3);
      s.from.decompose(from, qa, sa);
      s.to.decompose(to, qb, sb);
      s.object.matrix.compose(from.lerp(to, ease), qa.slerp(qb, ease), sa.lerp(sb, ease));
      if (t < 1) return true;
      this.ghostGroup.remove(s.object);
      return false;
    });
  }

  /** A node hovering at each brick's connection seam. Fail-safe: any error just
   * leaves the joints layer empty, the model still renders. */
  private buildMarkers() {
    try {
      this.model.root.updateMatrixWorld(true);
      this.turntable.updateMatrixWorld(true);
      const r = THREE.MathUtils.clamp(this.model.box.getSize(new THREE.Vector3()).length() * 0.004, 0.9, 1.7);
      this.markers = this.model.parts.map((p) => {
        const box = new THREE.Box3().setFromObject(p.object);
        if (box.isEmpty()) return null;
        const c = box.getCenter(new THREE.Vector3());
        const mesh = new THREE.Mesh(this.markerGeo, this.greenMat);
        mesh.scale.setScalar(r);
        // a small bright node sitting on top of each brick (its stud/joint)
        mesh.position.copy(this.turntable.worldToLocal(new THREE.Vector3(c.x, box.max.y, c.z)));
        mesh.visible = false;
        mesh.renderOrder = 4;
        this.jointGroup.add(mesh);
        return mesh;
      });
    } catch {
      this.markers = [];
    }
  }

  setJoints(on: boolean, broken: number[]) {
    this.showJoints = on;
    this.broken = new Set(broken);
  }

  /** Returns how many parts drop in (for the landing sound). */
  /** How much of this model was already on screen a moment ago (a growing draft). */
  setLanded(n: number) {
    this.landed = n;
  }

  /** Where the camera is looking, to hand to the next version of a model that
   *  is still being written: it should not move while bricks are added. */
  snapshot() {
    return { target: this.goal.target.clone(), dist: this.goal.dist, yaw: this.turntable.rotation.y };
  }

  restore(s: { target: THREE.Vector3; dist: number; yaw: number }) {
    this.goal.target.copy(s.target);
    this.goal.dist = s.dist;
    this.goal.snap = true; // exactly where it was: no cut, because nothing moved
    this.turntable.rotation.y = s.yaw;
  }

  apply(mode: ViewMode, step: number) {
    const fresh: PreparedModel["parts"] = [];
    this.selection.length = 0;
    this.model.parts.forEach((p, i) => {
      p.object.position.copy(p.home);
      const future = p.step > step;
      let placed: boolean;
      if (mode === "steps") {
        placed = !future;
        p.object.visible = placed;
        this.setGhost(p.object, false);
        if (p.step === step) {
          fresh.push(p);
          this.selection.push(...p.meshes);
        }
      } else {
        p.object.visible = true;
        const ghosted = mode === "timeline" && future;
        this.setGhost(p.object, ghosted);
        placed = !ghosted;
        // a draft that just grew: the pieces it gained drop into place
        if (this.landed > 0 && i >= this.landed) fresh.push(p);
      }
      const marker = this.markers[i];
      if (marker) {
        marker.visible = this.showJoints && placed;
        marker.material = this.broken.has(i) ? this.redMat : this.greenMat;
      }
    });
    this.drop = { start: performance.now(), parts: fresh };
    return fresh.length;
  }

  /** Whole model for display/timeline; placed-so-far (biased to new parts) for steps. */
  frame(mode: ViewMode, step: number, camera: THREE.PerspectiveCamera, zoom = 1, onlyIfOutgrown = false) {
    this.turntable.rotation.y = mode === "steps" ? 0 : this.turntable.rotation.y;
    this.model.root.updateMatrixWorld(true);
    const box = new THREE.Box3();
    const fresh = new THREE.Box3();
    for (const p of this.model.parts) {
      if (mode === "steps" && p.step > step) continue;
      box.expandByObject(p.object);
      if (mode === "steps" && p.step === step) fresh.expandByObject(p.object);
    }
    if (box.isEmpty()) box.copy(this.model.box);
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    const target = sphere.center.clone();
    if (!fresh.isEmpty()) target.lerp(fresh.getCenter(new THREE.Vector3()), 0.35);
    this.goal.target.copy(target);
    const fov = THREE.MathUtils.degToRad(camera.fov);
    const fit = Math.min(fov, 2 * Math.atan(Math.tan(fov / 2) * camera.aspect));
    const margin = mode === "steps" ? 0.92 : mode === "timeline" ? 1.0 : 0.95;
    const dist = ((sphere.radius / Math.sin(fit / 2)) * margin) / zoom;
    if (onlyIfOutgrown) {
      // a model still being written: hold the view, and only give ground when
      // the build has outgrown it, easing rather than cutting
      if (dist <= this.goal.dist * 1.02) {
        this.goal.target.copy(target);
        return;
      }
      this.goal.snap = false;
    }
    this.goal.dist = dist;
  }

  /** Until when the scene still has motion to show (drop-in, camera ease). */
  busyUntil = 0;

  setYaw(radians: number) {
    this.turntable.rotation.y = radians;
  }

  snapCamera() {
    this.goal.snap = true;
    this.wake();
  }

  wake(ms = 1400) {
    this.busyUntil = Math.max(this.busyUntil, performance.now() + ms);
  }

  get busy() {
    return this.dragging || performance.now() < this.busyUntil;
  }

  dragStart() {
    this.dragging = true;
  }

  dragEnd() {
    this.dragging = false;
    this.resumeAt = performance.now() + 1800;
    this.wake(800); // let the orbit damping settle
  }

  /** `animate` false = a single still frame (paused preview): jump to the goal instead of easing. */
  tick(dt: number, mode: ViewMode, spin: number, camera: THREE.Camera, controls: OrbitControlsImpl, animate = true) {
    const step = Math.min(dt, 0.05);
    if (mode !== "steps" && !this.dragging && performance.now() > this.resumeAt) this.turntable.rotation.y += spin * step;

    const t = Math.min(1, (performance.now() - this.drop.start) / DROP_MS);
    const ease = 1 - Math.pow(1 - t, 3);
    for (const p of this.drop.parts) p.object.position.copy(p.home).addScaledVector(this.lifts.get(p.object)!, 1 - ease);
    this.tickSpring(performance.now());

    const g = this.goal;
    const offset = camera.position.clone().sub(controls.target);
    if (g.snap || !animate) {
      controls.target.copy(g.target);
      offset.copy(ISO).multiplyScalar(g.dist);
      g.snap = false;
    } else {
      const k = 1 - Math.pow(0.001, step);
      controls.target.lerp(g.target, k);
      offset.setLength(THREE.MathUtils.lerp(offset.length(), g.dist, k));
      // An exponential ease never quite arrives; land it, or every frame nudges
      // the camera a hair, fires "change", and the scene never goes idle.
      if (controls.target.distanceToSquared(g.target) < 1e-8) controls.target.copy(g.target);
      if (Math.abs(offset.length() - g.dist) < 1e-4) offset.setLength(g.dist);
    }
    camera.position.copy(controls.target).add(offset);
    controls.update();
  }

  dispose() {
    this.clearGhost();
    this.ghost.dispose();
    this.markerGeo.dispose();
    this.greenMat.dispose();
    this.redMat.dispose();
    this.lineOk.dispose();
    this.lineBad.dispose();
    this.stabilityGeo?.dispose();
    for (const m of Object.values(this.ghostMats)) m.dispose();
  }

  /** Swap a part between its real materials and the translucent ghost. */
  private setGhost(obj: THREE.Object3D, on: boolean) {
    obj.traverse((c) => {
      const any = c as THREE.Mesh | THREE.LineSegments;
      if (!("material" in any)) return;
      if (any.userData.realMaterial === undefined) any.userData.realMaterial = any.material;
      if ((any as THREE.Mesh).isMesh) {
        any.material = on ? this.ghost : any.userData.realMaterial;
        any.renderOrder = on ? 2 : 0;
      } else {
        any.visible = !on;
      }
    });
  }
}

/** An LDraw line's `x y z a b c … i` as a matrix in the model's own frame. */
function ldrMatrix(origin: [number, number, number], m: number[]) {
  return new THREE.Matrix4().set(m[0], m[1], m[2], origin[0], m[3], m[4], m[5], origin[1], m[6], m[7], m[8], origin[2], 0, 0, 0, 1);
}

type SceneProps = Props & {
  controls: React.RefObject<OrbitControlsImpl | null>;
  rig: React.RefObject<Rig | null>;
};

function Scene({ url, mode, step = 0, spin = 0.15, joints = false, broken, shadow, zoom = 1, yaw, active = true, interactive = true, edit, preserveView = false, landed = 0, onLoaded, onError, controls, rig }: SceneProps) {
  const [loaded, setLoaded] = useState<{ turntable: THREE.Group; shadowScale: number } | null>(null);
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera;
  const gl = useThree((s) => s.gl);
  const invalidate = useThree((s) => s.invalidate);
  const aspect = useThree((s) => s.size.width / Math.max(1, s.size.height));
  const loadedEvent = useEffectEvent((m: PreparedModel) => onLoaded?.(m));
  const errorEvent = useEffectEvent((e: unknown) => onError?.(e));
  /** Survives the model swap after an accepted edit, so the view doesn't jump. */
  const keptYaw = useRef(0);

  // a draft grows into a new model every few seconds: the camera and the
  // turntable carry over, so bricks appear without the view moving
  const carry = useRef<{ target: THREE.Vector3; dist: number; yaw: number } | null>(null);
  const growing = useRef(0);

  useEffect(() => {
    let alive = true;
    prepareModel(url).then(
      (m) => {
        if (!alive) return;
        const r = new Rig(m);
        if (growing.current > 0 && carry.current) r.restore(carry.current);
        else if (preserveView) r.preserveFrom(keptYaw.current);
        rig.current = r;
        setLoaded({ turntable: r.turntable, shadowScale: Math.max(8, m.box.getSize(new THREE.Vector3()).length() * 1.6) });
        loadedEvent(m);
      },
      (e) => alive && errorEvent(e),
    );
    return () => {
      alive = false;
      keptYaw.current = rig.current?.yaw ?? keptYaw.current;
      carry.current = rig.current?.snapshot() ?? carry.current;
      rig.current?.dispose();
      rig.current = null;
    };
    // preserveView is read at load time only: flipping it never reloads the model.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, rig]);

  const brokenKey = (broken ?? []).join(",");
  useEffect(() => {
    const r = rig.current;
    if (!r) return;
    growing.current = landed;
    if (yaw !== undefined) r.setYaw(yaw);
    r.setLanded(landed);
    r.setJoints(joints, brokenKey ? brokenKey.split(",").map(Number) : []);
    const landing = r.apply(mode, step);
    r.frame(mode, step, camera, zoom, landed > 0); // a growing draft keeps its framing
    r.wake();
    invalidate();
    if (mode !== "steps" || !landing) return;
    // The new parts snap home as the drop-in finishes: one soft click per step.
    const t = setTimeout(() => play("connect", { volume: 0.45 }), DROP_MS * 0.85);
    return () => clearTimeout(t);
  }, [loaded, mode, step, camera, rig, zoom, yaw, invalidate, joints, brokenKey, landed]);

  useEffect(() => {
    const r = rig.current;
    if (!r) return;
    r.frame(mode, step, camera, zoom);
    r.wake();
    invalidate();
  }, [aspect, mode, step, camera, rig, zoom, invalidate]);

  // --- edit mode ------------------------------------------------------------
  const editing = !!edit?.enabled;
  const selKey = (edit?.selected ?? []).join(",");
  const markKey = `${(edit?.candidates ?? []).join(",")}|${(edit?.culprits ?? []).join(",")}`;
  const ghostKey = edit?.ghost ? `${edit.ghost.lines.join(",")}|${edit.ghost.valid}|${edit.ghost.placements.map((p) => `${p.line}:${p.origin.join(",")}:${p.matrix.join(",")}`).join(";")}` : "";
  const stabKey = editing && edit?.stability ? JSON.stringify(edit.stability) : "";

  const syncOutline = useEffectEvent(() => {
    rig.current?.setEditSelection(editing ? (edit?.selected ?? []) : [], editing ? (edit?.candidates ?? []) : [], editing ? (edit?.culprits ?? []) : []);
    invalidate();
  });
  const syncGhost = useEffectEvent(() => {
    rig.current?.setEditGhost(editing ? (edit?.ghost ?? null) : null);
    invalidate();
  });
  const syncStability = useEffectEvent(() => {
    rig.current?.setStability(editing ? (edit?.stability ?? null) : null);
    invalidate();
  });

  useEffect(() => syncOutline(), [loaded, editing, selKey, markKey]);
  useEffect(() => syncGhost(), [loaded, editing, ghostKey]);
  useEffect(() => syncStability(), [loaded, editing, stabKey]);

  const pickEvent = useEffectEvent((line: number | null, mods: { additive: boolean; body: boolean }) => edit?.onPick?.(line, mods));
  const dragEvent = useEffectEvent((phase: "start" | "move" | "end" | "cancel", d: [number, number]) => edit?.onDrag?.(phase, d));
  const isSelected = useEffectEvent((line: number) => !!edit?.selected.includes(line));

  /**
   * Tap to select, double tap for the whole body, hold to add to the selection,
   * and drag a selected brick across the stud grid. OrbitControls only gives up
   * the gesture when it starts on something already selected.
   */
  useEffect(() => {
    const r = rig.current;
    const dom = gl.domElement;
    if (!editing || !loaded || !r) return;

    const raycaster = new THREE.Raycaster();
    const ndc = new THREE.Vector2();
    const plane = new THREE.Plane();
    const grabbed = new THREE.Vector3();
    const point = new THREE.Vector3();
    const local = new THREE.Vector3();
    const spin = new THREE.Quaternion();
    let down: { x: number; y: number; t: number; line: number | null; id: number } | null = null;
    let hold: ReturnType<typeof setTimeout> | null = null;
    let held = false;
    let dragging = false;
    let last: [number, number] = [0, 0];
    let tapped = { line: -1, at: 0 };

    const toNdc = (ev: PointerEvent) => {
      const rect = dom.getBoundingClientRect();
      ndc.set(((ev.clientX - rect.left) / rect.width) * 2 - 1, -((ev.clientY - rect.top) / rect.height) * 2 + 1);
      raycaster.setFromCamera(ndc, camera);
    };

    const hit = (ev: PointerEvent) => {
      toNdc(ev);
      for (const h of raycaster.intersectObjects(r.pickables, false)) {
        const line = r.lineOfMesh.get(h.object);
        if (line !== undefined && h.object.visible) {
          grabbed.copy(h.point);
          return line;
        }
      }
      return null;
    };

    const release = () => {
      if (controls.current) controls.current.enabled = interactive;
    };

    const onDown = (ev: PointerEvent) => {
      if (ev.button > 0) return;
      const line = hit(ev);
      down = { x: ev.clientX, y: ev.clientY, t: performance.now(), line, id: ev.pointerId };
      held = false;
      dragging = false;
      last = [0, 0];
      if (line !== null && isSelected(line)) {
        // Take the gesture from OrbitControls before it starts orbiting.
        if (controls.current) controls.current.enabled = false;
        plane.setFromNormalAndCoplanarPoint(new THREE.Vector3(0, 1, 0), grabbed);
      }
      if (line !== null)
        hold = setTimeout(() => {
          held = true; // a long press adds to the selection (phones have no shift key)
          pickEvent(line, { additive: true, body: false });
        }, HOLD_MS);
    };

    const onMove = (ev: PointerEvent) => {
      if (!down || ev.pointerId !== down.id) return;
      const far = Math.hypot(ev.clientX - down.x, ev.clientY - down.y) > TAP_PX;
      if (far && hold) {
        clearTimeout(hold);
        hold = null;
      }
      if (!far || held || down.line === null || !isSelected(down.line)) return;
      if (!dragging) {
        dragging = true;
        dragEvent("start", [0, 0]);
      }
      toNdc(ev);
      if (!raycaster.ray.intersectPlane(plane, point)) return;
      // World delta -> the model's own axes: undo the turntable, then LDraw's
      // flipped Z (prepareModel turns the model to stand up).
      local.subVectors(point, grabbed).applyQuaternion(r.turntable.getWorldQuaternion(spin).invert());
      const d: [number, number] = [Math.round(local.x), Math.round(-local.z)];
      if (d[0] === last[0] && d[1] === last[1]) return;
      last = d;
      dragEvent("move", d);
      play("drag");
    };

    const onUp = (ev: PointerEvent) => {
      if (!down || ev.pointerId !== down.id) return;
      if (hold) clearTimeout(hold);
      hold = null;
      release();
      const quick = performance.now() - down.t < TAP_MS && Math.hypot(ev.clientX - down.x, ev.clientY - down.y) <= TAP_PX;
      if (dragging) dragEvent("end", last);
      else if (!held && quick) {
        const now = performance.now();
        const again = down.line !== null && tapped.line === down.line && now - tapped.at < TAP_MS;
        tapped = { line: down.line ?? -1, at: now };
        pickEvent(down.line, { additive: ev.shiftKey || ev.ctrlKey || ev.metaKey, body: again });
      }
      down = null;
      dragging = false;
    };

    const onCancel = () => {
      if (hold) clearTimeout(hold);
      hold = null;
      release();
      if (dragging) dragEvent("cancel", [0, 0]);
      down = null;
      dragging = false;
    };

    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "Escape" && dragging) onCancel();
    };

    dom.addEventListener("pointerdown", onDown, true);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onCancel);
    window.addEventListener("keydown", onKey);
    return () => {
      if (hold) clearTimeout(hold);
      release();
      dom.removeEventListener("pointerdown", onDown, true);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onCancel);
      window.removeEventListener("keydown", onKey);
    };
  }, [editing, loaded, gl, camera, controls, rig, interactive]);

  useEffect(() => {
    const c = controls.current;
    if (!c || !loaded) return;
    // Turning the model by hand clicks like a turntable: one drag sound per
    // ~9 degrees swept, so faster spins give denser clicks.
    let dragging = false;
    let last = { az: 0, pol: 0 };
    let swept = 0;
    const start = () => {
      dragging = true;
      last = { az: c.getAzimuthalAngle(), pol: c.getPolarAngle() };
      swept = 0;
      rig.current?.dragStart();
    };
    const end = () => {
      dragging = false;
      rig.current?.dragEnd();
    };
    const change = () => {
      if (!dragging) return;
      const az = c.getAzimuthalAngle();
      const pol = c.getPolarAngle();
      let dAz = Math.abs(az - last.az);
      if (dAz > Math.PI) dAz = 2 * Math.PI - dAz;
      swept += dAz + Math.abs(pol - last.pol);
      last = { az, pol };
      if (swept > 0.16) {
        swept = 0;
        play("drag");
      }
    };
    c.addEventListener("start", start);
    c.addEventListener("end", end);
    c.addEventListener("change", change);
    return () => {
      c.removeEventListener("start", start);
      c.removeEventListener("end", end);
      c.removeEventListener("change", change);
    };
  }, [controls, loaded, rig]);

  useFrame((state, dt) => {
    const c = controls.current;
    const r = rig.current;
    if (!r || !c) return;
    r.tick(dt, mode, spin, state.camera, c, active);
    // On-demand scenes keep asking for frames only while something is moving
    // (drop-in, camera ease, a drag with damping); idle, they cost nothing.
    if (state.frameloop === "demand" && active && r.busy) invalidate();
  });

  if (!loaded) return null;
  return (
    <>
      <primitive object={loaded.turntable} />
      {shadow && <ContactShadows position={[0, -0.01, 0]} opacity={0.42} scale={loaded.shadowScale} blur={2.6} far={6} resolution={512} color="#3a3a3a" />}
      {(mode === "steps" || editing) && <SelectionOutline rig={rig} />}
    </>
  );
}

interface OutlineResources {
  target: THREE.WebGLRenderTarget;
  black: THREE.MeshBasicMaterial;
  white: THREE.MeshBasicMaterial;
  material: THREE.ShaderMaterial;
  overlay: THREE.Scene;
  ortho: THREE.OrthographicCamera;
  clear: THREE.Color;
}

function createOutline(): OutlineResources {
  const target = new THREE.WebGLRenderTarget(1, 1);
  const material = new THREE.ShaderMaterial({
    uniforms: { tMask: { value: target.texture }, texel: { value: new THREE.Vector2() }, radius: { value: 3 }, color: { value: new THREE.Color(HIGHLIGHT) }, alpha: { value: 1 } },
    vertexShader: "varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }",
    fragmentShader: `
      uniform sampler2D tMask; uniform vec2 texel; uniform float radius; uniform vec3 color; uniform float alpha; varying vec2 vUv;
      void main() {
        if (texture2D(tMask, vUv).r > 0.5) discard;
        float hit = 0.0;
        for (int i = 0; i < 24; i++) {
          float a = float(i) * 0.2617994;
          vec2 d = vec2(cos(a), sin(a)) * texel;
          for (int j = 1; j <= 3; j++) hit = max(hit, texture2D(tMask, vUv + d * radius * float(j) / 3.0).r);
        }
        if (hit < 0.5) discard;
        gl_FragColor = vec4(color, alpha);
        #include <colorspace_fragment>
      }`,
    depthTest: false,
    depthWrite: false,
    transparent: true,
  });
  const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), material);
  quad.frustumCulled = false;
  const overlay = new THREE.Scene();
  overlay.add(quad);
  return {
    target,
    black: new THREE.MeshBasicMaterial({ color: 0x000000 }),
    white: new THREE.MeshBasicMaterial({ color: 0xffffff }),
    material,
    overlay,
    ortho: new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1),
    clear: new THREE.Color(),
  };
}

/**
 * Crisp screen-space outline around the visible silhouette of the step's new
 * parts (the purple line in the reference): render a mask of the selection
 * depth-tested against the whole model, then dilate it over the frame.
 */
function SelectionOutline({ rig, px = 3.5 }: { rig: React.RefObject<Rig | null>; px?: number }) {
  const res = useRef<OutlineResources | null>(null);

  useEffect(() => {
    const r = createOutline();
    res.current = r;
    return () => {
      r.target.dispose();
      r.material.dispose();
      r.black.dispose();
      r.white.dispose();
      res.current = null;
    };
  }, []);

  useFrame(({ gl, scene, camera, size, clock }) => {
    gl.render(scene, camera);
    const r = res.current;
    const g = rig.current;
    if (!r || !g) return;
    // Steps mode outlines the step's new parts; edit mode outlines what is
    // selected, what the user is being asked to choose between (pulsing) and
    // what an edit would have broken (red).
    const passes = [
      { objects: g.selection.length ? g.selection : g.editSelection, colour: HIGHLIGHT, alpha: 1 },
      { objects: g.candidateSel, colour: HIGHLIGHT, alpha: 0.35 + 0.65 * (0.5 + 0.5 * Math.sin(clock.elapsedTime * 1.2 * Math.PI * 2)) },
      { objects: g.culpritSel, colour: CULPRIT, alpha: 1 },
    ].filter((p) => p.objects.length > 0);
    if (!passes.length) return;

    const dpr = gl.getPixelRatio();
    const w = Math.floor(size.width * dpr);
    const h = Math.floor(size.height * dpr);
    if (r.target.width !== w || r.target.height !== h) r.target.setSize(w, h);

    const alpha = gl.getClearAlpha();
    gl.getClearColor(r.clear);
    const auto = gl.autoClear;
    for (const pass of passes) {
      gl.setRenderTarget(r.target);
      gl.setClearColor(0x000000, 1);
      gl.autoClear = true;
      gl.clear();
      scene.overrideMaterial = r.black;
      gl.render(scene, camera);
      for (const m of pass.objects) m.layers.enable(OUTLINE_LAYER);
      camera.layers.set(OUTLINE_LAYER);
      scene.overrideMaterial = r.white;
      gl.autoClear = false;
      gl.render(scene, camera);
      camera.layers.set(0);
      for (const m of pass.objects) m.layers.disable(OUTLINE_LAYER);
      scene.overrideMaterial = null;
      gl.setRenderTarget(null);
      gl.setClearColor(r.clear, alpha);

      r.material.uniforms.texel.value.set(1 / w, 1 / h);
      r.material.uniforms.radius.value = px * dpr;
      r.material.uniforms.color.value.setHex(pass.colour);
      r.material.uniforms.alpha.value = pass.alpha;
      gl.render(r.overlay, r.ortho);
    }
    gl.autoClear = auto;
  }, 1);

  return null;
}
