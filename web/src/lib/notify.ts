"use client";

// Step notifications: while the designer works (3-10 minutes), every step it
// takes can ping you like a build pipeline would. In the app that's a brick
// sliding in (StepFeed); with the tab in the background it's a real OS
// notification through the PWA's service worker.
//
// Permission is only ever requested from a tap on the bell, never on load.

const PREF = "bricked.stepNotifications";

const listeners = new Set<() => void>();
let cached: NotifyState | null = null;

/** For useSyncExternalStore, so the bell renders without a setState effect. */
export function subscribeNotify(fn: () => void) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function getNotifyState(): NotifyState {
  return (cached ??= notifyState());
}

/** The server (and the first paint) knows nothing about permissions. */
export const getServerNotifyState = (): NotifyState => "unsupported";

function changed() {
  cached = notifyState();
  listeners.forEach((l) => l());
}

export type NotifyState = "unsupported" | "off" | "on" | "blocked";

const supported = () => typeof window !== "undefined" && "Notification" in window;

export function notifyState(): NotifyState {
  if (!supported()) return "unsupported";
  if (Notification.permission === "denied") return "blocked";
  if (Notification.permission !== "granted") return "off";
  try {
    return localStorage.getItem(PREF) === "off" ? "off" : "on";
  } catch {
    return "on"; // private mode: the permission is the source of truth
  }
}

/** Tap handler for the bell: asks the browser the first time, then toggles. */
export async function toggleNotifications(): Promise<NotifyState> {
  if (!supported()) return "unsupported";
  if (Notification.permission === "default") {
    const granted = (await Notification.requestPermission()) === "granted";
    remember(granted ? "on" : "off");
    changed();
    return getNotifyState();
  }
  if (Notification.permission === "denied") return "blocked";
  const next = notifyState() === "on" ? "off" : "on";
  remember(next);
  changed();
  return next;
}

function remember(v: "on" | "off") {
  try {
    localStorage.setItem(PREF, v);
  } catch {
    // private mode: the setting just doesn't stick
  }
}

/**
 * One step, as an OS notification. Only fires when the app isn't on screen:
 * on screen, the brick sliding in already says it. All notifications share a
 * tag, so a run replaces its own notification instead of stacking ten of them.
 */
export async function notifyStep(title: string, body: string, done = false) {
  if (notifyState() !== "on" || document.visibilityState === "visible") return;
  const options: NotificationOptions = {
    body,
    tag: "bricked-step",
    icon: "/icons/icon-192.png",
    badge: "/icons/icon-192.png",
    silent: !done, // only the finished model makes a sound
  };
  try {
    const reg = await navigator.serviceWorker?.getRegistration();
    if (reg) return void reg.showNotification(title, options);
    new Notification(title, options);
  } catch {
    // notifications are a nicety; never break a build over one
  }
}
