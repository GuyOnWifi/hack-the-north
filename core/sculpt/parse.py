"""Parse the layer-map shape format the LLM emits for the `sculpt` backend.

WHY a text format (docs/01-architecture.md 4.3): the LLM never emits a coordinate. It emits a
picture -- bottom-to-top ASCII layers over a named palette. A human can read it, the UI can
preview it in 200 ms, and a wrong shape is caught before any tiling work happens.

The parser is deliberately unforgiving. A half-parsed grid is worse than a rejection: it yields
a model that is quietly not the thing that was asked for, and nothing downstream can tell you
so. Every problem raises `SculptError` with a sentence naming the layer, the row and the
column -- written once, well, because like `Report.human` it is both user-facing copy and the
text fed back to the repair loop.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterator

# Colour codes are non-negative LDraw codes, so -1 is a safe "nothing here" sentinel and the
# grid stays all-integer (invariant 1: no floats, and here, no Nones to special-case either).
EMPTY = -1

# '.' is the documented empty cell; a space is accepted too because hand-written maps and
# JSON-embedded maps pick up stray padding, and rejecting that teaches the LLM nothing useful.
EMPTY_CHARS = frozenset(". ")

# Bounds exist so the tiler's work is bounded before it starts -- invariant 5, pushed as far
# upstream as it will go.
MAX_SIDE = 64
MAX_LAYERS = 64


class SculptError(ValueError):
    """A shape we refuse to build, with a sentence explaining exactly what is wrong."""

    def __init__(self, code: str, human: str):
        super().__init__(human)
        self.code = code
        self.human = human


@dataclass(frozen=True, slots=True)
class LayerMap:
    """A validated voxel shape. `layers[y][z][x]` is an LDraw colour code, or EMPTY."""

    w: int
    d: int
    layers: tuple[tuple[tuple[int, ...], ...], ...]
    palette: tuple[tuple[str, int], ...] = ()

    @property
    def height(self) -> int:
        return len(self.layers)

    @property
    def filled(self) -> int:
        return sum(1 for _ in self.cells())

    @property
    def colors(self) -> tuple[int, ...]:
        return tuple(sorted({c for _, _, _, c in self.cells()}))

    def cells(self) -> Iterator[tuple[int, int, int, int]]:
        """(x, y, z, colour) for every filled cell, in a fixed order."""
        for y, layer in enumerate(self.layers):
            for z, row in enumerate(layer):
                for x, c in enumerate(row):
                    if c != EMPTY:
                        yield x, y, z, c

    def layer_cells(self, y: int) -> list[tuple[int, int, int]]:
        """(x, z, colour) for one layer, in a fixed order."""
        return [(x, z, c) for (x, yy, z, c) in self.cells() if yy == y]

    def render(self, char_for: dict[int, str] | None = None) -> str:
        """Round-trip back to the text format, for previews and for test diffs."""
        rev = dict(char_for or {})
        for ch, code in self.palette:
            rev.setdefault(code, ch)
        out = []
        for layer in self.layers:
            out.append("\n".join(
                "".join("." if c == EMPTY else rev.get(c, "?") for c in row) for row in layer))
        return "\n\n".join(out)


def parse(spec: dict | str) -> LayerMap:
    """Validate and parse a layer map. Raises `SculptError` on anything malformed."""
    if isinstance(spec, (str, bytes)):
        try:
            spec = json.loads(spec)
        except (ValueError, TypeError) as exc:
            raise SculptError("BAD_JSON", f"The shape is not valid JSON: {exc}") from None
    if not isinstance(spec, dict):
        raise SculptError("BAD_SHAPE", "The shape must be a JSON object with "
                                       "'grid', 'palette' and 'layers'.")

    w, d = _parse_grid(spec.get("grid"))
    palette = _parse_palette(spec.get("palette"))
    layers = _parse_layers(spec.get("layers"), w, d, palette)
    return LayerMap(w, d, layers, tuple(sorted(palette.items())))


# ------------------------------------------------------------------ pieces of the parse

def _parse_grid(grid) -> tuple[int, int]:
    if not isinstance(grid, dict):
        raise SculptError("BAD_GRID", "The shape needs a 'grid' like {\"w\": 12, \"d\": 12} "
                                      "giving its width in studs (x) and depth in studs (z).")
    out = []
    for key in ("w", "d"):
        v = grid.get(key)
        if not isinstance(v, int) or isinstance(v, bool):
            raise SculptError("BAD_GRID", f"grid.{key} must be a whole number of studs, "
                                          f"not {v!r}.")
        if not 1 <= v <= MAX_SIDE:
            raise SculptError("BAD_GRID", f"grid.{key} is {v}; it must be between 1 and "
                                          f"{MAX_SIDE} studs.")
        out.append(v)
    return out[0], out[1]


def _parse_palette(palette) -> dict[str, int]:
    if not isinstance(palette, dict) or not palette:
        raise SculptError("BAD_PALETTE", "The shape needs a 'palette' mapping one character to "
                                         "one LDraw colour code, e.g. {\"R\": 4, \"K\": 0}.")
    out: dict[str, int] = {}
    for ch, code in palette.items():
        if not isinstance(ch, str) or len(ch) != 1:
            raise SculptError("BAD_PALETTE", f"Palette key {ch!r} must be a single character.")
        if ch in EMPTY_CHARS:
            raise SculptError("BAD_PALETTE", f"Palette key {ch!r} is reserved for empty space "
                                             f"and cannot name a colour.")
        if not isinstance(code, int) or isinstance(code, bool) or code < 0:
            raise SculptError("BAD_PALETTE", f"Palette entry {ch!r} maps to {code!r}; it must "
                                             f"be an LDraw colour code like 4 (red) or 0 (black).")
        out[ch] = code
    return out


def _split_layer(raw: str, index: int) -> list[str]:
    """Rows of one layer, with the wrapping blank lines of a JSON multi-line string removed."""
    rows = [r.rstrip("\r") for r in raw.split("\n")]
    while rows and not rows[0].strip():
        rows.pop(0)
    while rows and not rows[-1].strip():
        rows.pop()
    if not rows:
        raise SculptError("EMPTY_LAYER", f"Layer {index} is blank. Every layer must contain at "
                                         f"least one brick; delete it or draw something in it.")
    return rows


def _parse_layers(layers, w: int, d: int, palette: dict[str, int]):
    if not isinstance(layers, list) or not layers:
        raise SculptError("NO_LAYERS", "The shape needs a non-empty 'layers' list of strings, "
                                       "bottom layer first.")
    if len(layers) > MAX_LAYERS:
        raise SculptError("TOO_TALL", f"The shape has {len(layers)} layers; the limit is "
                                      f"{MAX_LAYERS}.")

    known = ", ".join(repr(k) for k in sorted(palette))
    out = []
    for i, raw in enumerate(layers):
        if not isinstance(raw, str):
            raise SculptError("BAD_LAYER", f"Layer {i} is {type(raw).__name__}, not a string of "
                                           f"rows separated by newlines.")
        rows = _split_layer(raw, i)
        width = len(rows[0])
        for z, row in enumerate(rows):
            if len(row) != width:
                raise SculptError(
                    "RAGGED_LAYER",
                    f"Layer {i} row {z} is {len(row)} characters wide but row 0 is {width}. "
                    f"Every row in a layer must be the same width -- pad short rows with '.'.")
        if width > w:
            raise SculptError("LAYER_TOO_WIDE",
                              f"Layer {i} is {width} studs wide but the grid is only {w}.")
        if len(rows) > d:
            raise SculptError("LAYER_TOO_DEEP",
                              f"Layer {i} has {len(rows)} rows but the grid is only {d} deep.")

        grid_rows = []
        filled = 0
        for z, row in enumerate(rows):
            cells = []
            for x, ch in enumerate(row):
                if ch in EMPTY_CHARS:
                    cells.append(EMPTY)
                    continue
                if ch not in palette:
                    raise SculptError(
                        "UNKNOWN_CHAR",
                        f"Layer {i} row {z} column {x} uses {ch!r}, which is not in the palette. "
                        f"Known characters: {known} (and '.' for empty).")
                cells.append(palette[ch])
                filled += 1
            grid_rows.append(tuple(cells + [EMPTY] * (w - width)))
        if not filled:
            raise SculptError("EMPTY_LAYER",
                              f"Layer {i} is all '.', so it contains no bricks. Remove it.")
        grid_rows += [tuple([EMPTY] * w)] * (d - len(rows))
        out.append(tuple(grid_rows))
    return tuple(out)
