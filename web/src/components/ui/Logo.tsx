import { APP_NAME, LOGO_SMALL_SRC, LOGO_SRC } from "@/lib/brand";

/** The logo mark (the red corner brick). Width follows `size`; it keeps its aspect. */
export function LogoMark({ size = 64, small, className = "" }: { size?: number; small?: boolean; className?: string }) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={small ? LOGO_SMALL_SRC : LOGO_SRC} alt="" width={size} draggable={false} className={`pointer-events-none select-none ${className}`} style={{ width: size, height: "auto" }} />
  );
}

/** Chunky orange wordmark with an extruded underside, like the BUILDER title. */
export function Wordmark({ size = 46 }: { size?: number }) {
  return (
    <div
      className="select-none font-[900] uppercase leading-none"
      style={{
        fontSize: size,
        letterSpacing: "-0.02em",
        color: "#ff5a1f",
        textShadow: "0 2px 0 #d8420f, 0 4px 0 #b8360a, 0 8px 18px rgba(0,0,0,0.45)",
      }}
    >
      {APP_NAME}
    </div>
  );
}

/** Small inline lockup: mark + name, for headers. */
export function LogoLockup({ size = 26, ink = "#1a1a1a" }: { size?: number; ink?: string }) {
  return (
    <div className="flex items-center gap-2" aria-label={APP_NAME}>
      <LogoMark size={size * 1.25} small className="drop-shadow-[0_2px_2px_rgba(120,60,0,0.3)]" />
      <span className="font-[900] leading-none tracking-[-0.02em]" style={{ fontSize: size * 0.72, color: ink }}>
        {APP_NAME}
      </span>
    </div>
  );
}

/**
 * The brand loader: the logo mark hops up and snaps back down onto its shadow,
 * like a brick being pressed on. Replaces every generic spinner.
 */
export function BrickLoader({ size = 56, label, tone = "dark" }: { size?: number; label?: string; tone?: "dark" | "light" }) {
  return (
    <div className="flex flex-col items-center gap-3" role="status" aria-label={label ?? "Loading"}>
      <div className="relative flex flex-col items-center" style={{ width: size * 1.3, height: size * 1.25 }}>
        <div style={{ animation: "brick-hop 900ms cubic-bezier(.5,0,.5,1) infinite" }}>
          <LogoMark size={size} small />
        </div>
        <div
          className="absolute bottom-0 rounded-[50%]"
          style={{ width: size * 0.8, height: size * 0.14, background: tone === "dark" ? "rgba(0,0,0,0.22)" : "rgba(255,255,255,0.25)", animation: "brick-shadow 900ms cubic-bezier(.5,0,.5,1) infinite" }}
        />
      </div>
      {label && <span className={`text-[15px] font-bold ${tone === "dark" ? "text-ink-soft" : "text-white/85"}`}>{label}</span>}
    </div>
  );
}
