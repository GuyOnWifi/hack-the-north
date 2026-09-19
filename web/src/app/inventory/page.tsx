"use client";

import { play } from "@/lib/sound";

import { useMemo, useState } from "react";
import { ArrowLeft, Check, Minus, Plus, Search, Trash2, X } from "lucide-react";
import { ChunkyButton, IconTile, YellowBucket } from "@/components/ui/controls";
import { IsoBrick, BrickGlyph } from "@/components/ui/IsoBrick";
import { PartsScroller } from "@/components/PartsScroller";
import { PartImage } from "@/components/three/Snapshots";
import { PilePhoto } from "@/components/PilePhoto";
import { BUILDS, colourHex, colourName } from "@/lib/data";
import { loadSampleSession, removeItem, setSession, updateItem, useSession } from "@/lib/store";
import { sendInventory } from "@/lib/live";
import { useRouter } from "next/navigation";
import type { Confidence, InventoryItem } from "@/lib/types";

type Filter = "all" | "review" | "unknown";

const CHIP: Record<Confidence, { bg: string; ring: string; label: string }> = {
  confident: { bg: "#2fbf5b", ring: "#2fbf5b", label: "Confident" },
  review: { bg: "#ffb400", ring: "#ffb400", label: "Needs review" },
  unknown: { bg: "#9e9e9e", ring: "#9e9e9e", label: "Unknown" },
};

// Inventory review: what the scan found, sorted like a parts page, with
// confidence chips; tap any piece to see the evidence and fix it.
export default function Inventory() {
  const session = useSession();
  const [filter, setFilter] = useState<Filter>("all");
  const [open, setOpen] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [sending, setSending] = useState(false);
  const router = useRouter();
  const items = session.inventory;
  const total = items.reduce((n, i) => n + i.count, 0);
  const review = items.filter((i) => i.status === "review").length;
  const unknown = items.filter((i) => i.status === "unknown").length;
  const shown = items.filter((i) => filter === "all" || i.status === filter);
  const current = items.find((i) => i.id === open) ?? null;

  if (!items.length) return <Empty onAdd={() => setAdding(true)} adding={adding} onClose={() => setAdding(false)} />;

  return (
    <main className="fixed inset-0 mx-auto flex max-w-[1100px] flex-col bg-parts-bg">
      <YellowBucket className="px-[18px] pb-5">
        <div className="flex items-center gap-4 pt-4">
          <IconTile tone="white" label="Back" href="/home" size={56}>
            <ArrowLeft size={28} strokeWidth={2.8} />
          </IconTile>
          <div className="min-w-0 flex-1">
            <h1 className="text-[26px] font-[900] leading-none tracking-[-0.02em] text-ink">{total} pieces found</h1>
            <p className="mt-1 text-[15px] font-semibold text-ink/70">{review + unknown ? `${review + unknown} need a quick look` : "All checked. Nice."}</p>
          </div>
          <IconTile tone="white" label="Add a piece" size={56} onClick={() => setAdding(true)}>
            <Plus size={30} strokeWidth={2.8} />
          </IconTile>
        </div>
        <div className="mt-4 flex gap-2">
          <FilterChip active={filter === "all"} onClick={() => setFilter("all")} label={`All ${items.length}`} />
          <FilterChip active={filter === "review"} onClick={() => setFilter("review")} label={`Review ${review}`} dot="#ffb400" />
          <FilterChip active={filter === "unknown"} onClick={() => setFilter("unknown")} label={`Unknown ${unknown}`} dot="#9e9e9e" />
        </div>
      </YellowBucket>

      <div className="flex min-h-0 flex-1 flex-col pt-4">
        {shown.length === 0 ? (
          <div className="grid flex-1 place-items-center text-center">
            <div>
              <Check size={40} className="mx-auto" color="#1f7a3a" strokeWidth={3} />
              <p className="mt-2 text-[17px] font-bold text-ink">Nothing left to review</p>
              <button onClick={() => setFilter("all")} className="mt-1 text-[15px] font-bold text-blue">
                Show all pieces
              </button>
            </div>
          </div>
        ) : (
          <PartsScroller
            size={62}
            cells={shown.map((it) => ({
              key: it.id,
              part: it.part,
              colour: it.colour,
              count: it.count,
              ring: it.status === "confident" ? undefined : `${CHIP[it.status].ring}`,
              badge: <ConfidenceDot status={it.status} />,
              onClick: () => setOpen(it.id),
            }))}
          />
        )}
      </div>

      <div className="px-[18px] pt-2" style={{ paddingBottom: "calc(var(--safe-bottom) + 16px)" }}>
        <ChunkyButton
          variant="yellow"
          icon={<BrickGlyph size={34} />}
          disabled={sending}
          onClick={async () => {
            setSending(true);
            await sendInventory(items);
            router.push("/builds");
          }}
        >
          {sending ? "Packing your bricks…" : "Find builds"}
        </ChunkyButton>
      </div>

      {current && <Evidence item={current} all={items} onClose={() => setOpen(null)} />}
      {adding && <AddSheet onClose={() => setAdding(false)} />}
    </main>
  );
}

