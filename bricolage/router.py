"""Heuristic-first router (decision: heuristic first, LLM fallback). The
backend choice is on the hot path of every request, so cheap rules decide the
obvious cases and the LLM only breaks ties. recall is CUT for the demo.
"""
from __future__ import annotations
import re

COMPOSE_NOUNS = {
    "rover", "car", "truck", "vehicle", "buggy", "cart", "tank", "train",
    "house", "hut", "fort", "garage", "cabin", "tower", "castle", "wall",
    "bridge", "robot", "plane", "jet", "boat", "ship",
}
SCULPT_NOUNS = {
    "heart", "tree", "dog", "cat", "pikachu", "duck", "star", "pyramid",
    "mushroom", "apple", "flower", "rose", "tulip", "snake", "letter",
    "fish", "bird", "crown", "sword", "key", "cactus", "ghost", "skull",
}
SIZE = {"tiny": 0.5, "small": 0.7, "little": 0.7, "big": 1.5, "large": 1.5,
        "huge": 2.0, "long": 1.4, "mini": 0.6}
STOPWORDS = {"build", "make", "create", "the", "and", "for", "with", "please",
             "can", "you", "give", "want", "would", "like", "some", "this",
             "that", "small", "big", "tiny", "huge", "large", "little"}


def route(prompt):
    """Return (backend, noun, size, reason)."""
    words = re.findall(r"[a-z]+", prompt.lower())
    size = 1.0
    for w in words:
        if w in SIZE:
            size = SIZE[w]
    for w in words:
        if w in COMPOSE_NOUNS:
            return "compose", w, size, f"'{w}' is a structural object -> compose"
    for w in words:
        if w in SCULPT_NOUNS:
            return "sculpt", w, size, f"'{w}' is an organic shape -> sculpt"
    # Unknown request: it's a freeform object ("a moon", "a dragon"). Let the
    # designer IMAGINE it as a shape (sculpt) rather than defaulting to a vehicle.
    noun = next((w for w in words if len(w) > 2 and w not in STOPWORDS), "blob")
    return "sculpt", noun, size, f"no structural keyword -> freeform shape '{noun}' -> sculpt"
