"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Home, Layers, ScanLine, Smile } from "lucide-react";
import { IsoBrick } from "./IsoBrick";

/** Floating white tab pill + yellow scan button (IMG_1247). */
export function TabBar() {
  const path = usePathname();
  const tabs = [
    { href: "/home", label: "Home", icon: Home, active: path === "/home" },
    { href: "/inventory", label: "My bricks", icon: Layers, active: path.startsWith("/inventory") },
    { href: "/builds", label: "Builds", icon: Smile, active: path.startsWith("/builds") },
  ];
  return (
    <nav className="pointer-events-none fixed inset-x-0 bottom-0 z-40 flex justify-center gap-3 px-4" style={{ paddingBottom: "calc(var(--safe-bottom) + 14px)" }}>
      <div className="pointer-events-auto flex h-[72px] items-center gap-2 rounded-[28px] bg-white px-4 shadow-[0_10px_30px_rgba(20,40,80,0.18)]">
        {tabs.map(({ href, label, icon: Icon, active }) => (
          <Link key={href} href={href} aria-label={label} className="grid h-14 w-14 place-items-center transition-transform active:scale-90">
            <Icon size={active ? 34 : 30} strokeWidth={active ? 2.6 : 2.2} color={active ? "#2458ca" : "#c9c9c9"} fill={active ? "#2458ca" : "none"} fillOpacity={active ? 0.18 : 0} />
          </Link>
        ))}
      </div>
      <Link
        href="/scan"
        aria-label="Scan bricks"
        className="chunky pointer-events-auto grid h-[72px] w-[72px] place-items-center rounded-[22px]"
        style={{ background: "#f8d648", ["--rim" as string]: "#d8b320", ["--lift" as string]: "5px" } as React.CSSProperties}
      >
        <div className="relative">
          <IsoBrick w={2} d={2} h={3} color="#e8e8e8" size={40} />
          <span className="absolute -right-2 -top-2 grid h-6 w-6 place-items-center rounded-full bg-[#1a1a1a]">
            <ScanLine size={14} color="#fff" strokeWidth={2.6} />
          </span>
        </div>
      </Link>
    </nav>
  );
}

const SPLASH_BRICKS = [
  { w: 2, d: 2, h: 3, color: "#7b2fd0", x: "-6%", y: "-3%", size: 132, r: -24 },
  { w: 1, d: 1, h: 1, color: "#f7c600", round: true, x: "31%", y: "-1%", size: 46, r: 0 },
  { w: 1, d: 1, h: 1, color: "#f7c600", round: true, x: "67%", y: "-2%", size: 42, r: 0 },
  { w: 2, d: 1, h: 3, color: "#1e9e3a", x: "74%", y: "2%", size: 80, r: 14 },
  { w: 1, d: 2, h: 1, color: "#f7b500", x: "14%", y: "12.5%", size: 46, r: 32 },
  { w: 1, d: 1, h: 1, color: "#f7d000", round: true, x: "66%", y: "12%", size: 48, r: 0 },
  { w: 1, d: 1, h: 1, color: "#f7d000", round: true, x: "26%", y: "80%", size: 48, r: 0 },
  { w: 2, d: 1, h: 3, color: "#ff3a1a", x: "44%", y: "81%", size: 96, r: -8 },
  { w: 1, d: 2, h: 1, color: "#f7b500", x: "74%", y: "79%", size: 44, r: 24 },
];

const GREY_BRICKS = [
  { w: 2, d: 1, h: 3, x: "2%", y: "6%", size: 70, r: -24 },
  { w: 1, d: 1, h: 1, round: true, x: "38%", y: "6%", size: 30, r: 0 },
  { w: 2, d: 2, h: 1, x: "60%", y: "8%", size: 64, r: 12 },
  { w: 1, d: 1, h: 3, x: "14%", y: "31%", size: 40, r: 0 },
  { w: 2, d: 1, h: 3, x: "28%", y: "36%", size: 76, r: -10 },
  { w: 2, d: 2, h: 3, x: "84%", y: "45%", size: 66, r: 18 },
  { w: 1, d: 2, h: 1, x: "2%", y: "46%", size: 58, r: -30 },
  { w: 2, d: 1, h: 1, x: "14%", y: "73%", size: 62, r: -12 },
  { w: 1, d: 1, h: 3, x: "28%", y: "76%", size: 36, r: 0 },
  { w: 1, d: 2, h: 1, x: "64%", y: "76%", size: 44, r: 20 },
  { w: 2, d: 2, h: 1, x: "72%", y: "86%", size: 72, r: -6 },
  { w: 1, d: 1, h: 3, x: "90%", y: "91%", size: 32, r: 0 },
];

