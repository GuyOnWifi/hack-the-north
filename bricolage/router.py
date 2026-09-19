"""Subject extraction for the LEGO LLM harness.

There is ONE path now: every request goes to the harness, which prompts the LLM
to design a real 3D model in the BrickGPT grammar. No hard-coded nouns, no
template compose backend — the model figures out what to build. This module just
pulls a short subject word out of the prompt (for naming) and any size hint.
"""
from __future__ import annotations
import re

SIZE = {"tiny": 0.5, "small": 0.7, "little": 0.7, "big": 1.5, "large": 1.5,
        "huge": 2.0, "long": 1.4, "mini": 0.6}
STOPWORDS = {"build", "make", "create", "the", "and", "for", "with", "please",
             "can", "you", "give", "want", "would", "like", "some", "this",
             "that", "small", "big", "tiny", "huge", "large", "little", "a", "an",
             "me", "us", "into", "out", "3d", "2d", "real", "lego"}


def route(prompt):
    """Return (backend, noun, size, reason). Always the harness."""
    words = re.findall(r"[a-z]+", prompt.lower())
    size = 1.0
    for w in words:
        if w in SIZE:
            size = SIZE[w]
    noun = next((w for w in reversed(words) if len(w) > 2 and w not in STOPWORDS), "model")
    return "sculpt", noun, size, f"“{prompt.strip()}” → LEGO LLM harness (3D)"
