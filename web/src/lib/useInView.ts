"use client";

import { useEffect, useRef, useState } from "react";

/**
 * True while at least `threshold` of the element is on screen (scroll
 * containers included). Live 3D previews use it to stop animating when they're
 * scrolled away, so a page can hold several without cooking a phone.
 */
export function useInView<T extends Element>(threshold = 0.35) {
  const ref = useRef<T>(null);
  const [inView, setInView] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(([entry]) => setInView(entry.isIntersecting), { threshold });
    io.observe(el);
    return () => io.disconnect();
  }, [threshold]);
  return [ref, inView] as const;
}
