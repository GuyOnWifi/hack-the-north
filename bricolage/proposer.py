"""The DESIGNER's output, synthesized deterministically (mock stands in for
Opus). Emits composition trees only: generator + semantic args + socket names.
Never a coordinate. Real Opus produces the same structure behind client.py.
"""
from __future__ import annotations


def _scale(n, size, lo=2):
    return max(lo, round(n * size))


def synthesize(noun, size=1.0, seed=0):
    """noun -> composition tree of {gen, args, attach, children}."""
    if noun in ("rover", "car", "buggy", "cart", "vehicle", "truck", "tank", "train"):
        length, width = _scale(8, size, 6), 4
        cabin_depth = min(4, length)               # never overhang the deck
        return {"name": noun.title(), "root": {
            "gen": "chassis", "args": {"length": length, "width": width, "color": 72},
            "children": [
                {"gen": "cabin", "attach": "deck_front",
                 "args": {"style": "closed", "width": width, "depth": cabin_depth,
                          "height": 2, "color": 15}},
                {"gen": "axle_pair", "attach": "underside_front", "args": {"width": width}},
                {"gen": "axle_pair", "attach": "underside_rear", "args": {"width": width}},
            ]}}

    if noun in ("house", "hut", "garage", "cabin", "fort"):
        w, d = _scale(6, size, 4), _scale(6, size, 4)
        style = "open" if noun == "garage" else "closed"
        return {"name": noun.title(), "root": {
            "gen": "cabin", "args": {"style": style, "width": w, "depth": d,
                                     "height": _scale(2, size, 2), "color": 19},
            "children": [
                {"gen": "roof", "attach": "roof",
                 "args": {"width": w, "depth": d, "color": 4}},
            ]}}

    if noun in ("tower", "castle", "robot"):
        h = _scale(5, size, 3)
        root = {"gen": "tower", "args": {"height": h, "footprint": 2, "color": 71}}
        if noun == "robot":
            root["children"] = [{"gen": "cabin", "attach": "top",
                                 "args": {"style": "closed", "width": 2, "depth": 2,
                                          "height": 1, "color": 14}}]
        return {"name": noun.title(), "root": root}

    if noun in ("wall", "bridge"):
        return {"name": noun.title(), "root": {
            "gen": "wall", "args": {"length": _scale(10, size, 6),
                                    "height": _scale(3, size, 2), "color": 70}}}

    if noun in ("plane", "jet", "boat", "ship"):
        length, width = _scale(10, size, 8), 2
        return {"name": noun.title(), "root": {
            "gen": "chassis", "args": {"length": length, "width": width, "color": 71},
            "children": [
                {"gen": "cabin", "attach": "deck_center",
                 "args": {"style": "cab", "width": width, "depth": 2,
                          "height": 1, "color": 15}},
                {"gen": "wing", "attach": "deck_front", "args": {"span": 3, "color": 71}},
                {"gen": "wing", "attach": "deck_rear", "args": {"span": 3, "color": 71}},
            ]}}

    # LLM fallback default
    return synthesize("rover", size, seed)
