import Link from "next/link";
import { LogoMark } from "@/components/ui/Logo";

export default function NotFound() {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-parts-bg px-8 text-center">
      <div className="relative">
        <LogoMark size={120} className="rotate-[-18deg] opacity-90 grayscale-[35%]" />
        <span className="absolute -right-6 bottom-1 text-[44px] font-[900] leading-none text-ink/30">?</span>
      </div>
      <h1 className="text-[28px] font-[900] tracking-[-0.02em] text-ink">This piece is missing</h1>
      <p className="max-w-[320px] text-[16px] text-ink-soft">We couldn&apos;t find that page. It might have rolled under the sofa.</p>
      <Link href="/home" className="chunky mt-2 flex h-[58px] w-full max-w-[300px] items-center justify-center rounded-[16px] bg-blue text-[19px] font-bold text-white" style={{ ["--rim" as string]: "#034aa9" } as React.CSSProperties}>
        Go home
      </Link>
    </main>
  );
}
