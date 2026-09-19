"use client";

import { jsPDF } from "jspdf";
import { APP_NAME, LOGO_SMALL_SRC, LOGO_SRC } from "./brand";
import { partImageUrl } from "./data";
import { allParts, modelSnapshot, partThumbnail, prepareModel, renderStep, stepParts, type PartNode } from "./ldraw";
import type { Build } from "./types";

const PAGE = { w: 297, h: 210 }; // A4 landscape, mm
const BG: [number, number, number] = [236, 237, 237];
const RAIL: [number, number, number] = [196, 197, 197];
const INK: [number, number, number] = [36, 36, 36];

async function toDataUrl(src: string) {
  const blob = await (await fetch(src)).blob();
  return new Promise<string>((resolve) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result as string);
    r.readAsDataURL(blob);
  });
}

const imageCache = new Map<string, Promise<string>>();
function partPicture(part: string, colour: number, node: PartNode) {
  const key = `${part}@${colour}`;
  let p = imageCache.get(key);
  if (!p) {
    const local = partImageUrl(part, colour);
    p = local ? toDataUrl(local).catch(() => partThumbnail(node)) : partThumbnail(node);
    imageCache.set(key, p);
  }
  return p;
}

function imageSize(dataUrl: string) {
  return new Promise<{ w: number; h: number }>((resolve) => {
    const img = new Image();
    img.onload = () => resolve({ w: img.naturalWidth, h: img.naturalHeight });
    img.onerror = () => resolve({ w: 1, h: 1 });
    img.src = dataUrl;
  });
}

async function fit(doc: jsPDF, data: string, x: number, y: number, w: number, h: number) {
  const s = await imageSize(data);
  const k = Math.min(w / s.w, h / s.h);
  const dw = s.w * k;
  const dh = s.h * k;
  doc.addImage(data, "PNG", x + (w - dw) / 2, y + (h - dh) / 2, dw, dh, undefined, "FAST");
}

/** Builds the printable manual: cover, parts list, one page per step. */
export async function exportManual(build: Build, onProgress?: (done: number, total: number) => void) {
  const model = await prepareModel(build.model);
  const doc = new jsPDF({ orientation: "landscape", unit: "mm", format: "a4" });
  const total = model.stepCount + 2;
  const bg = () => {
    doc.setFillColor(...BG);
    doc.rect(0, 0, PAGE.w, PAGE.h, "F");
  };

  // Cover
  bg();
  doc.setFillColor(245, 178, 0);
  doc.roundedRect(0, -20, PAGE.w, 70, 16, 16, "F");
  doc.setTextColor(...INK);
  doc.setFont("helvetica", "bold");
  doc.setFontSize(34);
  doc.text(build.name, 18, 30);
  doc.setFontSize(13);
  doc.setFont("helvetica", "normal");
  doc.text(`${build.pieces} pieces  ·  ${model.stepCount} steps  ·  ${build.age}`, 18, 40);
  // Brand block on the yellow band: the mark, name under it.
  const logo = await toDataUrl(LOGO_SRC).catch(() => null);
  if (logo) await fit(doc, logo, PAGE.w - 58, 6, 40, 32);
  doc.setFont("helvetica", "bold");
  doc.setFontSize(11);
  doc.text(APP_NAME, PAGE.w - 38, 44, { align: "center" });
  doc.setFont("helvetica", "normal");
  await fit(doc, await modelSnapshot(build.model, 1400, 1000), 30, 55, PAGE.w - 60, PAGE.h - 70);
  const small = await toDataUrl(LOGO_SMALL_SRC).catch(() => null);
  const footer = async () => {
    doc.setFont("helvetica", "normal");
    doc.setFontSize(9);
    doc.setTextColor(...INK);
    if (small) await fit(doc, small, 10, PAGE.h - 12.6, 6.5, 6.5);
    doc.text(`Made with ${APP_NAME}`, 18, PAGE.h - 8);
  };
  await footer();
  onProgress?.(1, total);

  // Parts list
  doc.addPage();
  bg();
  doc.setFont("helvetica", "bold");
  doc.setFontSize(20);
  doc.text("Pieces", 16, 20);
  const list = allParts(model);
  const cols = 9;
  const cell = { w: (PAGE.w - 32) / cols, h: 30 };
  let i = 0;
  for (const p of list) {
    const row = Math.floor(i / cols);
    const y = 28 + row * cell.h;
    if (y + cell.h > PAGE.h - 8) {
      doc.addPage();
      bg();
      i = 0;
      continue;
    }
    const x = 16 + (i % cols) * cell.w;
    await fit(doc, await partPicture(p.part, p.colour, p.sample), x + 2, y, cell.w - 4, cell.h - 9);
    doc.setFontSize(9);
    doc.setFont("helvetica", "bold");
    doc.text(`${p.count}x`, x + 2, y + cell.h - 3);
    i++;
  }
  onProgress?.(2, total);

  // Steps
  for (let s = 0; s < model.stepCount; s++) {
    doc.addPage();
    bg();
    doc.setFillColor(...RAIL);
    doc.rect(0, 0, 62, PAGE.h, "F");
    doc.setTextColor(...INK);
    doc.setFont("helvetica", "bold");
    doc.setFontSize(30);
    doc.text(String(s + 1), 72, 22);
    const parts = stepParts(model, s);
    let y = 14;
    const slot = Math.min(44, (PAGE.h - 24) / Math.max(1, parts.length));
    for (const p of parts) {
      await fit(doc, await partPicture(p.part, p.colour, p.sample), 10, y, 42, slot - 9);
      doc.setFontSize(11);
      doc.text(`${p.count}x`, 10, y + slot - 3);
      y += slot;
    }
    await fit(doc, renderStep(model, s, 1500, 1100), 66, 18, PAGE.w - 74, PAGE.h - 26);
    doc.setFont("helvetica", "normal");
    doc.setFontSize(9);
    doc.text(`${s + 1} / ${model.stepCount}`, PAGE.w - 10, PAGE.h - 8, { align: "right" });
    await footer();
    onProgress?.(s + 3, total);
    await new Promise((r) => setTimeout(r, 0));
  }

  doc.save(`${build.name.replace(/\s+/g, "-").toLowerCase()}-manual.pdf`);
}
