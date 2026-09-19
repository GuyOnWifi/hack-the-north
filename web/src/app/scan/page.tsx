"use client";

import { play } from "@/lib/sound";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, Check, ImagePlus, RotateCcw } from "lucide-react";
import { ChunkyButton, IconTile, YellowBucket } from "@/components/ui/controls";
import { loadSampleSession, setSession } from "@/lib/store";

type CamState = "starting" | "live" | "denied" | "unavailable";

const TIPS = ["Plain background", "Spread them out", "Scale card in view"];

// Capture: live camera under a guided overlay, with upload as the fallback
// whenever the camera is missing or refused. Built for one-handed portrait use.
export default function Scan() {
  const router = useRouter();
  const video = useRef<HTMLVideoElement>(null);
  const file = useRef<HTMLInputElement>(null);
  const [cam, setCam] = useState<CamState>("starting");
  const [shot, setShot] = useState<string | null>(null);

  useEffect(() => {
    let stream: MediaStream | null = null;
    let cancelled = false;
    const media = navigator.mediaDevices?.getUserMedia
      ? navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices)
      : () => Promise.reject(new DOMException("No camera API", "NotFoundError"));
    media({ video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1440 } }, audio: false })
      .then((s) => {
        if (cancelled) return s.getTracks().forEach((t) => t.stop());
        stream = s;
        if (video.current) {
          video.current.srcObject = s;
          video.current.play().catch(() => {});
        }
        setCam("live");
      })
      .catch((e: DOMException) => setCam(e?.name === "NotAllowedError" ? "denied" : "unavailable"));
    return () => {
      cancelled = true;
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  const capture = useCallback(() => {
    const v = video.current;
    if (!v || !v.videoWidth) return;
    setShot(downscale(v, v.videoWidth, v.videoHeight));
    play("connect");
  }, []);

  const onFile = (f: File | undefined) => {
    if (!f) return;
    const img = new Image();
    img.onload = () => setShot(downscale(img, img.naturalWidth, img.naturalHeight));
    img.src = URL.createObjectURL(f);
  };

  const use = () => {
    setSession({ photo: shot, inventory: [], scanned: false });
    router.push("/scan/processing");
  };

  const noCamera = cam === "denied" || cam === "unavailable";

  return (
    <main className="fixed inset-0 flex flex-col bg-[#111]">
      <input ref={file} type="file" accept="image/*" capture="environment" className="hidden" onChange={(e) => onFile(e.target.files?.[0])} />

      <YellowBucket className="px-[18px] pb-5">
        <div className="flex items-center gap-4 pt-4">
          <IconTile tone="white" label="Back" href="/home" size={56}>
            <ArrowLeft size={28} strokeWidth={2.8} />
          </IconTile>
          <h1 className="text-[26px] font-[900] leading-none tracking-[-0.02em] text-ink">{shot ? "Looks good?" : "Scan your bricks"}</h1>
        </div>
        <ul className="no-scrollbar -mx-[18px] mt-4 flex gap-2 overflow-x-auto px-[18px]">
          {TIPS.map((t) => (
            <li key={t} className="flex shrink-0 items-center gap-1.5 rounded-full bg-white/70 px-3 py-1.5 text-[14px] font-bold text-ink">
              <Check size={16} strokeWidth={3} color="#1f7a3a" /> {t}
            </li>
          ))}
        </ul>
      </YellowBucket>

      <section className="relative -mt-10 flex-1 overflow-hidden">
        {/* Camera / preview */}
        {shot ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={shot} alt="Your photo" className="absolute inset-0 h-full w-full object-cover" />
        ) : (
          <video ref={video} playsInline muted className="absolute inset-0 h-full w-full object-cover" style={{ opacity: cam === "live" ? 1 : 0, transition: "opacity 300ms" }} />
        )}

        {!shot && cam === "starting" && (
          <div className="absolute inset-0 grid place-items-center">
            <div className="h-10 w-10 animate-spin rounded-full border-[4px] border-white/25 border-t-white" />
          </div>
        )}

        {!shot && noCamera && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 px-8 pt-10 text-center text-white">
            <div className="grid h-20 w-20 place-items-center rounded-[22px] bg-white/10">
              <ImagePlus size={40} />
            </div>
            <p className="text-[20px] font-[800]">{cam === "denied" ? "Camera access is off" : "No camera here"}</p>
            <p className="max-w-[300px] text-[15px] text-white/70">{cam === "denied" ? "Allow the camera in your browser settings, or pick a photo of your bricks instead." : "Pick a photo of your bricks instead."}</p>
            <ChunkyButton variant="yellow" className="mt-2 max-w-[280px]" onClick={() => file.current?.click()} icon={<ImagePlus size={24} />}>
              Choose a photo
            </ChunkyButton>
          </div>
        )}

        {/* Guide overlay */}
        {!shot && cam === "live" && <Guide />}
      </section>

      {/* Controls */}
      <footer className="relative flex items-center justify-between px-8 pt-5" style={{ paddingBottom: "calc(var(--safe-bottom) + 22px)" }}>
        {shot ? (
          <div className="flex w-full gap-3">
            <ChunkyButton variant="white" onClick={() => setShot(null)} icon={<RotateCcw size={22} strokeWidth={2.6} />}>
              Retake
            </ChunkyButton>
            <ChunkyButton variant="blue" onClick={use}>
              Use photo
            </ChunkyButton>
          </div>
        ) : (
          <>
            <IconTile tone="glass" label="Upload a photo" size={56} onClick={() => file.current?.click()} style={{ background: "rgba(255,255,255,0.14)" }}>
              <ImagePlus size={28} />
            </IconTile>
            <button
              onClick={capture}
              disabled={cam !== "live"}
              style={{ visibility: noCamera ? "hidden" : "visible", background: "#ffd502", ["--rim" as string]: "#b89700", ["--lift" as string]: "6px" } as React.CSSProperties}
              aria-label="Take photo"
              className="chunky grid h-[84px] w-[84px] place-items-center rounded-full disabled:opacity-40"
            >
              <span className="h-[62px] w-[62px] rounded-full border-[4px] border-white/90" />
            </button>
            <Link
              href="/inventory"
              onClick={() => loadSampleSession()}
              className="grid h-14 w-14 place-items-center rounded-[14px] bg-white/14 text-center text-[11px] font-[800] leading-tight text-white"
              style={{ background: "rgba(255,255,255,0.14)" }}
            >
              Try a
              <br />
              sample
            </Link>
          </>
        )}
      </footer>
    </main>
  );
}

