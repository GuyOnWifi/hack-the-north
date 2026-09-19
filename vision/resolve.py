"""Brickognize part id -> LDraw part id.

THE TRAP THIS EXISTS FOR
------------------------
Brickognize returns BrickLink-style ids. LDraw (and therefore bricknet, and therefore our whole
build system) uses official LDraw filenames, which carry a variant suffix that BrickLink omits.
Measured against known LDraw renders:

    brickognize   ldraw     part
    3023      ->  3023b     Plate 1 x 2     <- one of the commonest parts there is
    3040      ->  3040b     Slope 45 2 x 1
    3069a     ->  3069b     Tile 1 x 2      (with/without groove; identical on our grid)

Without this module those rows silently become `placeable: false` and quietly vanish from the
solver's inventory -- the worst kind of bug, because nothing errors.

Resolution order: exact hit, then variant suffixes, then the plain stem, then give up honestly.

Picking the RIGHT variant matters as much as finding one. The `a` suffix is usually the old or
special mould and `b` the modern plain one -- 3023a is "plate 1x2 with flat pin", 3023b is just
"plate 1x2" -- so naive alphabetical order resolves the commonest plate in LEGO to a rare
pin-bearing variant nobody owns. We pick the variant with the PLAINEST NAME (fewest qualifying
words), which is a property of the mould rather than an accident of lettering.
"""

from __future__ import annotations

import functools
import re

from core import meta as meta_mod

_SUFFIXES = ("", "a", "b", "c", "d", "e")
_STEM = re.compile(r"^(\d+)([a-z]*)$", re.I)
# Words that mark a variant as a special mould rather than the plain one.
_QUALIFIERS = re.compile(r"\b(with|without|and|for)\b", re.I)


def _plainness(part: str) -> tuple[int, int, str]:
    """Sort key: fewest qualifier words, then shortest name, then stable by id."""
    name = meta_mod.get(part).name
    return (len(_QUALIFIERS.findall(name)), len(name), part)


@functools.cache
def resolve(brickognize_id: str) -> tuple[str | None, str]:
    """(ldraw_part or None, how_we_got_there). Cached: the same ids recur constantly."""
    pid = (brickognize_id or "").strip()
    if not pid:
        return None, "empty"

    if meta_mod.has(pid):
        return pid, "exact"

    m = _STEM.match(pid)
    if not m:
        return None, "unparseable"
    digits, suffix = m.group(1), m.group(2).lower()

    # The same mould with a different variant letter (3023 -> 3023b, 3069a -> 3069b).
    variants = [f"{digits}{s}" for s in _SUFFIXES
                if f"{digits}{s}" != pid and meta_mod.has(f"{digits}{s}")]
    if variants:
        best = min(variants, key=_plainness)
        return best, f"variant:{pid}->{best}"

    if suffix and meta_mod.has(digits):
        return digits, f"stripped:{pid}->{digits}"

    return None, "no-ldraw-equivalent"


def resolve_candidates(candidates: list) -> tuple[str | None, str, object | None]:
    """Walk a ranked candidate list and take the best one we can actually place.

    A high-scoring part we cannot place is worth less than a slightly lower-scoring part we can,
    because an unplaceable part contributes nothing to a build.
    """
    for c in candidates:
        part, how = resolve(getattr(c, "part", None) or c.get("part"))
        if part:
            return part, how, c
    return None, "none-placeable", (candidates[0] if candidates else None)
