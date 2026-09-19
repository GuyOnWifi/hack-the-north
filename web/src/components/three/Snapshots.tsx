"use client";

import { useEffect, useState } from "react";
import { allParts, modelSnapshot, partThumbnail, prepareModel, type PartNode } from "@/lib/ldraw";
import { colourHex, partImageUrl } from "@/lib/data";
import { IsoBrick } from "@/components/ui/IsoBrick";
import bakedList from "@/fixtures/snapshots.json";

/** Still render of a whole model, generated once per session and cached. */
export function ModelSnapshot({ url, className = "", alt, width = 640, height = 480 }: { url: string; className?: string; alt: string; width?: number; height?: number }) {
  // Sample models ship pre-rendered (scripts/bake-snapshots.mjs): no WebGL at all.
  const baked = bakedSnapshot(url, width, height);
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (baked) return;
    let alive = true;
    let retry: ReturnType<typeof setTimeout>;
    // One retry after a pause: a lost WebGL context usually recovers.
    const attempt = (left: number) =>
      modelSnapshot(url, width, height).then(
        (s) => alive && setSrc(s),
        () => {
          if (!alive) return;
          if (left > 0) retry = setTimeout(() => attempt(left - 1), 1200);
          else setFailed(true);
        },
      );
    attempt(1);
    return () => {
      alive = false;
      clearTimeout(retry);
    };
  }, [url, width, height, baked]);
  if (baked)
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={baked} alt={alt} className={`object-contain ${className}`} draggable={false} decoding="async" />;
  if (failed) return <div className={`grid place-items-center ${className}`}><IsoBrick w={2} d={2} h={3} color="#9a9a9a" size={80} /></div>;
  if (!src) return <div className={`skeleton rounded-2xl ${className}`} aria-label="Loading preview" />;
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={src} alt={alt} className={`object-contain ${className}`} draggable={false} />;
}

const BAKED = new Set(bakedList as string[]);

/** Static file for a pre-rendered sample-model snapshot, if one was baked. */
export function bakedSnapshot(url: string, width: number, height: number) {
  const key = snapshotKey(url, width, height);
  return BAKED.has(key) ? `/snapshots/${key}.png` : null;
}

export function snapshotKey(url: string, width: number, height: number) {
  return `${url.replace(/^.*\//, "").replace(/\.[a-z]+$/, "")}-${width}x${height}`;
}

// Lets scripts/bake-snapshots.mjs drive the real renderer from a dev page:
// whole-model cards, and pictures of parts that have no bundled image.
if (typeof window !== "undefined" && process.env.NODE_ENV !== "production") {
  Object.assign(window, {
    __bakeSnapshot: modelSnapshot,
    __bakeMissingParts: async (url: string) => {
      const model = await prepareModel(url);
      const missing = allParts(model).filter((p) => !partImageUrl(p.part, p.colour));
      return Promise.all(missing.map(async (p) => ({ part: p.part, colour: p.colour, data: await partThumbnail(p.sample, 256) })));
    },
  });
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
