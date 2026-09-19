"use client";

import Link from "next/link";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { QrCode, Search } from "lucide-react";
import { TabBar } from "@/components/ui/chrome";
import { YellowBucket } from "@/components/ui/controls";
import { LogoTile } from "@/components/ui/Logo";
import { Rings } from "@/components/three/HeroBrick";
import { ModelSnapshot } from "@/components/three/Snapshots";
import { BUILDS, THEMES, getBuild } from "@/lib/data";

const HeroBrick = dynamic(() => import("@/components/three/HeroBrick").then((m) => m.HeroBrick), { ssr: false });

// Home (IMG_1226 / IMG_1227): yellow bucket with the booklet and search,
// promo carousel, then the themes grid above a floating tab bar.
export default function Home() {
  const router = useRouter();
  const [query, setQuery] = useState("");

  return (
    <main className="relative mx-auto min-h-dvh max-w-[520px] pb-36" style={{ background: "linear-gradient(180deg,#90aac5 0%,#b9cde2 40%,#d3e1ef 70%,#e6eef7 100%)" }}>
      <YellowBucket tone="home" className="px-[18px] pb-[26px]">
        <div className="flex justify-center pt-6">
          <Booklet />
        </div>
        <form
          className="chunky mt-6 flex h-[62px] items-center gap-3 rounded-[18px] bg-white pl-5 pr-3"
          style={{ ["--rim" as string]: "#d5d5d5", ["--lift" as string]: "5px" } as React.CSSProperties}
          onSubmit={(e) => {
            e.preventDefault();
            router.push(query.trim() ? `/create?prompt=${encodeURIComponent(query.trim())}` : "/builds");
          }}
        >
          <Search size={26} strokeWidth={2.6} color="#1a1a1a" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Build me a rover" aria-label="Describe a build" className="h-full min-w-0 flex-1 bg-transparent text-[19px] text-ink outline-none placeholder:text-[#949494]" />
          <span className="h-9 w-px bg-[#d9d9d9]" />
          <Link href="/scan" aria-label="Scan bricks" className="grid h-11 w-11 place-items-center">
            <QrCode size={28} strokeWidth={2.2} color="#1a1a1a" />
          </Link>
        </form>
      </YellowBucket>

      <Carousel />

      <h2 className="mt-7 text-center text-[22px] font-[800] tracking-[-0.01em] text-ink">Themes</h2>
      <div className="mt-4 grid grid-cols-2 gap-[18px] px-[18px]">
        {THEMES.map((t) => {
          const build = getBuild(t.model)!;
          return (
            <Link
              key={t.id}
              href={`/builds?theme=${encodeURIComponent(t.id)}`}
              className="chunky relative flex aspect-[0.66] flex-col overflow-hidden rounded-[22px]"
              style={{ background: t.bg, ["--rim" as string]: "rgba(0,0,0,0.12)", ["--lift" as string]: "5px" } as React.CSSProperties}
            >
              <span className="px-4 pt-5 text-center text-[28px] font-[900] leading-none tracking-[-0.03em]" style={{ color: t.ink, fontStyle: t.id === "Vehicles" ? "italic" : undefined }}>
                {t.label}
              </span>
              <ModelSnapshot url={build.model} alt={build.name} width={420} height={520} className="mt-auto h-[78%] w-full" />
            </Link>
          );
        })}
      </div>
      <TabBar />
    </main>
  );
}

/** Blue instruction booklet (stands where the set box sits in IMG_1226). */
function Booklet() {
  return (
    <div className="relative h-[172px] w-[256px]" style={{ perspective: 600 }}>
      <div className="absolute inset-x-0 bottom-0 h-[150px] rounded-[6px]" style={{ background: "linear-gradient(180deg,#3d8ae6,#2e73d2)", transform: "rotateX(12deg)", transformOrigin: "bottom", boxShadow: "0 12px 0 #2461b8, 0 22px 28px rgba(120,80,0,0.28)" }}>
        <div className="absolute left-[16px] top-[14px]">
          <LogoTile size={44} />
        </div>
        <div className="absolute left-[74px] top-[22px] h-[20px] w-[74px] rounded-full bg-white/35" />
        <div className="absolute left-[16px] top-[74px] h-[40px] w-[86px] rounded-[8px] border-[4px] border-white" />
        <div className="absolute left-[28px] top-[84px] h-[6px] w-[62px] rounded-full bg-white" />
        <div className="absolute left-[28px] top-[96px] h-[6px] w-[40px] rounded-full bg-white" />
        <div className="absolute left-[16px] top-[62px] h-[6px] w-[64px] rounded-full bg-white/35" />
      </div>
    </div>
  );
}

function Carousel() {
  const ref = useRef<HTMLDivElement>(null);
  const [page, setPage] = useState(0);
  const lunar = BUILDS.find((b) => b.id === "lunar")!;
  const slides = [
    {
      href: "/scan",
      title: "Scan your pile",
      sub: "Loose bricks in. A build out.",
      bg: "linear-gradient(180deg,#050505,#1c1c1c)",
      art: (
        <div className="absolute inset-0">
          <div className="absolute right-[-10px] top-1/2 h-[260px] w-[260px] -translate-y-1/2">
            <Rings size={250} />
            <HeroBrick className="!absolute inset-0" />
          </div>
        </div>
      ),
    },
    {
      href: `/build/${lunar.id}`,
      title: lunar.name,
      sub: `${lunar.pieces} pieces. Tonight's pick.`,
      bg: "linear-gradient(180deg,#3a1780,#6e13bc)",
      art: <ModelSnapshot url={lunar.model} alt={lunar.name} width={560} height={420} className="absolute right-[-14px] top-3 h-[74%] w-[80%]" />,
    },
    {
      href: "/builds",
      title: "Your manual, printed",
      sub: "Every step, ready for paper.",
      bg: "linear-gradient(180deg,#0b4cb5,#005ad2)",
      art: <ModelSnapshot url={BUILDS[0].model} alt="" width={560} height={420} className="absolute right-[-10px] top-4 h-[70%] w-[78%]" />,
    },
  ];
  return (
    <>
      <div
        ref={ref}
        className="no-scrollbar mt-8 flex snap-x snap-mandatory gap-3 overflow-x-auto px-[10px] scroll-px-[10px]"
        onScroll={(e) => {
          const el = e.currentTarget;
          setPage(Math.round(el.scrollLeft / (el.firstElementChild as HTMLElement).offsetWidth));
        }}
      >
        {slides.map((s) => (
          <Link key={s.title} href={s.href} className="relative h-[272px] w-[calc(100%-38px)] shrink-0 snap-start overflow-hidden rounded-[24px]" style={{ background: s.bg, boxShadow: "0 6px 0 rgba(0,0,0,0.12)" }}>
            {s.art}
            <div className="absolute bottom-6 left-6 right-24 text-white">
              <div className="text-[22px] font-[800] leading-tight tracking-[-0.01em]">{s.title}</div>
              <div className="mt-1 text-[16px] font-medium text-white/90">{s.sub}</div>
            </div>
          </Link>
        ))}
      </div>
      <div className="mt-5 flex justify-center gap-[6px]">
        {slides.map((s, i) => (
          <span key={s.title} className="h-[12px] rounded-full transition-all" style={{ width: i === page ? 30 : 12, background: i === page ? "#808a94" : "#a0acb9" }} />
        ))}
      </div>
    </>
  );
}
