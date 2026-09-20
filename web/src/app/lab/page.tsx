"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Sparkles } from "lucide-react";
import { registerModelText } from "@/lib/ldraw";
import { IconTile } from "@/components/ui/controls";
import { loadLdrSession } from "@/lib/live";
import { refreshTable } from "@/lib/editor";

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
  const [text, setText] = useState<string | null>(null);
  const [seeding, setSeeding] = useState(false);
  const router = useRouter();

  useEffect(() => {
    let alive = true;
    fetch(`/lab/${name}.ldr?t=${Date.now()}`)
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(`No /lab/${name}.ldr`))))
      .then((body) => {
        if (!alive) return;
        const parts = body.split("\n").filter((l) => l.startsWith("1 ")).length;
        setInfo(`${parts} parts`);
        setText(body);
        setUrl(registerModelText(`lab-${name}-${Date.now()}`, body));
      })
      .catch((e) => alive && setError(String(e.message ?? e)));
    return () => {
      alive = false;
    };
  }, [name]);

  // Same "Change it" as the build screens: seed a real session from this file
  // and hand over to the editor. Nothing is faked if the builder is offline.
  const change = async () => {
    if (!text || seeding) return;
    setSeeding(true);
    try {
      await loadLdrSession({ name, ldr: text, source: `lab/${name}` });
      await refreshTable();
      router.push("/build/live/view?edit=1");
    } catch {
      setError("Changing a model needs the builder running, and I can't reach it right now.");
    } finally {
      setSeeding(false);
    }
  };

  return (
    <main className="fixed inset-0" style={{ background: "linear-gradient(180deg,#8dbbe7 0%,#c9e2f6 100%)" }}>
      {url && <ModelView url={url} mode="display" spin={yaw === undefined ? 0.25 : 0} yaw={yaw} shadow onLoaded={() => document.body.setAttribute("data-model-ready", "1")} />}
      {yaw === undefined && url && (
        <div className="absolute right-4 top-4">
          <IconTile tone="white" label="Change it" size={56} onClick={change} disabled={seeding || !text}>
            <Sparkles size={26} strokeWidth={2.2} />
          </IconTile>
        </div>
      )}
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
