"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Search, Pencil } from "lucide-react";
import { GhostBricks, TabBar } from "@/components/ui/chrome";
import { YellowBucket } from "@/components/ui/controls";
import { SketchPad } from "@/components/SketchPad";
import { ModelSnapshot } from "@/components/three/Snapshots";
import { BUILDS, THEMES, getBuild } from "@/lib/data";
import { useInView } from "@/lib/useInView";
import { LogoLockup } from "@/components/ui/Logo";

const ModelView = dynamic(
  () => import("@/components/three/ModelView").then((m) => m.ModelView),
  { ssr: false },
);
const GlassBrick = dynamic(
  () => import("@/components/three/GlassBrick").then((m) => m.GlassBrick),
  { ssr: false },
);

// Home (IMG_1226 / IMG_1227): yellow bucket with the booklet and search,
// promo carousel, then the themes grid above a floating tab bar.
export default function Home() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [sketching, setSketching] = useState(false);

  return (
    <main
      className="relative mx-auto min-h-dvh max-w-[520px] pb-36"
      style={{
        background:
          "linear-gradient(180deg,#90aac5 0%,#b9cde2 40%,#d3e1ef 70%,#e6eef7 100%)",
      }}
    >
      <YellowBucket tone="home" className="px-[18px] pb-[22px]">
        <div className="relative flex h-[104px] items-end pb-3 pl-[146px]">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/darth-vader.png"
            alt=""
            draggable={false}
            className="pointer-events-none absolute -left-3 top-[-10px] h-[184px] w-auto select-none drop-shadow-[0_10px_14px_rgba(120,70,0,0.35)]"
          />
          <div className="relative">
            <LogoLockup size={26} />
            <div className="mt-1.5 text-[28px] font-[900] leading-none tracking-[-0.03em] text-ink">
              Let&apos;s build.
            </div>
          </div>
        </div>
        <form
          className="chunky relative z-10 mt-1 flex h-[62px] items-center gap-3 rounded-[18px] bg-white pl-5 pr-3"
          style={
            {
              ["--rim" as string]: "#d5d5d5",
              ["--lift" as string]: "5px",
            } as React.CSSProperties
          }
          onSubmit={(e) => {
            e.preventDefault();
            router.push(
              query.trim()
                ? `/create?prompt=${encodeURIComponent(query.trim())}`
                : "/builds",
            );
          }}
        >
          <Search size={26} strokeWidth={2.6} color="#1a1a1a" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Build me a rover"
            aria-label="Describe a build"
            className="h-full min-w-0 flex-1 bg-transparent text-[19px] text-ink outline-none placeholder:text-[#949494]"
          />
          <span className="h-9 w-px bg-[#d9d9d9]" />
          <button type="button" onClick={() => setSketching(true)} aria-label="Sketch a build" className="grid h-11 w-11 shrink-0 place-items-center active:scale-95">
            <Pencil size={26} strokeWidth={2.2} color="#1a1a1a" />
          </button>
        </form>
      </YellowBucket>
      {sketching && <SketchPad onClose={() => setSketching(false)} />}

      <Carousel />

      <section className="relative isolate mt-3 pb-6 pt-4">
        {/* big dark-blue bricks on the page itself, behind the grid */}
        <GhostBricks
          seed={211}
          cols={3}
          rows={5}
          scale={1.8}
          color="#123a8c"
          opacity={0.2}
          skip={0.2}
        />
        <h2 className="relative text-center text-[22px] font-[800] tracking-[-0.01em] text-ink">
          Themes
        </h2>
        <div className="relative mt-4 grid grid-cols-2 gap-[18px] px-[18px]">
          {THEMES.map((t, i) => {
            const build = getBuild(t.model)!;
            return (
              <Link
                key={t.id}
                href={`/builds?theme=${encodeURIComponent(t.id)}`}
                className="chunky relative isolate flex aspect-[0.66] flex-col overflow-hidden rounded-[22px]"
                style={
                  {
                    background: t.bg,
                    ["--rim" as string]: "rgba(0,0,0,0.12)",
                    ["--lift" as string]: "5px",
                  } as React.CSSProperties
                }
              >
                {/* each card's bricks pick up the main colour of its model */}
                <GhostBricks
                  seed={101 + i * 17}
                  cols={2}
                  rows={3}
                  scale={1.5}
                  color={CARD_BRICKS[t.id].color}
                  opacity={CARD_BRICKS[t.id].opacity}
                  skip={0.1}
                />
                <span
                  className="relative px-4 pt-5 text-center text-[28px] font-[900] leading-none tracking-[-0.03em]"
                  style={{
                    color: t.ink,
                    fontStyle: t.id === "Vehicles" ? "italic" : undefined,
                  }}
                >
                  {t.label}
                </span>
                <ModelSnapshot
                  url={build.model}
                  alt={build.name}
                  width={420}
                  height={520}
                  className="relative mt-auto h-[78%] w-full"
                />
              </Link>
            );
          })}
        </div>
      </section>
      <TabBar />
    </main>
  );
}

const CARD_BRICKS: Record<string, { color: string; opacity: number }> = {
  Vehicles: { color: "#f08a00", opacity: 0.32 },
  Space: { color: "#2f6cf0", opacity: 0.3 },
  Trucks: { color: "#e3000b", opacity: 0.28 },
  Anything: { color: "#1f5fd6", opacity: 0.2 },
};

