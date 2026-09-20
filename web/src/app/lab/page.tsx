"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { registerModelText } from "@/lib/ldraw";

const ModelView = dynamic(() => import("@/components/three/ModelView").then((m) => m.ModelView), { ssr: false });

// Dev lab: shows brickify output (public/lab/<name>.ldr) on the turntable,
// so layout changes can be judged by eye. Not linked from the app.
export default function LabPage() {
  return (
    <Suspense>
      <Lab />
    </Suspense>
  );
}

function Lab() {
  const params = useSearchParams();
  const name = params.get("m") ?? "bunny";
  // ?yaw=<degrees> renders a still view at that angle (used by brickify's critic loop)
  const yawDeg = params.get("yaw");
  const [turned, setTurned] = useState<number | null>(null);
  const yaw = turned ?? (yawDeg === null ? undefined : (Number(yawDeg) * Math.PI) / 180);

  // brickify's renderer turns the model from outside instead of reloading the
  // page for every angle: four views cost four frames, not four page loads.
  useEffect(() => {
    const w = window as unknown as { setLabYaw?: (deg: number) => void };
    w.setLabYaw = (deg: number) => setTurned((Number(deg) * Math.PI) / 180);
    return () => {
      delete w.setLabYaw;
    };
  }, []);
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState("");

  useEffect(() => {
    let alive = true;
    fetch(`/lab/${name}.ldr?t=${Date.now()}`)
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(`No /lab/${name}.ldr`))))
      .then((text) => {
        if (!alive) return;
        const parts = text.split("\n").filter((l) => l.startsWith("1 ")).length;
        setInfo(`${parts} parts`);
        setUrl(registerModelText(`lab-${name}-${Date.now()}`, text));
      })
      .catch((e) => alive && setError(String(e.message ?? e)));
    return () => {
      alive = false;
    };
  }, [name]);

  return (
    <main className="fixed inset-0" style={{ background: "linear-gradient(180deg,#8dbbe7 0%,#c9e2f6 100%)" }}>
      {url && <ModelView url={url} mode="display" spin={yaw === undefined ? 0.25 : 0} yaw={yaw} shadow onLoaded={() => document.body.setAttribute("data-model-ready", "1")} />}
      <div className="absolute left-4 top-4 rounded-[10px] bg-white/85 px-3 py-2 text-[14px] font-bold text-ink" style={{ display: yaw === undefined ? undefined : "none" }}>
        {name} · {error ?? info}
        <div className="mt-1 flex gap-2 text-[13px] font-semibold text-blue">
          {["hummingbird", "bunny", "horse", "cow"].map((m) => (
            <Link key={m} href={`/lab?m=${m}`}>
              {m}
            </Link>
          ))}
        </div>
      </div>
    </main>
  );
}