/** Decorative bricks drifting behind a screen (IMG_1223 colour / IMG_1230 grey). */
export function FloatingBricks({ tone = "colour", opacity = 1 }: { tone?: "colour" | "grey"; opacity?: number }) {
  const list = tone === "colour" ? SPLASH_BRICKS : GREY_BRICKS.map((b) => ({ ...b, color: "#8e8e8e", round: "round" in b ? b.round : false }));
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" style={{ opacity }} aria-hidden>
      {list.map((b, i) => (
        <div
          key={i}
          className="absolute"
          style={{
            left: b.x,
            top: b.y,
            ["--r" as string]: `${b.r}deg`,
            animation: `float-y ${5 + (i % 4)}s ease-in-out ${-i * 0.7}s infinite`,
            filter: tone === "colour" ? "drop-shadow(0 10px 14px rgba(0,0,0,0.45))" : undefined,
          }}
        >
          <IsoBrick w={b.w} d={b.d} h={b.h} color={b.color} round={"round" in b ? b.round : false} size={b.size} />
        </div>
      ))}
    </div>
  );
}

/** Round-plate stack progress bar from the loading screen (IMG_1230). */
export function PlateProgress({ value, count = 12 }: { value: number; count?: number }) {
  const active = Math.min(count - 1, Math.floor(value * count));
  return (
    <div className="flex items-center" role="progressbar" aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100}>
      {Array.from({ length: count }, (_, i) => {
        const on = i === active;
        return (
          <div
            key={i}
            className="-mx-[3px] h-[34px] w-[13px] rounded-[50%/12%] transition-colors duration-300"
            style={{
              background: on ? "linear-gradient(90deg,#c26f00,#ffa51f 45%,#e88b00)" : i < active ? "linear-gradient(90deg,#d8d8d8,#ffffff 45%,#e2e2e2)" : "linear-gradient(90deg,#cfcfcf,#f4f4f4 45%,#d9d9d9)",
              boxShadow: "inset -1px 0 0 rgba(0,0,0,0.12), 0 6px 10px rgba(0,0,0,0.12)",
              zIndex: count - i,
            }}
          />
        );
      })}
    </div>
  );
}

/** Timeline slider with bag stops and a round-plate knob (IMG_1242 / IMG_1245). */
export function StudSlider({ value, max, stops = [], onChange, className = "" }: { value: number; max: number; stops?: number[]; onChange: (v: number) => void; className?: string }) {
  const pct = max > 0 ? (value / max) * 100 : 0;
  const passed = [0, ...stops].filter((s) => s <= value).pop() ?? 0;
  const donePct = (passed / Math.max(1, max)) * 100;
  return (
    <div className={`relative h-[46px] rounded-full px-[14px] ${className}`} style={{ background: "rgba(90,90,90,0.55)" }}>
      <div className="relative top-1/2 h-[20px] -translate-y-1/2 rounded-full bg-white">
        <div className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${pct}%`, background: "#e88b00" }} />
        <div className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${donePct}%`, background: "#ffd502" }} />
        {stops.map((s) => (
          <div key={s} className="absolute top-1/2 h-[7px] w-[7px] -translate-x-1/2 -translate-y-1/2 rounded-full" style={{ left: `${(s / Math.max(1, max)) * 100}%`, background: s <= value ? "rgba(0,0,0,0.18)" : "#cccccc" }} />
        ))}
        <div className="pointer-events-none absolute top-1/2 -translate-x-1/2 -translate-y-1/2" style={{ left: `${pct}%` }}>
          <div className="grid h-[42px] w-[42px] place-items-center rounded-full" style={{ background: "radial-gradient(circle at 50% 40%,#ffe45c,#f9d51e 60%,#e2b900)", boxShadow: "0 4px 0 #c79f00, 0 6px 10px rgba(0,0,0,0.25)" }}>
            <div className="h-[26px] w-[26px] rounded-full" style={{ background: "radial-gradient(circle at 50% 35%,#fff08a,#f6d21a 70%)", boxShadow: "inset 0 -2px 0 rgba(0,0,0,0.12)" }} />
          </div>
        </div>
      </div>
      <input
        type="range"
        min={0}
        max={max}
        step={1}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label="Build progress"
        className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
      />
    </div>
  );
}

/** Instruction bag glyph with a number (IMG_1232 "1 - 6", IMG_1245 "5"). */
export function BagGlyph({ label, size = 64 }: { label: string; size?: number }) {
  return (
    <div className="relative grid place-items-center" style={{ width: size, height: size * 1.05 }}>
      <svg viewBox="0 0 64 68" width={size} height={size * 1.05} aria-hidden className="absolute inset-0 drop-shadow-[0_4px_6px_rgba(0,0,0,0.18)]">
        <path d="M8 6 Q32 2 56 6 L58 58 Q46 66 32 62 Q18 66 6 58 Z" fill="#fbfbfb" stroke="#e1e1e1" strokeWidth="1.5" />
        <path d="M8 6 Q32 2 56 6 L56 12 Q32 8 8 12 Z" fill="#ececec" />
      </svg>
      <span className="relative text-[17px] font-[800] text-ink">{label}</span>
    </div>
  );
}
