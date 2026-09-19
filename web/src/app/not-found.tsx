import Link from "next/link";
import { IsoBrick } from "@/components/ui/IsoBrick";

export default function NotFound() {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-parts-bg px-8 text-center">
      <div className="flex items-end gap-2">
        <IsoBrick w={2} d={1} h={3} color="#9a9a9a" size={70} />
        <IsoBrick w={1} d={1} h={3} color="#b5b5b5" size={40} />
      </div>
      <h1 className="text-[28px] font-[900] tracking-[-0.02em] text-ink">This piece is missing</h1>
      <p className="max-w-[320px] text-[16px] text-ink-soft">We couldn&apos;t find that page. It might have rolled under the sofa.</p>
      <Link href="/home" className="chunky mt-2 flex h-[58px] w-full max-w-[300px] items-center justify-center rounded-[16px] bg-blue text-[19px] font-bold text-white" style={{ ["--rim" as string]: "#034aa9" } as React.CSSProperties}>
        Go home
      </Link>
    </main>
  );
}
