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
    return os.environ.get("PROVIDER", "mock")


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

    # ---- deterministic mock (stands in for Opus; identical output shape) --
    def _mock(self, prompt, inv_summary, noun, size, seed):
        from proposer import synthesize
        return synthesize(noun, size, seed)


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
