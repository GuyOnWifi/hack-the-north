/** Seeded PRNG (mulberry32) so a seed reproduces a scene exactly. */
export function makeRng(seed: number) {
  let a = seed >>> 0;
  const next = () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  return {
    next,
    range: (lo: number, hi: number) => lo + (hi - lo) * next(),
    int: (n: number) => Math.floor(next() * n),
    pick: <T>(items: readonly T[]) => items[Math.floor(next() * items.length)],
  };
}
export type Rng = ReturnType<typeof makeRng>;