function downscale(source: CanvasImageSource, w: number, h: number, max = 1600) {
  const k = Math.min(1, max / Math.max(w, h));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(w * k);
  canvas.height = Math.round(h * k);
  canvas.getContext("2d")!.drawImage(source, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.85);
}

/** Framing guide: bracketed capture area and the scale-card slot. */
function Guide() {
  const corner = "absolute h-10 w-10 border-white";
  return (
    <div className="pointer-events-none absolute inset-x-6 bottom-6 top-16">
      <div className="absolute inset-0 rounded-[24px] shadow-[0_0_0_9999px_rgba(0,0,0,0.35)]" />
      <span className={`${corner} left-0 top-0 rounded-tl-[24px] border-l-[5px] border-t-[5px]`} />
      <span className={`${corner} right-0 top-0 rounded-tr-[24px] border-r-[5px] border-t-[5px]`} />
      <span className={`${corner} bottom-0 left-0 rounded-bl-[24px] border-b-[5px] border-l-[5px]`} />
      <span className={`${corner} bottom-0 right-0 rounded-br-[24px] border-b-[5px] border-r-[5px]`} />
      <div className="absolute bottom-4 left-4 grid h-[62px] w-[98px] place-items-center rounded-[10px] border-[3px] border-dashed border-[#ffd502] bg-black/20 text-center text-[11px] font-[800] leading-tight text-[#ffd502]">
        SCALE
        <br />
        CARD
      </div>
    </div>
  );
}
