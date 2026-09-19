"use client";

import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { ContactShadows, OrbitControls } from "@react-three/drei";
import { forwardRef, useEffect, useEffectEvent, useImperativeHandle, useRef, useState } from "react";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { prepareModel, type PreparedModel } from "@/lib/ldraw";
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
  interactive?: boolean;
  shadow?: boolean;
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
  const { className, mode, interactive = true } = props;
  const controls = useRef<OrbitControlsImpl | null>(null);
  const rig = useRef<Rig | null>(null);
  useImperativeHandle(ref, () => ({ resetView: () => rig.current?.snapCamera() }), []);

  return (
    <Canvas
      className={className}
      dpr={[1, 2]}
      gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
      camera={{ fov: mode === "steps" ? 20 : 28, near: 0.05, far: 2000, position: [-8, 6, 9] }}
      style={{ touchAction: "none" }}
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
  private dragging = false;
  private resumeAt = 0;

  constructor(readonly model: PreparedModel) {
    this.turntable.add(model.root);
    const q = new THREE.Quaternion();
    for (const p of model.parts) {
      p.object.parent!.getWorldQuaternion(q);
      this.lifts.set(p.object, new THREE.Vector3(0, DROP_LDU, 0).applyQuaternion(q.invert()));
    }
  }

  apply(mode: ViewMode, step: number) {
    const fresh: PreparedModel["parts"] = [];
    this.selection.length = 0;
    for (const p of this.model.parts) {
      p.object.position.copy(p.home);
      const future = p.step > step;
      if (mode === "steps") {
        p.object.visible = !future;
        this.setGhost(p.object, false);
        if (p.step === step) {
          fresh.push(p);
          this.selection.push(...p.meshes);
        }
      } else {
        p.object.visible = true;
        this.setGhost(p.object, mode === "timeline" && future);
      }
    }
    this.drop = { start: performance.now(), parts: fresh };
  }

  /** Whole model for display/timeline; placed-so-far (biased to new parts) for steps. */
  frame(mode: ViewMode, step: number, camera: THREE.PerspectiveCamera) {
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
    this.goal.target.copy(sphere.center);
    if (!fresh.isEmpty()) this.goal.target.lerp(fresh.getCenter(new THREE.Vector3()), 0.35);
    const fov = THREE.MathUtils.degToRad(camera.fov);
    const fit = Math.min(fov, 2 * Math.atan(Math.tan(fov / 2) * camera.aspect));
    const margin = mode === "steps" ? 0.92 : mode === "timeline" ? 1.0 : 0.95;
    this.goal.dist = (sphere.radius / Math.sin(fit / 2)) * margin;
  }

  snapCamera() {
    this.goal.snap = true;
  }

  dragStart() {
    this.dragging = true;
  }

  dragEnd() {
    this.dragging = false;
    this.resumeAt = performance.now() + 1800;
  }

  tick(dt: number, mode: ViewMode, spin: number, camera: THREE.Camera, controls: OrbitControlsImpl) {
    const step = Math.min(dt, 0.05);
    if (mode !== "steps" && !this.dragging && performance.now() > this.resumeAt) this.turntable.rotation.y += spin * step;

    const t = Math.min(1, (performance.now() - this.drop.start) / DROP_MS);
    const ease = 1 - Math.pow(1 - t, 3);
    for (const p of this.drop.parts) p.object.position.copy(p.home).addScaledVector(this.lifts.get(p.object)!, 1 - ease);

    const g = this.goal;
    const offset = camera.position.clone().sub(controls.target);
    if (g.snap) {
      controls.target.copy(g.target);
      offset.copy(ISO).multiplyScalar(g.dist);
      g.snap = false;
    } else {
      const k = 1 - Math.pow(0.001, step);
      controls.target.lerp(g.target, k);
      offset.setLength(THREE.MathUtils.lerp(offset.length(), g.dist, k));
    }
    camera.position.copy(controls.target).add(offset);
    controls.update();
  }

  dispose() {
    this.ghost.dispose();
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

function Scene({ url, mode, step = 0, spin = 0.15, shadow, onLoaded, onError, controls, rig }: SceneProps) {
  const [loaded, setLoaded] = useState<{ turntable: THREE.Group; shadowScale: number } | null>(null);
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera;
  const aspect = useThree((s) => s.size.width / Math.max(1, s.size.height));
  const loadedEvent = useEffectEvent((m: PreparedModel) => onLoaded?.(m));
  const errorEvent = useEffectEvent((e: unknown) => onError?.(e));

  useEffect(() => {
    let alive = true;
    prepareModel(url).then(
      (m) => {
        if (!alive) return;
        const r = new Rig(m);
        rig.current = r;
        setLoaded({ turntable: r.turntable, shadowScale: Math.max(8, m.box.getSize(new THREE.Vector3()).length() * 1.6) });
        loadedEvent(m);
      },
      (e) => alive && errorEvent(e),
    );
    return () => {
      alive = false;
      rig.current?.dispose();
      rig.current = null;
    };
  }, [url, rig]);

  useEffect(() => {
    const r = rig.current;
    if (!r) return;
    r.apply(mode, step);
    r.frame(mode, step, camera);
  }, [loaded, mode, step, camera, aspect, rig]);

  useEffect(() => {
    const c = controls.current;
    if (!c || !loaded) return;
    const start = () => rig.current?.dragStart();
    const end = () => rig.current?.dragEnd();
    c.addEventListener("start", start);
    c.addEventListener("end", end);
    return () => {
      c.removeEventListener("start", start);
      c.removeEventListener("end", end);
    };
  }, [controls, loaded, rig]);

  useFrame((state, dt) => {
    const c = controls.current;
    if (rig.current && c) rig.current.tick(dt, mode, spin, state.camera, c);
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
