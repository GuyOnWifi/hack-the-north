"use client";

import { useSyncExternalStore } from "react";
import { Bell, BellOff, BellRing } from "lucide-react";
import { IconTile } from "@/components/ui/controls";
import { getNotifyState, getServerNotifyState, subscribeNotify, toggleNotifications } from "@/lib/notify";

/** Ping me per step: designing runs for minutes, so you can go do something
 *  else and still watch the harness work. Asks permission only on a tap. */
export function StepBell() {
  const state = useSyncExternalStore(subscribeNotify, getNotifyState, getServerNotifyState);
  if (state === "unsupported") return null;

  const label = { on: "Step alerts on", off: "Tell me each step", blocked: "Alerts blocked in your browser" }[state];
  const Icon = { on: BellRing, off: Bell, blocked: BellOff }[state];
  return (
    <IconTile
      tone={state === "on" ? "ai" : "glass-light"}
      label={label}
      title={label}
      size={60}
      onClick={() => void toggleNotifications()}
      disabled={state === "blocked"}
      style={state === "blocked" ? { opacity: 0.5 } : undefined}
    >
      <Icon size={28} strokeWidth={2.6} />
    </IconTile>
  );
}
