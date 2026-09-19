"use client";

import { useSyncExternalStore } from "react";

const query = "(orientation: landscape)";

/** True when the viewport is wider than tall. Viewer screens lay out off this. */
export function useLandscape() {
  return useSyncExternalStore(
    (cb) => {
      const m = window.matchMedia(query);
      m.addEventListener("change", cb);
      return () => m.removeEventListener("change", cb);
    },
    () => window.matchMedia(query).matches,
    () => true,
  );
}
