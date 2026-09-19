"""Deterministic substitution (repair rung 2). When the bin is short an
element, swap a placed part for a set of smaller parts occupying the EXACT
same footprint (grid offsets, not matrices — decision D6). No LLM involved:
this is the machinery behind "most repairs never reach the model".
"""
from __future__ import annotations
from model import Part
from meta import SUBSTITUTIONS, PART_META


def refit_palette(parts, inventory):
    """Recolour parts to colours the bin actually stocks (nearest by RGB), so a
    mosaic/shape can be built from a finite scanned bin even when it asked for
    colours you don't have. Preserves the shape; changes only colour. Returns
    (new_parts, n_remapped). The constraint-solving half of the product."""
    from dataclasses import replace
    from meta import COLOR_RGB
    parts = list(parts)

    def dist(c1, c2):
        a = COLOR_RGB.get(c1, (128, 128, 128))
        b = COLOR_RGB.get(c2, (128, 128, 128))
        return sum((x - y) ** 2 for x, y in zip(a, b))

    remapped = 0
    for _ in range(40):
        used = _need(parts)
        short = [(e, used[e] - inventory.have(*e)) for e in used
                 if used[e] > inventory.have(*e)]
        if not short:
            break
        (part, color), deficit = max(short, key=lambda x: x[1])
        # colours the bin stocks THIS part in, with spare headroom, nearest first
        alts = []
        for (pp, c), qty in inventory.counts.items():
            if pp == part and c != color:
                spare = qty - used.get((pp, c), 0)
                if spare > 0:
                    alts.append((dist(color, c), c, spare))
        if not alts:
            break                      # no colour of this part is available at all
        alts.sort()
        _, newc, spare = alts[0]
        moved, target = 0, min(deficit, spare)
        for i, p in enumerate(parts):
            if moved >= target:
                break
            if p.part == part and p.color == color and p.sub != "base":
                parts[i] = replace(p, color=newc)
                moved += 1
                remapped += 1
        if moved == 0:
            break
    return parts, remapped


def _need(parts):
    n = {}
    for p in parts:
        n[(p.part, p.color)] = n.get((p.part, p.color), 0) + 1
    return n


def apply(parts, inventory):
    """Return (new_parts, swaps, resolved_all). Greedily substitutes shorted
    elements until the bin can afford the build or no rule applies."""
    parts = list(parts)
    swaps = []
    # remaining[e] = have - used, recomputed as we mutate
    def remaining():
        used = _need(parts)
        return {e: inventory.have(*e) - used.get(e, 0)
                for e in set(list(used) + list(inventory.counts))}

    changed = True
    while changed:
        changed = False
        rem = remaining()
        short = sorted(((-(v), e) for e, v in rem.items() if v < 0))
        for _, (part, color) in short:
            rules = SUBSTITUTIONS.get(part)
            if not rules:
                continue
            # find a placed part of this element and an affordable rule
            idx = next((i for i, p in enumerate(parts)
                        if p.part == part and p.color == color and p.rot == 0), None)
            if idx is None:
                continue
            for rule in rules:
                # affordable if every replacement element has headroom
                add = {}
                for rp, _, _ in rule:
                    add[(rp, color)] = add.get((rp, color), 0) + 1
                rem2 = remaining()
                # freeing one `part` gives +1 back
                rem2[(part, color)] = rem2.get((part, color), 0) + 1
                if all(rem2.get(e, 0) - c >= 0 for e, c in add.items()):
                    victim = parts.pop(idx)
                    for rp, ox, oz in rule:
                        parts.append(Part(
                            id=victim.id + f".{rp}", part=rp, color=color,
                            pos=(victim.pos[0] + ox, victim.pos[1], victim.pos[2] + oz),
                            rot=0, sub=victim.sub))
                    swaps.append({"from": part, "to": [r[0] for r in rule],
                                  "element_color": color, "at": victim.pos})
                    changed = True
                    break
            if changed:
                break

    rem = remaining()
    resolved_all = all(v >= 0 for v in rem.values())
    return parts, swaps, resolved_all
