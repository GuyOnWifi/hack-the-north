"""The provider adapter (decision D10). PROVIDER env switches Anthropic/OpenAI
*here only*, never at a call site. With no API key we fall back to a
deterministic MOCK so the whole loop runs with zero network (DEMO_SAFE).

Contract: propose_compose(prompt, inv_summary, noun, budget) -> composition
tree of {gen, args, attach, children}. The model emits CHOICES ONLY — generator
names, semantic args, socket names. Never a coordinate (invariant #4).
"""
from __future__ import annotations
import os

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


def provider():
    # DEMO_SAFE forces the deterministic offline mock no matter what PROVIDER
    # says — the judging-table wifi-died insurance (DoD #4).
    if os.environ.get("DEMO_SAFE") == "1":
        return "mock"
    return os.environ.get("PROVIDER", "mock")


def _first_json(text):
    """Extract the first balanced {...} object from CLI output (tolerates
    surrounding prose or a ```json fence). Ignores braces inside strings."""
    import json
    depth = 0
    start = None
    instr = esc = False
    for i, ch in enumerate(text):
        if instr:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                instr = False
            continue
        if ch == '"':
            instr = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    start = None
    return None


class LLMClient:
    """One method the rest of the system sees. Real providers parse tool_use;
    the mock synthesizes the same structure so Opus drops in unchanged."""

    def __init__(self, tape=None):
        self.tape = tape
        self.calls = 0

    def propose_compose(self, prompt, inv_summary, noun, size, seed):
        self.calls += 1
        p = provider()
        if p == "anthropic":
            return self._anthropic(prompt, inv_summary, noun, size, seed)
        if p == "openai":
            return self._openai(prompt, inv_summary, noun, size, seed)
        if p in ("claude_cli", "claude-cli", "cli"):
            return self._claude_cli(prompt, inv_summary, noun, size, seed)
        return self._mock(prompt, inv_summary, noun, size, seed)

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
        """Ask the designer to draw the request as a flat COLOUR PIXEL-ART grid
        (a mosaic). Reads clearly and colours naturally — far better than blind
        3D voxels. The vision loop then corrects it by looking at the render."""
        import subprocess
        from sculpt import parse_mask
        user = (f"Draw \"{prompt}\" as LEGO pixel art: a single flat grid, "
                "8-14 rows, like a mosaic picture facing the viewer.\n"
                "Output ONE JSON object, no prose: {\"name\": str, "
                "\"grid\": [\"row\", \"row\", ...]}. Each row is a string of "
                "equal length. Each character is a colour or empty:\n"
                "  r=red o=orange y=yellow g=green b=blue w=white k=black "
                "n=brown t=tan a=gray  .=empty\n"
                "Use colour to make it recognisable (a flower: green stem, "
                "coloured petals, yellow centre). Draw the whole SOLID silhouette "
                "of the object, centred, filling most of the grid.")
        try:
            out = subprocess.run(["claude", "-p", user], capture_output=True,
                                 text=True, timeout=110)
            data = _first_json(out.stdout)
            grid = data and (data.get("grid") or data.get("rows") or data.get("layers"))
            if not grid:
                return None
            if grid and isinstance(grid[0], list):     # tolerate nested [[...]]
                grid = grid[0]
            v = parse_mask(grid)
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
