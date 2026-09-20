"use client";

import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, ChevronsDown, ChevronsUp, Copy, Palette, Plus, RotateCw, Trash2 } from "lucide-react";
import { IconTile } from "@/components/ui/controls";
import type { ScreenDir } from "@/lib/editor";

// The Unity-style toolbar: one row of white tiles along the top of the stage.
// Every tile is data-sound="off" — the edit itself plays the one sound when the
// server answers (taste rule 1), so the tap must not stack another on top.

export interface ToolbarProps {
  /** Something is selected: the move/turn/paint tiles do something. */
  active: boolean;
  pending: boolean;
  portrait: boolean;
  onNudge: (dir: ScreenDir) => void;
  onRaise: (plates: number) => void;
  onRotate: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
  onColours: () => void;
  onParts: () => void;
  colours: boolean;
  parts: boolean;
}

export function EditToolbar({ active, pending, portrait, onNudge, onRaise, onRotate, onDuplicate, onDelete, onColours, onParts, colours, parts }: ToolbarProps) {
  const size = portrait ? 44 : 48;
  const icon = portrait ? 20 : 22;
  const tile = (label: string, on: boolean, action: () => void, child: React.ReactNode, lit = false) => (
    <IconTile
      key={label}
      tone="white"
      label={label}
      size={size}
      data-sound="off"
      disabled={!on || pending}
      onClick={action}
      style={{ opacity: !on || pending ? 0.4 : 1, outline: lit ? "3px solid #9840b0" : undefined, outlineOffset: -3 }}
    >
      {child}
    </IconTile>
  );

  return (
    <div className="no-scrollbar flex max-w-full items-center gap-2 overflow-x-auto px-1 py-1">
      {tile("Move left", active, () => onNudge("left"), <ArrowLeft size={icon} strokeWidth={2.4} />)}
      {tile("Move away", active, () => onNudge("up"), <ArrowUp size={icon} strokeWidth={2.4} />)}
      {tile("Move closer", active, () => onNudge("down"), <ArrowDown size={icon} strokeWidth={2.4} />)}
      {tile("Move right", active, () => onNudge("right"), <ArrowRight size={icon} strokeWidth={2.4} />)}
      <span aria-hidden className="mx-0.5 h-7 w-[2px] shrink-0 rounded bg-white/70" />
      {tile("Up one plate", active, () => onRaise(1), <ChevronsUp size={icon} strokeWidth={2.4} />)}
      {tile("Down one plate", active, () => onRaise(-1), <ChevronsDown size={icon} strokeWidth={2.4} />)}
      {tile("Turn a quarter", active, onRotate, <RotateCw size={icon} strokeWidth={2.4} />)}
      {tile("Paint", active, onColours, <Palette size={icon} strokeWidth={2.4} />, colours)}
      {tile("Copy", active, onDuplicate, <Copy size={icon} strokeWidth={2.4} />)}
      {tile("Delete", active, onDelete, <Trash2 size={icon} strokeWidth={2.4} />)}
      <span aria-hidden className="mx-0.5 h-7 w-[2px] shrink-0 rounded bg-white/70" />
      {tile("Add a piece", true, onParts, <Plus size={icon} strokeWidth={2.6} />, parts)}
    </div>
  );
}
