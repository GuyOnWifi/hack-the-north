"""The provider adapter (decision D10). PROVIDER env switches Anthropic/OpenAI
*here only*, never at a call site. With no API key we fall back to a
deterministic MOCK so the whole loop runs with zero network (DEMO_SAFE).

Contract: propose_compose(prompt, inv_summary, noun, budget) -> composition
tree of {gen, args, attach, children}. The model emits CHOICES ONLY — generator
names, semantic args, socket names. Never a coordinate (invariant #4).
"""
from __future__ import annotations
import os

import json
import hashlib
import pathlib
MODEL = "claude-opus-5"     # behind the adapter; swap to gpt for OpenAI prize

SYSTEM = """You are the DESIGNER in a LEGO build system. You decide WHAT to
build. You never place a brick. You emit a composition: a tree of generator
calls with semantic arguments and socket names. Coordinates are computed by the
host. Available generators and their sockets are supplied in the catalog.
Reason about the user's bin in capability terms, not exact quantities."""

# The tool the real model is forced to call (output_config format). Shape only.
PROPOSE_TOOL = {
    "name": "propose_build",
    "description": "Emit a composition tree. No coordinates.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "root": {"$ref": "#/$defs/node"},
        },
        "$defs": {"node": {
            "type": "object",
            "properties": {
                "gen": {"type": "string"},
                "args": {"type": "object"},
                "attach": {"type": ["string", "null"]},
                "children": {"type": "array", "items": {"$ref": "#/$defs/node"}},
            }, "required": ["gen"],
        }},
        "required": ["root"],
    },
}


CACHE_DIR = pathlib.Path(os.environ.get(
    "BRICOLAGE_LLM_CACHE", pathlib.Path(__file__).resolve().parent.parent / "data" / "llm_cache"))


def _cache_key(*parts):
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode()).hexdigest()


def _cache_get(key):
    if os.environ.get("BRICOLAGE_NO_LLM_CACHE"):
        return None
    f = CACHE_DIR / key[:2] / f"{key}.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _cache_put(key, value):
    if os.environ.get("BRICOLAGE_NO_LLM_CACHE"):
        return
    f = CACHE_DIR / key[:2] / f"{key}.json"
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(value))
    except OSError:
        pass


def provider():
    # DEMO_SAFE forces the deterministic offline mock no matter what PROVIDER
    # says — the judging-table wifi-died insurance (DoD #4).
    if os.environ.get("DEMO_SAFE") == "1":
        return "mock"
    return os.environ.get("PROVIDER", "mock")


def _first_json(text):
    """Extract the first balanced {...} object from CLI output (tolerates
    surrounding prose or a ```json fence)."""
    import json
    depth = start = 0
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    start = 0
    return None


