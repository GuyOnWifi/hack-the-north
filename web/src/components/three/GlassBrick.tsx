"use client";

import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Environment, Lightformer, MeshTransmissionMaterial } from "@react-three/drei";
import { useEffect, useEffectEvent, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { prepareModel, registerModelText } from "@/lib/ldraw";

// The hero: a real 2x4 brick (LDraw 3001, so true studs and the hollow, tubed
// underside) in smoked glass, turning slowly in front of glowing scan rings.
// The rings live inside the scene, not in the page, because glass can only
// bend what is rendered behind it: as the brick turns, the rings warp through it.

const BRICK_URL = registerModelText("glass-brick-3001", "1 0 0 0 0 1 0 0 0 1 0 0 0 1 3001.dat\n");
const BRICK_LENGTH = 4; // studs = world units once prepared
const RING_DEPTH = -2.6;

type Placement = {
  /** Centre, in viewport half-extents: [1, 0] is the middle of the right edge. */
  at: [number, number];
  /** Brick length, or ring diameter, in viewport heights. */
  size: number;
};

type Props = {
  className?: string;
  /** false pauses the animation (one still frame stays up). */
  active?: boolean;
  brick?: Placement;
  rings?: Placement;
  /** How much dimmer each ring gets going outward. */
  ringFade?: number;
  spin?: number;
  /** Fires once the brick is on screen (the rings show immediately). */
  onReady?: () => void;
};

export function GlassBrick({ className, active = true, brick = { at: [0, 0], size: 0.62 }, rings = { at: [0, 0], size: 0.92 }, ringFade = 0.17, spin = 0.32, onReady }: Props) {
  return (
    <Canvas className={className} dpr={[1, 1.5]} frameloop={active ? "always" : "demand"} gl={{ alpha: true, antialias: true }} camera={{ fov: 30, position: [0, 0, 12], near: 0.1, far: 100 }}>
      <GlassStudio />
      <pointLight position={[-2.5, 3, 4]} intensity={40} color="#ffffff" />
      <pointLight position={[3, 1.5, 3]} intensity={24} color="#fff3c4" />
      <ScanRings placement={rings} fade={ringFade} />
      <Brick placement={brick} spin={spin} onReady={onReady} />
    </Canvas>
  );
}

/**
 * What the glass reflects: a black studio with a few bright strips, the way
 * glass is lit for product shots. Dark glass is defined by its highlights, so
 * a bright room (our usual environment) would just turn it into grey plastic.
 * Built from local light shapes and rendered once: no download, works offline.
 */
function GlassStudio() {
  return (
    <Environment resolution={256} frames={1}>
      <color attach="background" args={["#020203"]} />
      {/* up and behind: this is what the tipped-forward top face and stud tops mirror */}
      <Lightformer form="rect" intensity={2.2} position={[0, 7, -5]} scale={[11, 0.55, 1]} target={[0, 0, 0]} />
      {/* low in front: a thin sheen along the near side so the silhouette holds on black */}
      <Lightformer form="rect" intensity={0.9} position={[0, -7, 4.5]} scale={[9, 0.4, 1]} target={[0, 0, 0]} />
      <Lightformer form="rect" intensity={9} position={[-5, 6, 2]} scale={[9, 1.6, 1]} target={[0, 0, 0]} />
      <Lightformer form="rect" intensity={5} position={[6, 3, 5]} scale={[1.4, 7, 1]} target={[0, 0, 0]} />
      <Lightformer form="rect" intensity={3} position={[-7, -1, 4]} scale={[1, 5, 1]} target={[0, 0, 0]} />
      <Lightformer form="ring" intensity={5} color="#ffcc33" position={[7, 0, -5]} scale={7} target={[0, 0, 0]} />
    </Environment>
  );
}

/** The 3001 part's geometry, baked upright and centred on its own middle. */
function useBrickGeometry() {
  const [geometry, setGeometry] = useState<THREE.BufferGeometry | null>(null);
  useEffect(() => {
    let alive = true;
    let made: THREE.BufferGeometry | null = null;
    prepareModel(BRICK_URL).then(
      (model) => {
        if (!alive) return;
        model.root.updateMatrixWorld(true);
        const baked = model.parts.flatMap((p) => p.meshes).map((m) => m.geometry.clone().applyMatrix4(m.matrixWorld));
        if (!baked.length) return;
        made = baked.length === 1 ? baked[0] : mergeGeometries(baked, false);
        made.center();
        setGeometry(made);
      },
      () => {},
    );
    return () => {
      alive = false;
      made?.dispose();
    };
  }, []);
  return geometry;
}

function Brick({ placement, spin, onReady }: { placement: Placement; spin: number; onReady?: () => void }) {
  const geometry = useBrickGeometry();
  const ready = useEffectEvent(() => onReady?.());
  useEffect(() => {
    if (geometry) ready();
  }, [geometry]);
  const turn = useRef<THREE.Group>(null);
  const viewport = useThree((s) => s.viewport);
  // What the glass "sees" where nothing else is behind it: the dark card.
  const backdrop = useMemo(() => new THREE.Color("#09090b"), []);

  useFrame((_, dt) => {
    if (turn.current) turn.current.rotation.y += spin * Math.min(dt, 0.05);
  });

  if (!geometry) return null;
  const scale = (placement.size * viewport.height) / BRICK_LENGTH;
  return (
    // Outer group: a fixed tip toward the viewer, so the studs always show.
    // Inner group: the slow turn about the brick's own upright axis.
    <group position={[(placement.at[0] * viewport.width) / 2, (placement.at[1] * viewport.height) / 2, 0]} rotation={[0.5, 0, -0.2]} scale={scale}>
      <group ref={turn} rotation={[0, -0.7, 0]}>
        <mesh geometry={geometry}>
          {/* A light, cool tint: the black card behind is what makes the glass read
              as dark, while the tint only decides how much of the rings gets through. */}
          <MeshTransmissionMaterial
            color="#aeb2c8"
            background={backdrop}
            transmission={1}
            thickness={1.7}
            backside
            backsideThickness={0.9}
            ior={1.5}
            roughness={0}
            chromaticAberration={0.07}
            anisotropicBlur={0}
            distortion={0.32}
            distortionScale={0.32}
            temporalDistortion={0.13}
            envMapIntensity={1.1}
            backsideEnvMapIntensity={0.25}
            samples={4}
            resolution={256}
            backsideResolution={128}
          />
        </mesh>
      </group>
    </group>
  );
}

const RING_VERTEX = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

// Five concentric rings with a crisp core and a soft halo, breathing slightly
// out of phase with each other, over a warm glow at the centre.
const RING_FRAGMENT = /* glsl */ `
  uniform float uTime;
  uniform float uFade;
  uniform vec3 uColor;
  varying vec2 vUv;
  void main() {
    float d = length(vUv - 0.5) * 2.0;
    float a = 0.0;
    for (int i = 0; i < 5; i++) {
      float fi = float(i);
      float r = (0.3 + fi * 0.165) * (1.0 + 0.035 * sin(uTime * 1.3 - fi * 0.55));
      float core = smoothstep(0.0095, 0.0035, abs(d - r));
      float halo = exp(-pow((d - r) / 0.034, 2.0)) * 0.38;
      a += (core + halo) * (1.0 - fi * uFade);
    }
    a += 0.2 * exp(-d * d * 5.0);
    a *= smoothstep(1.0, 0.96, d);
    gl_FragColor = vec4(uColor, clamp(a, 0.0, 1.0));
    #include <colorspace_fragment>
  }
`;

function ScanRings({ placement, fade }: { placement: Placement; fade: number }) {
  const camera = useThree((s) => s.camera);
  const size = useThree((s) => s.size);
  const getViewport = useThree((s) => s.viewport.getCurrentViewport);
  const material = useRef<THREE.ShaderMaterial>(null);
  const uniforms = useMemo(() => ({ uTime: { value: 0 }, uFade: { value: fade }, uColor: { value: new THREE.Color("#ffc800") } }), [fade]);

  useFrame((state) => {
    if (material.current) material.current.uniforms.uTime.value = state.clock.elapsedTime;
  });

  // The viewport's extent at the rings' depth (they sit behind the brick).
  const view = getViewport(camera, new THREE.Vector3(0, 0, RING_DEPTH), size);
  const diameter = placement.size * view.height;
  return (
    <mesh position={[(placement.at[0] * view.width) / 2, (placement.at[1] * view.height) / 2, RING_DEPTH]} scale={[diameter, diameter, 1]}>
      <planeGeometry args={[1, 1]} />
      <shaderMaterial ref={material} uniforms={uniforms} vertexShader={RING_VERTEX} fragmentShader={RING_FRAGMENT} transparent depthWrite={false} toneMapped={false} />
    </mesh>
  );
}
