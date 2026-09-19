"""The tape — the streamed log of agent activity (Contract 4). Our best demo
artifact and the Rox prize exhibit: it shows conflicting sources, decisions
under uncertainty, and a verifier that can REJECT the model.

actor  in designer | inspector | repair | scribe | cataloguer | router
status in ok | fail | warn | running
"""
from __future__ import annotations
import json


class Tape:
    def __init__(self, clock=None):
        self.events = []
        self._t = 0
        self._clock = clock  # injectable so replay is deterministic

    def emit(self, actor, kind, text, status="ok", ms=0, tokens=0, **extra):
        self._t += max(1, ms)
        ev = {"t": self._t, "actor": actor, "kind": kind, "text": text,
              "status": status, "ms": ms, "tokens": tokens, **extra}
        self.events.append(ev)
        return ev

    def sse(self):
        return "\n".join("data: " + json.dumps(e) for e in self.events)

    ICON = {"ok": "✓", "fail": "✗", "warn": "!", "running": "…"}
    COLOR = {"designer": "36", "inspector": "35", "repair": "33",
             "scribe": "32", "router": "34", "cataloguer": "36"}

    def render(self, color=True):
        lines = []
        for e in self.events:
            icon = self.ICON.get(e["status"], " ")
            tag = f"{e['actor']:>9}"
            if color:
                c = self.COLOR.get(e["actor"], "37")
                tag = f"\x1b[{c}m{tag}\x1b[0m"
                icon = {"ok": "\x1b[32m✓\x1b[0m", "fail": "\x1b[31m✗\x1b[0m",
                        "warn": "\x1b[33m!\x1b[0m", "running": "…"}.get(e["status"], " ")
            meta = ""
            if e["ms"] or e["tokens"]:
                bits = []
                if e["ms"]:
                    bits.append(f"{e['ms']}ms")
                if e["tokens"]:
                    bits.append(f"{e['tokens']}tok")
                meta = f"  \x1b[90m({', '.join(bits)})\x1b[0m" if color else f"  ({', '.join(bits)})"
            lines.append(f"  {icon} {tag}  {e['text']}{meta}")
        return "\n".join(lines)
