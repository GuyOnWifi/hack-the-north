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
  /** Parts already on screen from the previous version of a model that is still
   *  being written: everything after them drops in, and the camera eases to the
   *  new size instead of snapping to it. */
  landed?: number;
  onLoaded?: (model: PreparedModel) => void;
  onError?: (err: unknown) => void;
  className?: string;
};

const HIGHLIGHT = 0x9840b0;
const DROP_MS = 260;
const DROP_LDU = 40;
const ISO = new THREE.Vector3(-1.35, 1.0, 1.55).normalize();
const OUTLINE_LAYER = 7;

/** One WebGL canvas that renders a prepared LDraw model in either look. */
export const ModelView = forwardRef<ModelViewHandle, Props>(function ModelView(props, ref) {
  const { className, mode, interactive = true, active = true } = props;
  const controls = useRef<OrbitControlsImpl | null>(null);
  const rig = useRef<Rig | null>(null);
  useImperativeHandle(ref, () => ({ resetView: () => rig.current?.snapCamera() }), []);

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
  private readonly greenMat = new THREE.MeshBasicMaterial({ color: 0x2fd66f, transparent: true, opacity: 0.95 });
  private readonly redMat = new THREE.MeshBasicMaterial({ color: 0xf83b3b });

  constructor(readonly model: PreparedModel) {
    this.turntable.add(model.root);
    this.turntable.add(this.jointGroup);
    const q = new THREE.Quaternion();
    for (const p of model.parts) {
      p.object.parent!.getWorldQuaternion(q);
      this.lifts.set(p.object, new THREE.Vector3(0, DROP_LDU, 0).applyQuaternion(q.invert()));
    }
    this.buildMarkers();
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
    this.ghost.dispose();
    this.markerGeo.dispose();
    this.greenMat.dispose();
    this.redMat.dispose();
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

type SceneProps = Props & {
  controls: React.RefObject<OrbitControlsImpl | null>;
  rig: React.RefObject<Rig | null>;
};

function Scene({ url, mode, step = 0, spin = 0.15, joints = false, broken, shadow, zoom = 1, yaw, active = true, landed = 0, onLoaded, onError, controls, rig }: SceneProps) {
  const [loaded, setLoaded] = useState<{ turntable: THREE.Group; shadowScale: number } | null>(null);
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera;
  const invalidate = useThree((s) => s.invalidate);
  const aspect = useThree((s) => s.size.width / Math.max(1, s.size.height));
  const loadedEvent = useEffectEvent((m: PreparedModel) => onLoaded?.(m));
  const errorEvent = useEffectEvent((e: unknown) => onError?.(e));

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
        rig.current = r;
        setLoaded({ turntable: r.turntable, shadowScale: Math.max(8, m.box.getSize(new THREE.Vector3()).length() * 1.6) });
        loadedEvent(m);
      },
      (e) => alive && errorEvent(e),
    );
    return () => {
      alive = false;
      carry.current = rig.current?.snapshot() ?? carry.current;
      rig.current?.dispose();
      rig.current = null;
    };
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
      {mode === "steps" && <SelectionOutline rig={rig} />}
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
    uniforms: { tMask: { value: target.texture }, texel: { value: new THREE.Vector2() }, radius: { value: 3 }, color: { value: new THREE.Color(HIGHLIGHT) } },
    vertexShader: "varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }",
    fragmentShader: `
      uniform sampler2D tMask; uniform vec2 texel; uniform float radius; uniform vec3 color; varying vec2 vUv;
      void main() {
        if (texture2D(tMask, vUv).r > 0.5) discard;
        float hit = 0.0;
        for (int i = 0; i < 24; i++) {
          float a = float(i) * 0.2617994;
          vec2 d = vec2(cos(a), sin(a)) * texel;
          for (int j = 1; j <= 3; j++) hit = max(hit, texture2D(tMask, vUv + d * radius * float(j) / 3.0).r);
        }
        if (hit < 0.5) discard;
        gl_FragColor = vec4(color, 1.0);
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

  useFrame(({ gl, scene, camera, size }) => {
    gl.render(scene, camera);
    const r = res.current;
    const selection = rig.current?.selection ?? [];
    if (!r || !selection.length) return;

    const dpr = gl.getPixelRatio();
    const w = Math.floor(size.width * dpr);
    const h = Math.floor(size.height * dpr);
    if (r.target.width !== w || r.target.height !== h) r.target.setSize(w, h);

    const alpha = gl.getClearAlpha();
    gl.getClearColor(r.clear);
    const auto = gl.autoClear;
    gl.setRenderTarget(r.target);
    gl.setClearColor(0x000000, 1);
    gl.clear();
    scene.overrideMaterial = r.black;
    gl.render(scene, camera);
    for (const m of selection) m.layers.enable(OUTLINE_LAYER);
    camera.layers.set(OUTLINE_LAYER);
    scene.overrideMaterial = r.white;
    gl.autoClear = false;
    gl.render(scene, camera);
    camera.layers.set(0);
    for (const m of selection) m.layers.disable(OUTLINE_LAYER);
    scene.overrideMaterial = null;
    gl.setRenderTarget(null);
    gl.setClearColor(r.clear, alpha);

    r.material.uniforms.texel.value.set(1 / w, 1 / h);
    r.material.uniforms.radius.value = px * dpr;
    gl.render(r.overlay, r.ortho);
    gl.autoClear = auto;
  }, 1);

  return null;
}