/** The smoked-glass brick in front of the rings, which pulse from the card's right edge. */
function HeroGlass({ active }: { active: boolean }) {
  const [ready, setReady] = useState(false);
  return (
    <div
      className="pointer-events-none absolute inset-0 transition-opacity duration-700"
      style={{ opacity: ready ? 1 : 0 }}
    >
      <GlassBrick
        active={active}
        brick={{ at: [0.42, 0.08], size: 1.02 }}
        rings={{ at: [1, 0], size: 2.3 }}
        ringFade={0.09}
        onReady={() => setReady(true)}
      />
    </div>
  );
}

/** A live model turning slowly on display, sized to overflow its card so the card's edge crops it. */
function SpinningModel({
  url,
  active,
  zoom = 1,
  spin = 0.22,
}: {
  url: string;
  active: boolean;
  zoom?: number;
  spin?: number;
}) {
  const [ready, setReady] = useState(false);
  return (
    // The canvas covers the whole card and overflows right, top and bottom, so the
    // only edge that ever crops the model is the card's own rounded one.
    <div
      className="pointer-events-none absolute left-0 right-[-62%] top-[-48%] h-[170%] transition-opacity duration-700"
      style={{ opacity: ready ? 1 : 0 }}
    >
      <ModelView
        url={url}
        mode="display"
        spin={spin}
        interactive={false}
        zoom={zoom}
        active={active}
        onLoaded={() => setReady(true)}
      />
    </div>
  );
}

function Slide({
  href,
  title,
  sub,
  bg,
  children,
}: {
  href: string;
  title: string;
  sub: string;
  bg: string;
  children: (active: boolean) => React.ReactNode;
}) {
  const [ref, inView] = useInView<HTMLAnchorElement>();
  // Each live 3D card costs a WebGL context; don't create one until the card is
  // first swiped into view (then keep it, since recreating costs more).
  const [seen, setSeen] = useState(false);
  if (inView && !seen) setSeen(true);
  return (
    <Link
      ref={ref}
      href={href}
      className="relative isolate h-[272px] w-[calc(100%-38px)] shrink-0 snap-start overflow-hidden rounded-[24px]"
      style={{ background: bg, boxShadow: "0 6px 0 rgba(0,0,0,0.12)" }}
    >
      {seen && children(inView)}
      {/* keeps the title readable where the model passes behind it */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "linear-gradient(24deg, rgba(0,0,0,0.55) 0%, rgba(0,0,0,0.18) 30%, rgba(0,0,0,0) 54%)",
        }}
      />
      <div
        className="absolute bottom-6 left-6 right-24 text-white"
        style={{
          textShadow: "0 1px 3px rgba(0,0,0,0.55), 0 2px 14px rgba(0,0,0,0.5)",
        }}
      >
        <div className="text-[22px] font-[800] leading-tight tracking-[-0.01em]">
          {title}
        </div>
        <div className="mt-1 text-[16px] font-medium text-white/90">{sub}</div>
      </div>
    </Link>
  );
}

function Carousel() {
  const [page, setPage] = useState(0);
  const lunar = BUILDS.find((b) => b.id === "lunar")!;
  const car = BUILDS.find((b) => b.id === "car")!;
  const titles = ["Say it, build it", lunar.name, "Your manual, printed"];
  return (
    <>
      <div
        className="no-scrollbar mt-8 flex snap-x snap-mandatory gap-3 overflow-x-auto px-[10px] scroll-px-[10px]"
        onScroll={(e) => {
          const el = e.currentTarget;
          setPage(
            Math.round(
              el.scrollLeft / (el.firstElementChild as HTMLElement).offsetWidth,
            ),
          );
        }}
      >
        <Slide
          href="/builds"
          title={titles[0]}
          sub="An idea in. A real build out."
          bg="linear-gradient(180deg,#050505,#1c1c1c)"
        >
          {(active) => (
            <>
              <GhostBricks seed={41} opacity={0.16} />
              <HeroGlass active={active} />
            </>
          )}
        </Slide>
        <Slide
          href={`/build/${lunar.id}`}
          title={titles[1]}
          sub={`${lunar.pieces} pieces. Tonight's pick.`}
          bg="linear-gradient(180deg,#3a1780,#6e13bc)"
        >
          {(active) => (
            <>
              <GhostBricks seed={7} opacity={0.17} />
              <SpinningModel url={lunar.model} active={active} zoom={1.4} />
            </>
          )}
        </Slide>
        <Slide
          href="/builds"
          title={titles[2]}
          sub="Every step, ready for paper."
          bg="linear-gradient(180deg,#0b4cb5,#005ad2)"
        >
          {(active) => (
            <>
              <GhostBricks seed={23} opacity={0.17} />
              <SpinningModel url={car.model} active={active} zoom={1.2} />
            </>
          )}
        </Slide>
      </div>
      <div className="mt-5 flex justify-center gap-[6px]">
        {titles.map((t, i) => (
          <span
            key={t}
            className="h-[12px] rounded-full transition-all"
            style={{
              width: i === page ? 30 : 12,
              background: i === page ? "#808a94" : "#a0acb9",
            }}
          />
        ))}
      </div>
    </>
  );
}
