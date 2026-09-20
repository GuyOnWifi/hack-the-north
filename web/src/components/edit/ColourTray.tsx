"use client";

import type { PartsTable } from "@/lib/bricolage";

// The palette the server offers for this model: its own colours first, then the
// common ones. Tapping one repaints the selection — the tile itself stays
// silent, the accepted edit plays the sound.

export function ColourTray({ palette, onPick, disabled }: { palette: PartsTable["palette"]; onPick: (code: number) => void; disabled?: boolean }) {
  if (!palette.length) return null;
  return (
    <div data-sound="off" className="no-scrollbar flex max-w-full gap-2 overflow-x-auto rounded-[14px] bg-white/85 px-3 py-2.5" style={{ animation: "tape-in 180ms ease-out" }}>
      {palette.map((c) => (
        <button
          key={c.code}
          type="button"
          aria-label={c.name}
          title={c.name}
          disabled={disabled}
          onClick={() => onPick(c.code)}
          className="h-9 w-9 shrink-0 rounded-[8px] transition-transform active:scale-90 disabled:opacity-40"
          style={{
            background: c.trans ? `linear-gradient(135deg, ${c.hex}99, ${c.hex}cc)` : c.hex,
            boxShadow: "inset 0 -3px 0 rgba(0,0,0,0.18), 0 0 0 2px rgba(0,0,0,0.08)",
          }}
        />
      ))}
    </div>
  );
}
