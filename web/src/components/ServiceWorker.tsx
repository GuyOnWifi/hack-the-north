"use client";

import { useEffect } from "react";

// Registers public/sw.js in production so the app installs as a PWA and the
// model/part assets keep working with the wifi off.
export function ServiceWorker() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production" || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/sw.js", { scope: "/", updateViaCache: "none" }).catch(() => {});
  }, []);
  return null;
}