class LLMClient:
    """One method the rest of the system sees. Real providers parse tool_use;
    the mock synthesizes the same structure so Opus drops in unchanged."""

    def __init__(self, tape=None):
        self.tape = tape
        self.calls = 0

    def propose_compose(self, prompt, inv_summary, noun, size, seed):
        """Ask the designer for a composition, memoised on disk.

        MEASURED: a `claude -p` proposal takes 5-14 s, of which ~1.8 s is just spawning the CLI
        (a trivial "reply ok" prompt costs 1.77 s). A demo runs the same handful of prompts over
        and over, so the second run of anything should be free -- and on stage the difference
        between 14 s and instant is the difference between a pause and a beat.

        Keyed on everything that can change the answer, so a different bin or seed still asks.
        Determinism is unaffected: we already record the returned composition and replay the
        recorded op, never the model.
        """
        p = provider()
        key = _cache_key(p, MODEL, prompt, inv_summary, noun, size, seed)
        hit = _cache_get(key)
        if hit is not None:
            return hit

        self.calls += 1
        if p == "anthropic":
            comp = self._anthropic(prompt, inv_summary, noun, size, seed)
        elif p == "openai":
            comp = self._openai(prompt, inv_summary, noun, size, seed)
        elif p in ("claude_cli", "claude-cli", "cli"):
            comp = self._claude_cli(prompt, inv_summary, noun, size, seed)
        else:
            return self._mock(prompt, inv_summary, noun, size, seed)

        # Only cache a real answer. The mock fallback is cheap to recompute and caching it would
        # pin a degraded result in place long after the network came back.
        if comp is not None:
            _cache_put(key, comp)
        return comp

    # ---- real providers (wired, inert without a key) -------------------
    def _anthropic(self, prompt, inv_summary, noun, size, seed):  # pragma: no cover
        import anthropic  # noqa
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=MODEL, max_tokens=16000,
            system=[{"type": "text", "text": SYSTEM + "\n" + _CATALOG,
                     "cache_control": {"type": "ephemeral"}}],
            tools=[PROPOSE_TOOL], tool_choice={"type": "tool", "name": "propose_build"},
            messages=[{"role": "user",
                       "content": f"Bin: {inv_summary}\nBuild: {prompt}"}])
        for block in msg.content:
            if block.type == "tool_use":
                return block.input
        raise RuntimeError("model did not call propose_build")

    def _openai(self, prompt, inv_summary, noun, size, seed):  # pragma: no cover
        raise NotImplementedError("flip PROVIDER=openai after wiring the SDK")

    def _claude_cli(self, prompt, inv_summary, noun, size, seed):
        """Use the already-authenticated `claude -p` CLI as the designer (no API
        key needed). Falls back to the mock on any failure so the loop never
        breaks. Determinism still holds: we RECORD the returned composition, and
        replay re-applies the recorded op, not the model."""
        import subprocess, json
        user = (f"Bin (capability summary): {inv_summary}\n"
                f"Build request: {prompt!r}\n\n"
                "Emit ONE JSON object and nothing else — no prose, no code "
                "fence — matching:\n"
                '{"name": str, "root": {"gen": str, "args": {..semantic knobs..}, '
                '"children": [{"gen": str, "attach": <parent socket name>, '
                '"args": {...}, "children": [...]}]}}\n'
                "Use only generators/sockets from the catalog. Choose sizes that "
                "fit the bin. Never output coordinates.")
        try:
            out = subprocess.run(
                ["claude", "-p", user, "--system-prompt", SYSTEM + "\n" + _CATALOG],
                capture_output=True, text=True, timeout=90)
            comp = _first_json(out.stdout)
            if comp and "root" in comp and "gen" in comp.get("root", {}):
                comp.setdefault("name", noun.title())
                return comp
        except Exception:
            pass
        return self._mock(prompt, inv_summary, noun, size, seed)

    # ---- deterministic mock (stands in for Opus; identical output shape) --
    def _mock(self, prompt, inv_summary, noun, size, seed):
        from proposer import synthesize
        return synthesize(noun, size, seed)

    def propose_shape(self, prompt, noun, size, seed):
        """For open-ended shapes: the designer imagines a voxel field for ANY
        noun. Mock is procedural; claude_cli asks the real model for layer masks
        (a CHOICE of shape — the solver still legalises + verifies it)."""
        if provider() in ("claude_cli", "claude-cli", "cli"):
            v = self._claude_shape(prompt, noun)
            if v:
                return v
        from proposer import voxel_shape
        return voxel_shape(noun, size)

    def _claude_shape(self, prompt, noun):  # pragma: no cover (needs CLI)
        import subprocess, json
        user = (f"Design '{prompt}' as a small LEGO voxel model, ~5-8 layers.\n"
                "Output ONE JSON object, no prose: "
                '{"name": str, "layers": [["....","..#.",...], ...]} where each '
                "layer is a list of equal-length rows of '#' (brick) or '.' "
                "(empty), bottom layer first. Keep it under 8x8. Colours are "
                "chosen by the host.")
        try:
            out = subprocess.run(["claude", "-p", user], capture_output=True,
                                 text=True, timeout=90)
            data = _first_json(out.stdout)
            if not data or "layers" not in data:
                return None
            v = {}
            for y, layer in enumerate(data["layers"]):
                for z, row in enumerate(layer):
                    for x, ch in enumerate(row):
                        if ch == "#":
                            v[(x, y, z)] = 4
            return (v, data.get("name", noun.title())) if v else None
        except Exception:
            return None


# catalog the real system prompt would carry (generators + sockets)
_CATALOG = """CATALOG (generators -> sockets offered to children):
 chassis(length,width) -> deck_front, deck_rear, deck_center, nose, tail,
                          underside_front, underside_rear
 cabin(style=open|closed|cab, width, depth, height) -> roof   [mount: base]
 axle_pair(width) -> (none)                                    [mount: top]
 wall(length,height,width) -> top                              [mount: base]
 tower(height,footprint) -> top                                [mount: base]
 roof(width,depth,pitch) -> (none)                             [mount: base]
 slab(width,depth) -> top
 wing(span,sweep) -> (none)                                    [mount: root]
"""