function FilterChip({ active, label, onClick, dot }: { active: boolean; label: string; onClick: () => void; dot?: string }) {
  return (
    <button onClick={onClick} className="flex h-10 items-center gap-2 rounded-full px-4 text-[15px] font-[800] transition-colors" style={{ background: active ? "#1a1a1a" : "rgba(255,255,255,0.7)", color: active ? "#fff" : "#1a1a1a" }}>
      {dot && <span className="h-2.5 w-2.5 rounded-full" style={{ background: dot }} />}
      {label}
    </button>
  );
}

function ConfidenceDot({ status }: { status: Confidence }) {
  const c = CHIP[status];
  return (
    <span className="grid h-6 w-6 place-items-center rounded-full border-2 border-white shadow" style={{ background: c.bg }} aria-label={c.label}>
      {status === "confident" ? <Check size={13} color="#fff" strokeWidth={3.5} /> : <span className="text-[13px] font-[900] leading-none text-white">?</span>}
    </span>
  );
}

function Sheet({ children, onClose, title }: { children: React.ReactNode; onClose: () => void; title: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/45" style={{ animation: "fade-in 150ms ease-out" }} onClick={onClose}>
      <div
        className="no-scrollbar max-h-[88dvh] w-full max-w-[560px] overflow-auto rounded-t-[28px] bg-page px-5 pt-3"
        style={{ animation: "sheet-up 260ms cubic-bezier(.2,.9,.3,1)", paddingBottom: "calc(var(--safe-bottom) + 20px)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mx-auto mb-3 h-[5px] w-12 rounded-full bg-black/15" />
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="min-w-0">{title}</div>
          <button onClick={onClose} aria-label="Close" className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-black/5 active:scale-95">
            <X size={22} strokeWidth={2.6} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

/** Evidence panel: the crop it came from, confidence, top-3 one-tap swaps. */
function Evidence({ item, all, onClose }: { item: InventoryItem; all: InventoryItem[]; onClose: () => void }) {
  const session = useSession();
  const pct = Math.round(item.confidence * 100);
  const c = CHIP[item.status];
  return (
    <Sheet
      onClose={onClose}
      title={
        <div className="flex items-center gap-3">
          <PartImage part={item.part} colour={item.colour} size={64} />
          <div className="min-w-0">
            <div className="truncate text-[19px] font-[800] leading-tight text-ink">{item.title}</div>
            <div className="mt-0.5 flex items-center gap-1.5 text-[14px] font-semibold text-ink-soft">
              <span className="h-3 w-3 rounded-full border border-black/15" style={{ background: colourHex(item.colour) }} />
              {colourName(item.colour)} · #{item.part}
            </div>
          </div>
        </div>
      }
    >
      <div className="grid grid-cols-[1fr_auto] items-stretch gap-3">
        <div className="relative overflow-hidden rounded-[18px] bg-white">
          {session.photo ? (
            <div className="relative aspect-[4/3] overflow-hidden">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={session.photo}
                alt="Where we saw it"
                className="absolute max-w-none"
                style={{ width: `${100 / Math.max(item.crop.w, 0.05) / 1.6}%`, left: `${50 - (item.crop.x + item.crop.w / 2) * (100 / Math.max(item.crop.w, 0.05) / 1.6)}%`, top: `${50 - (item.crop.y + item.crop.h / 2) * (100 / Math.max(item.crop.w, 0.05) / 1.6) * 0.75}%` }}
              />
            </div>
          ) : (
            <PilePhoto items={all} focus={item.crop} className="aspect-[4/3]" />
          )}
          <div className="pointer-events-none absolute left-1/2 top-1/2 h-[62%] w-[62%] -translate-x-1/2 -translate-y-1/2 rounded-[10px] border-[3px]" style={{ borderColor: c.ring }} />
          <span className="absolute left-2 top-2 rounded-full bg-black/55 px-2 py-0.5 text-[12px] font-bold text-white">From your photo</span>
        </div>
        <div className="flex w-[104px] flex-col items-center justify-center rounded-[18px] bg-white px-2 text-center">
          <span className="text-[30px] font-[900] leading-none text-ink">{pct}%</span>
          <span className="mt-1 text-[12px] font-bold" style={{ color: item.status === "confident" ? "#1f7a3a" : item.status === "review" ? "#b27a00" : "#6b6b6b" }}>
            {c.label}
          </span>
          <div className="mt-3 flex items-center gap-1">
            <button aria-label="One fewer" onClick={() => (item.count > 1 ? updateItem(item.id, { count: item.count - 1 }) : removeItem(item.id))} className="grid h-8 w-8 place-items-center rounded-full bg-page active:scale-90">
              <Minus size={16} strokeWidth={3} />
            </button>
            <span className="w-6 text-[18px] font-[900]">{item.count}</span>
            <button aria-label="One more" onClick={() => updateItem(item.id, { count: item.count + 1 })} className="grid h-8 w-8 place-items-center rounded-full bg-page active:scale-90">
              <Plus size={16} strokeWidth={3} />
            </button>
          </div>
        </div>
      </div>

      {item.alternatives.length > 0 && (
        <>
          <h3 className="mb-2 mt-5 text-[15px] font-[800] text-ink">Is it one of these?</h3>
          <div className="grid grid-cols-3 gap-2">
            {item.alternatives.map((a) => (
              <button
                key={a.part}
                onClick={() => {
                  updateItem(item.id, { part: a.part, title: a.title, status: "confident", confidence: 1, alternatives: [] });
                  play("connect");
                  onClose();
                }}
                className="chunky flex flex-col items-center rounded-[16px] bg-white px-1 pb-2 pt-1 text-center"
                style={{ ["--rim" as string]: "#d5d5d5", ["--lift" as string]: "4px" } as React.CSSProperties}
              >
                <PartImage part={a.part} colour={a.colour} size={64} />
                <span className="line-clamp-2 text-[12px] font-bold leading-tight text-ink">{a.title}</span>
                <span className="mt-0.5 text-[11px] font-semibold text-ink-soft">{Math.round(a.confidence * 100)}%</span>
              </button>
            ))}
          </div>
        </>
      )}

      <div className="mt-5 flex gap-3">
        <ChunkyButton
          variant="white"
          className="!text-[16px]"
          onClick={() => {
            removeItem(item.id);
            onClose();
          }}
          icon={<Trash2 size={20} color="#c0182b" />}
          style={{ color: "#c0182b" }}
        >
          Not a brick
        </ChunkyButton>
        <ChunkyButton
          variant="blue"
          className="!text-[16px]"
          onClick={() => {
            updateItem(item.id, { status: "confident", confidence: Math.max(item.confidence, 0.99) });
            play("connect");
            onClose();
          }}
          icon={<Check size={22} strokeWidth={3} />}
        >
          Looks right
        </ChunkyButton>
      </div>
    </Sheet>
  );
}

const CATALOG = (() => {
  const seen = new Map<string, { part: string; title: string; colours: Set<number> }>();
  for (const b of BUILDS)
    for (const p of b.parts) {
      const e = seen.get(p.part) ?? { part: p.part, title: p.title, colours: new Set<number>() };
      e.colours.add(p.colour);
      seen.set(p.part, e);
    }
  return [...seen.values()].filter((p) => !/minifig|sticker/i.test(p.title));
})();

const SETS: Record<string, string> = { "889": "radar-truck", "1621": "lunar" };

/** Add by typing (typeahead) or import a whole set by number. */
function AddSheet({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<"part" | "set">("part");
  const [q, setQ] = useState("");
  const [pick, setPick] = useState<(typeof CATALOG)[number] | null>(null);
  const [colour, setColour] = useState<number | null>(null);
  const [count, setCount] = useState(1);
  const [setNo, setSetNo] = useState("");
  const [setMsg, setSetMsg] = useState<string | null>(null);
  const results = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return CATALOG.slice(0, 8);
    return CATALOG.filter((p) => p.title.toLowerCase().includes(s) || p.part.includes(s)).slice(0, 8);
  }, [q]);

  const add = () => {
    if (!pick || colour === null) return;
    setSession((sess) => {
      const existing = sess.inventory.find((i) => i.part === pick.part && i.colour === colour);
      if (existing) return { inventory: sess.inventory.map((i) => (i === existing ? { ...i, count: i.count + count } : i)), scanned: true };
      const item: InventoryItem = { id: `add-${Date.now()}`, part: pick.part, colour, title: pick.title, count, status: "confident", confidence: 1, crop: { x: 0.4, y: 0.4, w: 0.12, h: 0.12 }, alternatives: [] };
      return { inventory: [...sess.inventory, item], scanned: true };
    });
    play("connect");
    onClose();
  };

  const importSet = () => {
    const build = BUILDS.find((b) => b.id === SETS[setNo.trim().replace(/-1$/, "")]);
    if (!build) {
      setSetMsg("We don't know that set yet. Try 889 or 1621.");
      return;
    }
    setSession((sess) => {
      const inv = [...sess.inventory];
      for (const p of build.parts) {
        const i = inv.findIndex((x) => x.part === p.part && x.colour === p.colour);
        if (i >= 0) inv[i] = { ...inv[i], count: inv[i].count + p.count };
        else inv.push({ id: `set-${p.part}-${p.colour}`, part: p.part, colour: p.colour, title: p.title, count: p.count, status: "confident", confidence: 1, crop: { x: 0.4, y: 0.4, w: 0.12, h: 0.12 }, alternatives: [] });
      }
      return { inventory: inv, scanned: true };
    });
    play("connect", { volume: 0.6 });
    onClose();
  };

  return (
    <Sheet onClose={onClose} title={<span className="text-[22px] font-[900] tracking-[-0.02em] text-ink">Add pieces</span>}>
      <div className="mb-4 flex gap-2">
        <FilterChip active={tab === "part"} onClick={() => setTab("part")} label="A piece" />
        <FilterChip active={tab === "set"} onClick={() => setTab("set")} label="A whole set" />
      </div>
      {tab === "part" ? (
        <>
          <label className="flex h-[54px] items-center gap-3 rounded-[16px] bg-white px-4 shadow-[0_3px_0_#d5d5d5]">
            <Search size={22} strokeWidth={2.6} />
            <input autoFocus value={q} onChange={(e) => { setQ(e.target.value); setPick(null); }} placeholder="Brick 2 x 4, wheel, 3001…" className="min-w-0 flex-1 bg-transparent text-[17px] outline-none placeholder:text-[#9a9a9a]" />
          </label>
          {!pick ? (
            <ul className="mt-3 flex flex-col gap-1">
              {results.length === 0 && <li className="py-6 text-center text-[15px] text-ink-soft">No pieces match &ldquo;{q}&rdquo;</li>}
              {results.map((p) => (
                <li key={p.part}>
                  <button onClick={() => { setPick(p); setColour([...p.colours][0]); }} className="flex w-full items-center gap-3 rounded-[14px] px-2 py-1.5 text-left active:bg-black/5">
                    <PartImage part={p.part} colour={[...p.colours][0]} size={44} />
                    <span className="min-w-0 flex-1 truncate text-[16px] font-semibold text-ink">{p.title}</span>
                    <span className="text-[13px] text-ink-soft">#{p.part}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <div className="mt-4">
              <div className="flex items-center gap-3 rounded-[18px] bg-white p-3">
                <PartImage part={pick.part} colour={colour ?? 0} size={72} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[17px] font-[800] text-ink">{pick.title}</div>
                  <div className="text-[14px] text-ink-soft">{colour !== null ? colourName(colour) : "Pick a colour"}</div>
                </div>
                <div className="flex items-center gap-1">
                  <button aria-label="Fewer" onClick={() => setCount((c) => Math.max(1, c - 1))} className="grid h-9 w-9 place-items-center rounded-full bg-page">
                    <Minus size={18} strokeWidth={3} />
                  </button>
                  <span className="w-7 text-center text-[19px] font-[900]">{count}</span>
                  <button aria-label="More" onClick={() => setCount((c) => c + 1)} className="grid h-9 w-9 place-items-center rounded-full bg-page">
                    <Plus size={18} strokeWidth={3} />
                  </button>
                </div>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {[...new Set([...pick.colours, 0, 1, 4, 14, 15, 71, 72])].map((code) => (
                  <button key={code} aria-label={colourName(code)} onClick={() => setColour(code)} className="h-10 w-10 rounded-full border-[3px] transition-transform active:scale-90" style={{ background: colourHex(code), borderColor: colour === code ? "#1a1a1a" : "#ffffff" }} />
                ))}
              </div>
              <ChunkyButton variant="blue" className="mt-5" onClick={add}>
                Add {count} {count === 1 ? "piece" : "pieces"}
              </ChunkyButton>
            </div>
          )}
        </>
      ) : (
        <>
          <label className="flex h-[54px] items-center gap-3 rounded-[16px] bg-white px-4 shadow-[0_3px_0_#d5d5d5]">
            <span className="text-[16px] font-bold text-ink-soft">Set</span>
            <input autoFocus inputMode="numeric" value={setNo} onChange={(e) => { setSetNo(e.target.value); setSetMsg(null); }} placeholder="889" className="min-w-0 flex-1 bg-transparent text-[19px] font-bold outline-none placeholder:text-[#b5b5b5]" />
          </label>
          <p className="mt-2 min-h-5 px-1 text-[14px]" style={{ color: setMsg ? "#c0182b" : "#5c5c5c" }}>
            {setMsg ?? "Everything from the set's box gets added to your pile."}
          </p>
          <ChunkyButton variant="blue" className="mt-3" onClick={importSet} disabled={!setNo.trim()}>
            Import set
          </ChunkyButton>
        </>
      )}
    </Sheet>
  );
}

function Empty({ onAdd, adding, onClose }: { onAdd: () => void; adding: boolean; onClose: () => void }) {
  return (
    <main className="mx-auto flex min-h-dvh max-w-[520px] flex-col bg-parts-bg">
      <YellowBucket className="px-[18px] pb-6">
        <div className="flex items-center gap-4 pt-4">
          <IconTile tone="white" label="Back" href="/home" size={56}>
            <ArrowLeft size={28} strokeWidth={2.8} />
          </IconTile>
          <h1 className="text-[26px] font-[900] tracking-[-0.02em] text-ink">My bricks</h1>
        </div>
      </YellowBucket>
      <div className="flex flex-1 flex-col items-center justify-center gap-3 px-8 text-center">
        <div className="relative mb-2 h-[120px] w-[180px]">
          <div className="absolute left-2 top-8"><IsoBrick w={2} d={2} h={3} color="#b4b4b4" size={86} /></div>
          <div className="absolute right-4 top-0"><IsoBrick w={2} d={1} h={3} color="#c7c7c7" size={66} /></div>
          <div className="absolute bottom-0 right-10"><IsoBrick w={1} d={1} h={1} round color="#a9a9a9" size={40} /></div>
        </div>
        <p className="text-[22px] font-[900] tracking-[-0.02em] text-ink">No bricks yet</p>
        <p className="max-w-[300px] text-[16px] text-ink-soft">Snap a photo of your pile and we&apos;ll count every piece.</p>
        <div className="mt-4 flex w-full max-w-[340px] flex-col gap-3">
          <ChunkyButton variant="yellow" href="/scan" icon={<BrickGlyph size={34} />}>
            Scan my bricks
          </ChunkyButton>
          <ChunkyButton variant="white" onClick={loadSampleSession}>
            Try a sample pile
          </ChunkyButton>
          <button onClick={onAdd} className="mt-1 text-[16px] font-bold text-blue">
            Add pieces by hand
          </button>
        </div>
      </div>
      {adding && <AddSheet onClose={onClose} />}
    </main>
  );
}
