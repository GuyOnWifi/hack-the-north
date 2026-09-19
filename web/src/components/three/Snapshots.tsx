"use client";

import { useEffect, useState } from "react";
import { modelSnapshot, partThumbnail, type PartNode } from "@/lib/ldraw";
import { colourHex, partImageUrl } from "@/lib/data";
import { IsoBrick } from "@/components/ui/IsoBrick";

/** Still render of a whole model, generated once per session and cached. */
export function ModelSnapshot({ url, className = "", alt, width = 640, height = 480 }: { url: string; className?: string; alt: string; width?: number; height?: number }) {
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    modelSnapshot(url, width, height).then(
      (s) => alive && setSrc(s),
      () => alive && setFailed(true),
    );
    return () => {
      alive = false;
    };
  }, [url, width, height]);
  if (failed) return <div className={`grid place-items-center ${className}`}><IsoBrick w={2} d={2} h={3} color="#9a9a9a" size={80} /></div>;
  if (!src) return <div className={`skeleton rounded-2xl ${className}`} aria-label="Loading preview" />;
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={src} alt={alt} className={`object-contain ${className}`} draggable={false} />;
}

/**
 * Part picture: the bundled Rebrickable render when we have one, else a render of
 * the actual part from a loaded model, else a tinted generic brick.
 */
export function PartImage({ part, colour, node, size = 72, className = "" }: { part: string; colour: number; node?: PartNode; size?: number; className?: string }) {
  const local = partImageUrl(part, colour);
  const [fallback, setFallback] = useState<string | null>(null);
  const [broken, setBroken] = useState(false);
  useEffect(() => {
    if ((local && !broken) || !node) return;
    let alive = true;
    partThumbnail(node).then((s) => alive && setFallback(s));
    return () => {
      alive = false;
    };
  }, [local, broken, node]);
  const src = local && !broken ? local : fallback;
  if (!src)
    return (
      <div className={`grid place-items-center ${className}`} style={{ width: size, height: size }}>
        <IsoBrick w={2} d={1} h={3} color={colourHex(colour)} size={size * 0.7} />
      </div>
    );
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={src} alt="" width={size} height={size} onError={() => setBroken(true)} className={`object-contain ${className}`} style={{ width: size, height: size }} draggable={false} />
  );
}
