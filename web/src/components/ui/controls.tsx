"use client";

import Link from "next/link";
import { forwardRef } from "react";

type Variant = "yellow" | "blue" | "purple" | "white" | "green";

const VARIANTS: Record<Variant, { bg: string; rim: string; ink: string }> = {
  yellow: { bg: "#ffd502", rim: "#ccaa02", ink: "#1a1a1a" },
  blue: { bg: "#005ad2", rim: "#034aa9", ink: "#ffffff" },
  purple: { bg: "#6e13bc", rim: "#5c109d", ink: "#ffffff" },
  white: { bg: "#ffffff", rim: "#cccccc", ink: "#1a1a1a" },
  green: { bg: "#2fa84a", rim: "#227a37", ink: "#ffffff" },
};

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  icon?: React.ReactNode;
  href?: string;
};

/** The full-width chunky action button (Confirm / Start Building / Build Together). */
export const ChunkyButton = forwardRef<HTMLButtonElement, ButtonProps>(function ChunkyButton(
  { variant = "blue", icon, href, className = "", children, style, ...rest },
  ref,
) {
  const v = VARIANTS[variant];
  const cls = `chunky flex h-[58px] w-full items-center justify-center gap-3 rounded-[16px] text-[19px] font-bold tracking-[-0.01em] ${className}`;
  const css = { background: v.bg, color: v.ink, ["--rim" as string]: v.rim, ...style } as React.CSSProperties;
  const body = (
    <>
      {icon}
      <span>{children}</span>
    </>
  );
  if (href)
    return (
      <Link href={href} className={cls} style={css}>
        {body}
      </Link>
    );
  return (
    <button ref={ref} className={cls} style={css} {...rest}>
      {body}
    </button>
  );
});

type TileTone = "white" | "glass" | "glass-light" | "dark" | "yellow";

const TILE: Record<TileTone, { bg: string; ink: string; rim?: string }> = {
  white: { bg: "#ffffff", ink: "#1a1a1a", rim: "#cccccc" },
  glass: { bg: "rgba(0,0,0,0.34)", ink: "#ffffff" },
  "glass-light": { bg: "rgba(0,0,0,0.2)", ink: "#ffffff" },
  dark: { bg: "rgba(0,0,0,0.55)", ink: "#ffffff" },
  yellow: { bg: "rgba(160,90,0,0.45)", ink: "#ffffff" },
};

type TileProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  tone?: TileTone;
  size?: number;
  href?: string;
  round?: boolean;
  label: string;
};

/** Square icon tile (back, close, home, settings, prev/next). */
export function IconTile({ tone = "white", size = 56, href, round, label, className = "", children, style, ...rest }: TileProps) {
  const t = TILE[tone];
  const cls = `${t.rim ? "chunky" : "active:scale-95 transition-transform"} grid shrink-0 place-items-center ${round ? "rounded-full" : "rounded-[14px]"} ${className}`;
  const css = { width: size, height: size, background: t.bg, color: t.ink, ["--rim" as string]: t.rim, ["--lift" as string]: "4px", ...style } as React.CSSProperties;
  if (href)
    return (
      <Link href={href} aria-label={label} className={cls} style={css}>
        {children}
      </Link>
    );
  return (
    <button aria-label={label} className={cls} style={css} {...rest}>
      {children}
    </button>
  );
}

/** Yellow rounded "bucket" header that the portrait screens hang content from. */
export function YellowBucket({ children, className = "", tone = "yellow" }: { children: React.ReactNode; className?: string; tone?: "yellow" | "home" }) {
  const bg = tone === "home" ? "linear-gradient(180deg,#f0b529 0%,#f3c53a 100%)" : "linear-gradient(180deg,#f5b200 0%,#fccd01 100%)";
  return (
    <div className={`relative z-10 rounded-b-[44px] ${className}`} style={{ background: bg, boxShadow: "0 7px 0 #dcae00" }}>
      <div style={{ paddingTop: "var(--safe-top)" }}>{children}</div>
    </div>
  );
}

/** Big bold centered screen title. */
export function Title({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <h1 className={`text-center text-[30px] font-[900] leading-[1.05] tracking-[-0.025em] text-ink ${className}`}>{children}</h1>;
}
