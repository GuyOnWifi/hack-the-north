"use client";

import { Canvas, useFrame } from "@react-three/fiber";
import { RoundedBox } from "@react-three/drei";
import { useRef } from "react";
import * as THREE from "three";
import { StudioEnvironment } from "./StudioEnvironment";

// The glossy smoked 2x4 brick from the splash / home carousel (IMG_1223),
// slowly turning on display with a couple of hard sparkles.

function Brick() {
  const ref = useRef<THREE.Group>(null);
  useFrame((_, dt) => {
    if (ref.current) ref.current.rotation.y += Math.min(dt, 0.05) * 0.35;
  });
  const material = (
    <meshPhysicalMaterial color="#0d0d0f" roughness={0.08} metalness={0} clearcoat={1} clearcoatRoughness={0.05} transmission={0.35} thickness={1.2} ior={1.5} envMapIntensity={2.2} />
  );
  const studs: [number, number][] = [];
  for (let x = 0; x < 4; x++) for (let z = 0; z < 2; z++) studs.push([(x - 1.5) * 0.8, (z - 0.5) * 0.8]);
  return (
    <group ref={ref} rotation={[0.52, -0.6, 0.2]}>
      <RoundedBox args={[3.2, 0.96 * 1.2, 1.6]} radius={0.06} smoothness={4}>
        {material}
      </RoundedBox>
      {studs.map(([x, z]) => (
        <mesh key={`${x}${z}`} position={[x, 0.58 + 0.1, z]}>
          <cylinderGeometry args={[0.24, 0.24, 0.2, 40]} />
          {material}
        </mesh>
      ))}
    </group>
  );
}

export function HeroBrick({ className = "" }: { className?: string }) {
  return (
    <Canvas className={className} dpr={[1, 2]} gl={{ alpha: true, antialias: true }} camera={{ fov: 30, position: [0, 0.3, 12.5] }}>
      <StudioEnvironment blur={0.02} />
      <pointLight position={[-2, 3, 3]} intensity={40} color="#ffffff" />
      <pointLight position={[2.5, 2, 2]} intensity={25} color="#fff7d6" />
      <directionalLight position={[0, 5, 5]} intensity={1.5} />
      <Brick />
    </Canvas>
  );
}

/** Concentric yellow rings behind the hero brick. */
export function Rings({ size = 340 }: { size?: number }) {
  return (
    <div className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2" style={{ width: size, height: size }} aria-hidden>
      <div className="absolute inset-0 rounded-full" style={{ background: "radial-gradient(circle, rgba(255,200,0,0.28) 0%, rgba(255,200,0,0.08) 45%, transparent 70%)" }} />
      {[0.3, 0.46, 0.62, 0.8, 1].map((s, i) => (
        <div
          key={s}
          className="absolute left-1/2 top-1/2 rounded-full"
          style={{
            width: size * s,
            height: size * s,
            marginLeft: (-size * s) / 2,
            marginTop: (-size * s) / 2,
            border: `${i < 3 ? 6 : 4}px solid rgba(250,204,0,${1 - i * 0.19})`,
            boxShadow: `0 0 16px rgba(255,204,0,${0.55 - i * 0.1}), inset 0 0 12px rgba(255,204,0,${0.4 - i * 0.07})`,
            animation: `ring-pulse 2.4s ease-in-out ${i * 0.18}s infinite alternate`,
          }}
        />
      ))}
    </div>
  );
}
