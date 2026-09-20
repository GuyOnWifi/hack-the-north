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


def _env(name, default, cast=float):
    """A fat-fingered env var must not take the module down with it: pipeline.py
    imports this unconditionally, DEMO_SAFE=1 included."""
    try:
        return cast(os.environ[name])
    except (KeyError, ValueError, TypeError):
        return default


MODEL = "claude-opus-5"     # behind the adapter; swap to gpt for OpenAI prize

# The latency knob. On claude-opus-5 thinking is ON when you omit `thinking`,
# and output_config.effort defaults to "high" -- so an unconfigured call runs
# the second-most-expensive setting available. This workload is a pick from an
# 8-entry catalog with a ~170-token answer, so the deep exploration is bought
# and not used. `low` is the panic setting: it is documented to skip thinking
# on inputs it judges simple, and bin-fit arg choice is exactly that judgement.
EFFORT = os.environ.get("BRICOLAGE_EFFORT", "medium")   # low|medium|high|xhigh|max

# Invariant #8: every loop has a budget and a degradation path. The SDK default
# is a 600 s read timeout with 2 retries -- ~30 minutes of stage silence on a
# stalled connection. We stream, so READ_TIMEOUT bounds SILENCE between events
# rather than total generation (a slow-but-healthy answer is never discarded),
# and DEADLINE is the hard wall-clock ceiling. max_retries=0: a retry re-runs
# the generation that just proved too slow, and the fallback is instant.
LLM_READ_TIMEOUT = _env("BRICOLAGE_LLM_TIMEOUT", 20.0)
LLM_DEADLINE = _env("BRICOLAGE_LLM_DEADLINE", 45.0)
_SDK = None     # one client per process; keeps the connection pool for the server

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
        self.degraded = False    # True once a provider fell back to the mock
        self.last_error = None
        self.last_usage = None   # the SDK Usage of the last real call, for the tape

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
        self.degraded = False
        self.last_usage = None
        # EFFORT is part of the answer, so it must be part of the key -- otherwise
        # an effort sweep silently re-serves the previous setting's build.
        key = _cache_key(p, MODEL, EFFORT, prompt, inv_summary, noun, size, seed)
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
        if comp is not None and not self.degraded:
            _cache_put(key, comp)
        return comp

    # ---- real providers (wired, inert without a key) -------------------
    def _anthropic(self, prompt, inv_summary, noun, size, seed):  # pragma: no cover
        """One SDK call, bounded, and it never raises.

        Streamed on purpose: for a non-streaming call the read timeout is a
        budget for the WHOLE generation, so a tight one throws away slow-but-
        good answers. Streamed, the same number bounds silence between events,
        which is what a stalled conference AP actually looks like. DEADLINE is
        the separate hard ceiling, because pings can keep a stream alive
        forever. Forced tool_choice is documented-legal with adaptive thinking
        on claude-opus-5 (the ban applies to MANUAL thinking, and to the
        fable/mythos family) -- do not "fix" it to auto.

        Invariant #4 is untouched: the schema carries gen/args/attach, never a
        coordinate.
        """
        import time
        global _SDK
        try:
            # Imported here, not at module scope: `anthropic` reaches the demo
            # laptop through requirements.txt, and DEMO_SAFE=1 must still run
            # on a machine that never installed it.
            import anthropic
            if _SDK is None:
                _SDK = anthropic.Anthropic(
                    timeout=anthropic.Timeout(LLM_READ_TIMEOUT, connect=5.0),
                    max_retries=0)
            deadline = time.monotonic() + LLM_DEADLINE
            with _SDK.messages.stream(
                    model=MODEL, max_tokens=16000,
                    thinking={"type": "adaptive"},      # the opus-5 default; explicit
                                                        # so a swap to opus-4-8, where
                                                        # omitting it means NO thinking,
                                                        # cannot change behaviour silently
                    output_config={"effort": EFFORT},
                    system=[{"type": "text", "text": SYSTEM + "\n" + _CATALOG,
                             "cache_control": {"type": "ephemeral"}}],
                    tools=[PROPOSE_TOOL],
                    tool_choice={"type": "tool", "name": "propose_build"},
                    messages=[{"role": "user",
                               "content": f"Bin: {inv_summary}\nBuild: {prompt}"}]) as stream:
                for _ in stream:
                    if time.monotonic() > deadline:
                        raise TimeoutError(
                            f"designer exceeded {LLM_DEADLINE:g}s wall clock")
                msg = stream.get_final_message()
            self.last_usage = getattr(msg, "usage", None)
            if os.environ.get("BRICOLAGE_LLM_STATS"):
                self._log_usage(msg)
            # opus-5 safety classifiers can decline with HTTP 200 and
            # stop_reason "refusal"; there is no tool_use block in that turn.
            if msg.stop_reason != "refusal":
                for block in msg.content:
                    if block.type == "tool_use":
                        return block.input
            self.last_error = f"no proposal (stop_reason={msg.stop_reason})"
        except Exception as e:
            # ImportError, no key (a bare TypeError, NOT an AnthropicError),
            # timeout, dead wifi, 429, 500 -- one answer on stage: take the
            # deterministic build and keep moving.
            self.last_error = f"{type(e).__name__}: {e}"
        return self._degrade(prompt, inv_summary, noun, size, seed)

    def _degrade(self, prompt, inv_summary, noun, size, seed):
        """Fall back to the offline designer, loudly. Marked degraded so
        propose_compose does not pin this answer on disk long after the
        network came back."""
        import sys
        self.degraded = True
        print(f"[llm] falling back to the offline designer: {self.last_error}",
              file=sys.stderr)
        if self.tape is not None:
            self.tape.emit("designer", "degrade",
                           f"designer unreachable ({self.last_error}); using the "
                           f"known-good template", status="warn", ms=1)
        return self._mock(prompt, inv_summary, noun, size, seed)

    @staticmethod
    def _log_usage(msg):
        """BRICOLAGE_LLM_STATS=1 prints the two numbers that settle the open
        questions: thinking_tokens (is effort the bottleneck?) and the cache
        counters (is the ~1.5 KB prefix over opus-5's 512-token minimum?)."""
        import sys
        try:
            u = msg.usage
            d = getattr(u, "output_tokens_details", None)
            print(f"[llm] effort={EFFORT} out={u.output_tokens} "
                  f"thinking={getattr(d, 'thinking_tokens', '?')} "
                  f"cache_write={getattr(u, 'cache_creation_input_tokens', 0)} "
                  f"cache_read={getattr(u, 'cache_read_input_tokens', 0)} "
                  f"fresh_in={u.input_tokens}", file=sys.stderr)
        except Exception:
            pass

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
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
        # Same cache-poisoning bug lived here: a mock IS a dict, so without the
        # flag propose_compose pinned it on disk under a real-provider key.
        self.last_error = self.last_error or "CLI returned no usable JSON"
        return self._degrade(prompt, inv_summary, noun, size, seed)

    # ---- deterministic mock (stands in for Opus; identical output shape) --
    def _mock(self, prompt, inv_summary, noun, size, seed):
        from proposer import synthesize
        return synthesize(noun, size, seed)

    def propose_shape(self, prompt, noun, size, seed):
        """For open-ended shapes: the designer imagines a voxel field for ANY
        noun. Mock is procedural; claude_cli asks the real model for layer masks
        (a CHOICE of shape — the solver still legalises + verifies it)."""
        p = provider()
        if p in ("claude_cli", "claude-cli", "cli"):
            v = self._claude_shape(prompt, noun)
            if v:
                return v
        elif p != "mock":
            # There is no SDK path here. Say so, rather than let the "sketching…"
            # line above imply we asked the model and got this back.
            msg = (f"no {p} path for open-ended shapes — using the procedural "
                   f"'{noun}' shape")
            if self.tape is not None:
                self.tape.emit("designer", "degrade", msg, status="warn", ms=1)
            else:
                print(f"[llm:propose_shape] {msg}")
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
