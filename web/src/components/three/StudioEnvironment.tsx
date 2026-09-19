"use client";

import { useThree } from "@react-three/fiber";
import { useEffect, useState } from "react";
import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";

/**
 * Soft studio reflections generated locally (no HDR download, so it works
 * offline), attached declaratively as the scene's environment map.
 */
export function StudioEnvironment({ blur = 0.04 }: { blur?: number }) {
  const gl = useThree((s) => s.gl);
  const [texture, setTexture] = useState<THREE.Texture | null>(null);

  useEffect(() => {
    const pmrem = new THREE.PMREMGenerator(gl);
    const room = new RoomEnvironment();
    const tex = pmrem.fromScene(room, blur).texture;
    const id = requestAnimationFrame(() => setTexture(tex));
    return () => {
      cancelAnimationFrame(id);
      tex.dispose();
      pmrem.dispose();
      room.dispose();
    };
  }, [gl, blur]);

  return texture ? <primitive object={texture} attach="environment" /> : null;
}
