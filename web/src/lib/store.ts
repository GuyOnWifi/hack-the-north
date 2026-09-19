"use client";

import { useSyncExternalStore } from "react";
import { INVENTORY_FIXTURE } from "./data";
import type { InventoryItem } from "./types";

// Tiny persisted session store: the captured photo and the reviewed inventory.
interface Session {
  photo: string | null;
  inventory: InventoryItem[];
  scanned: boolean;
}

const KEY = "brickbook-session-v2";
const empty: Session = { photo: null, inventory: [], scanned: false };

let state: Session = empty;
let hydrated = false;
const listeners = new Set<() => void>();

function hydrate() {
  if (hydrated || typeof window === "undefined") return;
  hydrated = true;
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw) state = { ...empty, ...JSON.parse(raw) };
  } catch {}
}

function persist() {
  try {
    // The photo can be large; drop it rather than fail the whole write.
    window.localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    try {
      window.localStorage.setItem(KEY, JSON.stringify({ ...state, photo: null }));
    } catch {}
  }
}

export function setSession(update: Partial<Session> | ((s: Session) => Partial<Session>)) {
  hydrate();
  state = { ...state, ...(typeof update === "function" ? update(state) : update) };
  persist();
  listeners.forEach((l) => l());
}

export function loadSampleSession() {
  setSession({ photo: null, inventory: INVENTORY_FIXTURE, scanned: true });
}

export function useSession() {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => {
      hydrate();
      return state;
    },
    () => empty,
  );
}

export function updateItem(id: string, patch: Partial<InventoryItem>) {
  setSession((s) => ({ inventory: s.inventory.map((i) => (i.id === id ? { ...i, ...patch } : i)) }));
}

export function removeItem(id: string) {
  setSession((s) => ({ inventory: s.inventory.filter((i) => i.id !== id) }));
}
