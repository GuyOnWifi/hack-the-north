"""Plain language -> part-level edit ops (docs/EDITING.md E).

Three tiers, in order, and every one of them ends at the same gate:

  1. `preparse` — a deterministic phrase parser. No model, works offline, and
     it handles nearly everything a person actually types at a finished model.
  2. `fast` — one small model call that may choose an op, a target, a direction
     word, a whole number, a colour name or a part number, and *nothing else*.
     `validate_reply` refuses any reply carrying a coordinate.
  3. the existing brief-level edit, for requests that are really a redesign.

Code computes every coordinate. The model never sees one and never emits one.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brickify"))
from brickify import partlib  # noqa: E402

HUMAN = {
    "NEEDS_SELECTION": "Tap the pieces you mean first, then say that again.",
    "NOT_FOUND": "I couldn't find any {phrase} on this model. Tap the pieces you mean and try again.",
    "AMBIGUOUS": "I found {n} things that could be “{phrase}”: {names}. Tap the one you mean.",
    "NL_FAILED": "I couldn't work that out. Tap the pieces and use the buttons, or try different words.",
    "LLM_COORDINATE": "I couldn't work that out. Tap the pieces and use the buttons, or try different words.",
    "STRUCTURAL_UNAVAILABLE": "That's a redesign, and this model was loaded from a file, so I can only "
                              "change its pieces: move, turn, recolour, add or remove them.",
}

DIRS = {"right": (1, 0, 0), "left": (-1, 0, 0), "up": (0, 1, 0), "down": (0, -1, 0),
        "forward": (0, 0, -1), "forwards": (0, 0, -1), "front": (0, 0, -1),
        "back": (0, 0, 1), "backward": (0, 0, 1), "backwards": (0, 0, 1)}
FLAT = ("left", "right", "forward", "forwards", "front", "back", "backward", "backwards")
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
         "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "a": 1, "an": 1}
NUM = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|an?|a couple)"
UNIT = r"(?:studs?|plates?|bricks?)"
DIR_RE = r"(?:up|down|left|right|forwards?|backwards?|back|front)"
POS_WORDS = {"top": "top", "upper": "top", "bottom": "bottom", "lower": "bottom",
             "front": "front", "back": "back", "rear": "back", "left": "left", "right": "right"}
GENERIC = {"piece", "pieces", "part", "parts", "brick", "bricks", "one", "ones", "bit", "bits"}
PRONOUN_SEL = {"this", "these", "that", "those", "them", "selected", "the selection", "selection"}
PRONOUN_ALL = {"everything", "all", "the whole thing", "the model", "whole thing", "model"}
TAGS = {"light": "light", "lights": "light", "lamp": "light", "lamps": "light",
        "headlight": "light", "headlights": "light", "taillight": "light", "taillights": "light",
        "eye": "eye", "eyes": "eye", "window": "window", "windows": "window",
        "windscreen": "window", "glass": "window",
        "wheel": "wheel", "wheels": "wheel", "tyre": "wheel", "tyres": "wheel",
        "tire": "wheel", "tires": "wheel"}
KINDS = {"brick", "plate", "tile", "slope", "round", "wedge", "hinge", "bar"}
TRANS_OF = {"blue": 33, "red": 36, "yellow": 46, "green": 34, "orange": 57,
            "clear": 47, "white": 47, "pink": 45, "purple": 52}


def _num(word) -> int:
    if word is None:
        return 1
    w = str(word).strip().lower()
    if w == "a couple":
        return 2
    if w.isdigit():
        return int(w)
    return WORDS.get(w, 1)


# ------------------------------------------------------------------ colours
_INDEX: dict | None = None


def _colour_index() -> dict:
    global _INDEX
    if _INDEX is None:
        idx: dict = {}
        for code, meta in partlib.colours().items():
            idx.setdefault(meta["name"].lower(), []).append(code)
        _INDEX = idx
    return _INDEX


def _norm_colour(phrase: str) -> str:
    p = " ".join(phrase.lower().split())
    p = p.replace("gray", "grey")
    p = re.sub(r"^(see[- ]through|transparent)\s+", "trans ", p)
    if p == "clear":
        p = "trans clear"
    return p


def colour_codes(phrase: str, table) -> list:
    """Every LDraw code a colour phrase could mean, model colours first."""
    p = _norm_colour(phrase)
    if not p:
        return []
    idx = _colour_index()
    out: list = []
    if p == "light grey":
        out = [71, 7]
    elif p == "dark grey":
        out = [72, 8]
    else:
        out = list(idx.get(p, []))
        if not out and not p.startswith("trans "):
            out = list(idx.get("trans " + p, []))
    if not out:
        return []
    present = {r["colour"] for r in table["parts"]}
    return sorted(out, key=lambda c: (c not in present, c))


def _is_colour(phrase: str) -> bool:
    p = _norm_colour(phrase)
    return bool(p) and (p in _colour_index() or p in ("light grey", "dark grey"))


def target_colour(phrase: str, table, current: int) -> int | None:
    """The code a recolour should use for a part that is currently `current`:
    a see-through piece stays see-through."""
    codes = colour_codes(phrase, table)
    if not codes:
        return None
    if partlib.is_trans(current):
        key = _norm_colour(phrase).replace("trans ", "")
        t = TRANS_OF.get(key)
        if t is not None:
            return t
        for c in codes:
            if partlib.is_trans(c):
                return c
    for c in codes:
        if not partlib.is_trans(c):
            return c
    return codes[0]


# ----------------------------------------------------------- target phrases
def _tok(s: str) -> list:
    return re.findall(r"[a-z0-9]+", s.lower())


def _sing(w: str) -> str:
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def resolve(phrase: str, table, selection) -> tuple:
    """('ok', ids) | ('NEEDS_SELECTION', []) | ('NOT_FOUND', candidates) |
    ('AMBIGUOUS', candidates, names). Lower-case, punctuation stripped."""
    selection = [s for s in (selection or []) if any(r["id"] == s for r in table["parts"])]
    raw = " ".join(re.sub(r"[^\w\s-]", " ", (phrase or "").lower()).split())
    if not raw:
        return ("NOT_FOUND", [])
    if raw in PRONOUN_SEL:
        return ("ok", list(selection)) if selection else ("NEEDS_SELECTION", [])
    if raw in PRONOUN_ALL:
        return ("ok", [r["id"] for r in table["parts"]])
    if raw == "it":
        return ("ok", list(selection) if selection else [r["id"] for r in table["parts"]])

    toks = _tok(raw)
    every = False
    while toks and toks[0] in ("the", "a", "an", "all", "every", "both"):
        if toks[0] in ("all", "every", "both"):
            every = True
        toks.pop(0)
    plural = every
    while len(toks) > 1 and toks[-1] in GENERIC:
        if toks[-1].endswith("s"):
            plural = True
        toks.pop()
    if toks and toks == ["it"]:
        return ("ok", list(selection) if selection else [r["id"] for r in table["parts"]])
    if toks and " ".join(toks) in PRONOUN_SEL:
        return ("ok", list(selection)) if selection else ("NEEDS_SELECTION", [])

    pos: list = []
    popped: list = []
    while toks and toks[0] in POS_WORDS:
        popped.append(toks[0])
        pos.append(POS_WORDS[toks.pop(0)])
    if not toks and popped:
        # "the front" can also be a body actually called front
        if " ".join(popped) in {b["name"].lower() for b in table["bodies"]}:
            toks, pos = popped, []
    colour_phrase = ""
    for take in (3, 2, 1):
        if len(toks) >= take and _is_colour(" ".join(toks[:take])):
            if len(toks) == take and not pos and not colour_phrase:
                pass  # a bare colour is a valid target ("the red ones")
            colour_phrase = " ".join(toks[:take])
            toks = toks[take:]
            break
    noun = " ".join(toks)
    if noun and any(t.endswith("s") and len(t) > 3 for t in toks):
        plural = True

    rows = table["parts"]
    ids, bodies_hit = (None, 0)
    if noun:
        ids, bodies_hit = _noun_ids(noun, table)
        if ids is None:
            return ("NOT_FOUND", [])
    else:
        ids = [r["id"] for r in rows]
    noun_ids = list(ids)

    if colour_phrase:
        codes = set(colour_codes(colour_phrase, table))
        ids = [i for i in ids if _row(table, i)["colour"] in codes]
        if not ids:
            return ("NOT_FOUND", noun_ids if noun else [])
    if pos:
        ids = _by_pos(ids, pos, table, bool(noun), plural)
        if not ids:
            return ("NOT_FOUND", noun_ids)
    if not ids:
        return ("NOT_FOUND", [])
    if not plural and not every:
        if bodies_hit > 1:
            names = ", ".join(sorted({_row(table, i)["body"] for i in ids})[:4])
            return ("AMBIGUOUS", ids, names)
        if noun and not pos and len(ids) > 1 and bodies_hit == 0:
            names = ", ".join(sorted({_row(table, i)["name"] for i in ids})[:4])
            return ("AMBIGUOUS", ids, names)
    return ("ok", ids)


def _row(table, ident):
    for r in table["parts"]:
        if r["id"] == ident:
            return r
    return None


def _auto_body(name: str) -> bool:
    """True for the colour-cluster names load_ldr invents ('red', 'black 3')."""
    return _is_colour(re.sub(r"\s+\d+$", "", name.strip().lower()))


def _noun_ids(noun: str, table):
    """(ids, bodies matched). ids is None when nothing matched at all."""
    rows = table["parts"]
    toks = [_sing(t) for t in _tok(noun)]
    # 1 — a body name. A loaded model's bodies are named after their colour
    # ("light grey 2"), and those names must not swallow real nouns: "lights"
    # is a lamp, not the grey cluster. Only an exact match counts for those.
    exact = [b["name"] for b in table["bodies"] if b["name"].lower() == noun]
    if not exact:
        exact = [b["name"] for b in table["bodies"]
                 if not _auto_body(b["name"])
                 and all(t in [_sing(x) for x in re.split(r"[\s_-]+", b["name"].lower())] for t in toks)]
    if exact:
        return [r["id"] for r in rows if r["body"] in exact], len(exact)
    # 2 — a tag (the words people use)
    tag = TAGS.get(noun) or (TAGS.get(toks[0]) if len(toks) == 1 else None)
    if tag:
        hit = [r["id"] for r in rows if tag in r["tags"]]
        if hit:
            return hit, 0
    # 3 — a kind
    if len(toks) == 1 and toks[0] in KINDS:
        hit = [r["id"] for r in rows if r["kind"] == toks[0]]
        if hit:
            return hit, 0
    # 4 — a size, optionally with a kind
    m = re.search(r"(\d+)\s*x\s*(\d+)", noun)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        want_kind = next((t for t in toks if t in KINDS), None)
        hit = [r["id"] for r in rows
               if sorted((r["size"][0], r["size"][2])) == sorted((a, b))
               and (want_kind is None or r["kind"] == want_kind)]
        if hit:
            return hit, 0
    # 5 — a word from the part's own name
    hit = [r["id"] for r in rows
           if all(t in [_sing(x) for x in _tok(r["name"])] for t in toks)]
    if hit:
        return hit, 0
    # 6 — an LDraw part number
    hit = [r["id"] for r in rows if r["part"].lower() == noun.replace(" ", "")]
    if hit:
        return hit, 0
    return None, 0


AXIS = {"top": (1, -1), "bottom": (1, 1), "left": (0, -1), "right": (0, 1),
        "front": (2, -1), "back": (2, 1)}


def _by_pos(ids, pos, table, has_noun, plural):
    for word in pos:
        axis, sign = AXIS[word]
        rows = [_row(table, i) for i in ids]
        if has_noun:
            vals = [r["origin"][axis] * sign for r in rows]
            mid = (min(vals) + max(vals)) / 2
            keep = [r["id"] for r, v in zip(rows, vals) if v > mid + 1e-9]
            ids = keep or ids
        else:
            keep = [r["id"] for r in rows if word in r["where"]]
            ids = keep or ids
            if word in ("top", "bottom") and not plural:
                # "the top piece" means one piece: the extreme one, first in
                # file order when several share the extreme layer
                rows2 = [_row(table, i) for i in ids]
                vals = [r["origin"][1] * sign for r in rows2]
                best = max(vals)
                layer = [r for r, v in zip(rows2, vals) if v > best - 8.0]
                ids = [min(layer, key=lambda r: r["line"])["id"]]
    return ids


# ------------------------------------------------------- the pre-parser (E.3)
def _clean(text: str) -> str:
    t = " ".join((text or "").strip().lower().split())
    t = re.sub(r"^(please\s+|can you\s+|could you\s+|i want to\s+|i'd like to\s+)+", "", t)
    t = re.sub(r"[\s.!,]+$", "", t)
    t = re.sub(r"^\s*please\s+", "", t)
    return t


def preparse(text: str, table, selection):
    """A recognised phrase -> {"kind": "ops"|"nav"|"reject", ...}; None when the
    phrase isn't one we know (the FAST model gets a try)."""
    t = _clean(text)
    if not t:
        return None
    if re.fullmatch(r"(undo|undo that|go back|revert|revert that)", t):
        return {"kind": "nav", "dir": "undo"}
    if re.fullmatch(r"(redo|redo that)", t):
        return {"kind": "nav", "dir": "redo"}

    m = re.match(r"^(?:make|paint|colou?r|turn|change)\s+(.+)$", t)
    if m:
        got = _recolour(m.group(1), table, selection)
        if got is not None:
            return got
    m = re.match(r"^(?:delete|remove|erase|get rid of|take off|take away|take out)\s+(.+)$", t)
    if m:
        return _with_target(m.group(1), table, selection,
                            lambda ids: [{"op": "delete", "ids": ids, "cascade": False}])
    m = re.match(r"^(?:move|shift|nudge|push|slide)\s+(.+)$", t)
    if m:
        got = _move(m.group(1), table, selection)
        if got is not None:
            return got
    m = re.match(r"^(raise|lift|lower|drop)\s+(.+)$", t)
    if m:
        got = _raise(m.group(1), m.group(2), table, selection)
        if got is not None:
            return got
    m = re.match(r"^(?:rotate|turn|spin)\s+(.+)$", t)
    if m:
        got = _rotate(m.group(1), table, selection)
        if got is not None:
            return got
    m = re.match(r"^(?:duplicate|copy|clone)\s+(.+)$", t)
    if m:
        return _with_target(m.group(1), table, selection,
                            lambda ids: [{"op": "duplicate", "ids": ids}])
    m = re.match(r"^add\s+(.+)$", t)
    if m:
        got = _add(m.group(1), table, selection)
        if got is not None:
            return got
    return None


def _bare(phrase: str) -> str:
    return re.sub(r"^(the|a|an|all the|all|every|both)\s+", "", (phrase or "").strip().lower())


def _reject(code, phrase="", candidates=(), names=""):
    human = HUMAN[code].format(phrase=_bare(phrase), n=len(candidates), names=names)
    return {"kind": "reject", "code": code, "human": human, "candidates": list(candidates),
            "phrase": phrase}


def _with_target(phrase, table, selection, make):
    got = resolve(phrase, table, selection)
    if got[0] == "ok":
        return {"kind": "ops", "ops": make(got[1]), "matched": got[1], "phrase": phrase}
    if got[0] == "NEEDS_SELECTION":
        return _reject("NEEDS_SELECTION")
    if got[0] == "AMBIGUOUS":
        return _reject("AMBIGUOUS", phrase, got[1], got[2])
    # the verb was understood but the target wasn't: let the model try, and
    # offline say so plainly rather than pretending
    return {"kind": "miss", "code": "NOT_FOUND", "phrase": phrase, "candidates": list(got[1])}


def _recolour(rest, table, selection):
    """'<target> (to|into|in)? <colour>' — see-through pieces stay see-through."""
    toks = rest.split()
    for take in (3, 2, 1):
        if len(toks) <= take:
            continue
        phrase = " ".join(toks[-take:])
        if not _is_colour(phrase):
            continue
        head = " ".join(toks[:-take])
        head = re.sub(r"\s+(to|into|in)$", "", head).strip()
        if not head:
            continue
        got = resolve(head, table, selection)
        if got[0] == "NEEDS_SELECTION":
            return _reject("NEEDS_SELECTION")
        if got[0] == "AMBIGUOUS":
            return _reject("AMBIGUOUS", head, got[1], got[2])
        if got[0] != "ok":
            return {"kind": "miss", "code": "NOT_FOUND", "phrase": head, "candidates": list(got[1])}
        buckets: dict = {}
        for i in got[1]:
            code = target_colour(phrase, table, _row(table, i)["colour"])
            if code is None:
                return None
            buckets.setdefault(code, []).append(i)
        ops = [{"op": "recolour", "ids": ids, "colour": c} for c, ids in sorted(buckets.items())]
        return {"kind": "ops", "ops": ops, "matched": got[1], "phrase": head}
    return None


def _units(word, direction):
    if not word:
        return 1 if direction in ("up", "down") else 1
    w = word.rstrip("s")
    if w == "stud":
        return 1 if direction in FLAT else None
    if w == "plate":
        return 1 if direction in ("up", "down") else None
    if w == "brick":
        return 3 if direction in ("up", "down") else None
    return None


def _vec(direction, n):
    v = DIRS[direction]
    return [v[0] * n, v[1] * n, v[2] * n]


def _move(rest, table, selection):
    pats = [rf"^(?P<t>.+?)\s+(?P<dir>{DIR_RE})(?:\s+by)?(?:\s+(?P<n>{NUM}))?(?:\s+(?P<unit>{UNIT}))?$",
            rf"^(?P<t>.+?)\s+(?P<n>{NUM})(?:\s+(?P<unit>{UNIT}))?\s+(?P<dir>{DIR_RE})$"]
    for pat in pats:
        m = re.match(pat, rest)
        if not m:
            continue
        direction = m.group("dir")
        mult = _units(m.group("unit"), direction)
        if mult is None:
            return None
        n = _num(m.group("n")) * mult
        if not (1 <= n <= 40):
            return None
        d = _vec(direction, n)
        return _with_target(m.group("t"), table, selection,
                            lambda ids: [{"op": "move", "ids": ids, "d": d, "settle": True}])
    return None


def _raise(verb, rest, table, selection):
    direction = "up" if verb in ("raise", "lift") else "down"
    m = re.match(rf"^(?P<t>.+?)(?:\s+by)?(?:\s+(?P<n>{NUM}))?(?:\s+(?P<unit>{UNIT}))?$", rest)
    if not m:
        return None
    mult = _units(m.group("unit"), direction)
    if mult is None:
        return None
    n = _num(m.group("n")) * mult
    if not (1 <= n <= 40):
        return None
    d = _vec(direction, n)
    return _with_target(m.group("t"), table, selection,
                        lambda ids: [{"op": "move", "ids": ids, "d": d, "settle": True}])


def _rotate(rest, table, selection):
    quarters = 1
    m = re.match(r"^(?P<t>.+?)\s+(?:around|round|180|half way|halfway)$", rest)
    if m:
        quarters, rest = 2, m.group("t")
    else:
        m = re.match(r"^(?P<t>.+?)\s+(?:left|anticlockwise|counter-?clockwise|270(?: degrees)?)$", rest)
        if m:
            quarters, rest = 3, m.group("t")
        else:
            m = re.match(rf"^(?P<t>.+?)\s+(?P<n>{NUM})\s+(?:times|quarter turns?)$", rest)
            if m:
                quarters, rest = ((_num(m.group("n")) - 1) % 4) + 1, m.group("t")
            else:
                m = re.match(r"^(?P<t>.+?)\s+(?:90|right|clockwise)(?: degrees)?$", rest)
                if m:
                    quarters, rest = 1, m.group("t")
    if quarters % 4 == 0:
        return None
    return _with_target(rest, table, selection,
                        lambda ids: [{"op": "rotate", "ids": ids, "quarters": quarters % 4, "settle": True}])


def _find_part(phrase, table):
    toks = _tok(phrase)
    m = re.search(r"(\d+)\s*x\s*(\d+)", phrase)
    kindw = next((t for t in toks if t in KINDS), None)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        hits = [k for k in table["kit"] if sorted((k["size"][0], k["size"][2])) == sorted((a, b))]
        if kindw:
            hits = [k for k in hits if k["kind"] == kindw] or hits
        else:
            hits = [k for k in hits if k["kind"] == "brick"] or hits
        if hits:
            return hits[0]["part"]
    for k in table["kit"]:
        if k["part"] == phrase.strip():
            return k["part"]
    return None


def _add(rest, table, selection):
    m = re.match(rf"^(?:(?P<n>{NUM})\s+)?(?P<body>.+?)(?:\s+(?P<how>on top(?: of .+)?|on .+|to .+))?$", rest)
    if not m:
        return None
    n = _num(m.group("n")) if m.group("n") else 1
    if not (1 <= n <= 8):
        return None
    body = m.group("body").strip()
    colour = 4
    toks = body.split()
    for take in (3, 2, 1):
        if len(toks) > take and _is_colour(" ".join(toks[:take])):
            codes = colour_codes(" ".join(toks[:take]), table)
            colour = codes[0] if codes else 4
            body = " ".join(toks[take:])
            break
    part = _find_part(body, table)
    if not part:
        return None
    on = None
    how = (m.group("how") or "").strip()
    tgt = re.sub(r"^(on top of|on top|on|to)\s*", "", how).strip()
    if tgt:
        got = resolve(tgt, table, selection)
        if got[0] == "NEEDS_SELECTION":
            return _reject("NEEDS_SELECTION")
        if got[0] == "AMBIGUOUS":
            return _reject("AMBIGUOUS", tgt, got[1], got[2])
        if got[0] != "ok":
            return None
        on = got[1][0]
    ops = [{"op": "add", "part": part, "colour": colour, "on": on, "quarters": 0, "settle": True}
           for _ in range(n)]
    return {"kind": "ops", "ops": ops, "matched": [], "phrase": body}


# ------------------------------------------------------- the FAST model (E.4)
SYSTEM = """You translate one instruction into edit ops for a LEGO model. You never give positions, \
coordinates, offsets, matrices or sizes; code computes all geometry. Choose only: an op, a target, a \
direction word, a whole number, a colour name, a part number from `kit`. If the request changes the \
design's shape or proportions (bigger ears, a longer tail, add a hat) answer `structural`. If you \
cannot tell which pieces are meant, answer `unclear`. Reply with one JSON object and nothing else.

Op shapes:
  {"op":"recolour","target":T,"colour":"<colour name>"}
  {"op":"delete","target":T,"cascade":false}
  {"op":"move","target":T,"dir":"up|down|left|right|forward|back","n":2,"unit":"stud|plate|brick"}
  {"op":"rotate","target":T,"quarters":1}
  {"op":"duplicate","target":T}
  {"op":"add","part":"3001","colour":"<colour name>","on":T_or_null,"quarters":0}
  T = {"ids":[..]} | {"groups":[..]} | {"body":".."} | {"colour":".."} | {"part":".."}
      | {"selection":true} | {"all":true} | {"phrase":"the front lights"}

Reply with exactly one of:
  {"route":"direct","say":"...","ops":[...]}
  {"route":"structural","why":"..."}
  {"route":"unclear","ask":"...","candidates":{"body":".."}}"""

FORBIDDEN = {"x", "y", "z", "pos", "position", "at", "d", "offset", "origin", "matrix",
             "coords", "coord", "size", "xyz", "translate", "transform", "location", "ldu",
             "studs", "plates", "height", "width", "depth", "angle", "degrees"}
OP_KEYS = {"recolour": {"op", "target", "colour"}, "delete": {"op", "target", "cascade"},
           "move": {"op", "target", "dir", "n", "unit"}, "rotate": {"op", "target", "quarters"},
           "duplicate": {"op", "target"}, "add": {"op", "part", "colour", "on", "quarters"}}
TARGET_KEYS = {"ids", "groups", "body", "colour", "part", "selection", "all", "phrase"}
UNITS = {"stud", "plate", "brick"}


class Refused(Exception):
    def __init__(self, code, why):
        super().__init__(why)
        self.code = code
        self.why = why


def _int_only(v, lo, hi, field):
    if isinstance(v, bool) or not isinstance(v, int):
        raise Refused("LLM_COORDINATE", f"'{field}' must be a whole number, got {v!r}")
    if not (lo <= v <= hi):
        raise Refused("NL_FAILED", f"'{field}' must be between {lo} and {hi}")
    return v


def _check_target(t, table, groups):
    if not isinstance(t, dict) or not t:
        raise Refused("NL_FAILED", "a target is exactly one of ids/groups/body/colour/part/selection/all/phrase")
    stray = sorted(set(t) - TARGET_KEYS)
    if stray:
        raise Refused("LLM_COORDINATE", f"'{stray[0]}' is not allowed in a target")
    if len(t) != 1:
        raise Refused("NL_FAILED", "a target is exactly one of ids/groups/body/colour/part/selection/all/phrase")
    (key, val), = t.items()
    known = {r["id"] for r in table["parts"]}
    if key == "ids":
        if not isinstance(val, list) or not val or not all(isinstance(i, str) for i in val):
            raise Refused("NL_FAILED", "'ids' must be a list of piece ids")
        bad = [i for i in val if i not in known]
        if bad:
            raise Refused("NL_FAILED", f"no such piece: {bad[0]}")
    elif key == "groups":
        if not isinstance(val, list) or not val or any(g not in groups for g in val):
            raise Refused("NL_FAILED", "'groups' must name groups from the list I gave you")
    elif key == "body":
        if val not in {b["name"] for b in table["bodies"]}:
            raise Refused("NL_FAILED", f"no such body: {val!r}")
    elif key == "colour":
        if not isinstance(val, str) or not colour_codes(val, table):
            raise Refused("NL_FAILED", f"unknown colour: {val!r}")
    elif key == "part":
        if not isinstance(val, str) or val not in {r["part"] for r in table["parts"]}:
            raise Refused("NL_FAILED", f"no such part in this model: {val!r}")
    elif key in ("selection", "all"):
        if val is not True:
            raise Refused("NL_FAILED", f"'{key}' must be true")
    elif key == "phrase":
        if not isinstance(val, str) or not val.strip():
            raise Refused("NL_FAILED", "'phrase' must be words")
    return t


def validate_reply(raw, table, groups=()):
    """Strict allow-list. Anything that could hold a coordinate refuses the
    whole reply — there is no partial acceptance."""
    text = raw if isinstance(raw, str) else json.dumps(raw)
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise Refused("NL_FAILED", "the reply wasn't a JSON object")
    try:
        obj = json.loads(m.group(0))
    except (ValueError, TypeError):
        raise Refused("NL_FAILED", "the reply wasn't valid JSON")
    if not isinstance(obj, dict):
        raise Refused("NL_FAILED", "the reply wasn't a JSON object")
    route = obj.get("route")
    if route == "structural":
        if set(obj) - {"route", "why"}:
            raise Refused("NL_FAILED", "unexpected fields alongside 'structural'")
        return {"route": "structural", "why": str(obj.get("why", ""))}
    if route == "unclear":
        if set(obj) - {"route", "ask", "candidates"}:
            raise Refused("NL_FAILED", "unexpected fields alongside 'unclear'")
        cand = obj.get("candidates")
        if cand is not None and not isinstance(cand, dict):
            raise Refused("NL_FAILED", "'candidates' must be an object")
        return {"route": "unclear", "ask": str(obj.get("ask", "")), "candidates": cand or {}}
    if route != "direct":
        raise Refused("NL_FAILED", "'route' must be direct, structural or unclear")
    if set(obj) - {"route", "say", "ops"}:
        bad = sorted(set(obj) - {"route", "say", "ops"})
        raise Refused("LLM_COORDINATE", f"unexpected field '{bad[0]}'")
    ops = obj.get("ops")
    if not isinstance(ops, list) or not ops or len(ops) > 8:
        raise Refused("NL_FAILED", "'ops' must be a list of 1 to 8 ops")
    out = []
    for o in ops:
        if not isinstance(o, dict):
            raise Refused("NL_FAILED", "each op must be an object")
        kind = o.get("op")
        if kind not in OP_KEYS:
            raise Refused("NL_FAILED", f"unknown op {kind!r}")
        extra = sorted(set(o) - OP_KEYS[kind])
        if extra:
            raise Refused("LLM_COORDINATE", f"'{extra[0]}' is not allowed on a {kind} op")
        clean = {"op": kind}
        if kind != "add":
            clean["target"] = _check_target(o.get("target"), table, groups)
        if kind == "recolour":
            if not isinstance(o.get("colour"), str) or not colour_codes(o["colour"], table):
                raise Refused("NL_FAILED", f"unknown colour {o.get('colour')!r}")
            clean["colour"] = o["colour"]
        elif kind == "delete":
            if o.get("cascade") not in (None, True, False):
                raise Refused("NL_FAILED", "'cascade' must be true or false")
            clean["cascade"] = bool(o.get("cascade"))
        elif kind == "move":
            if o.get("dir") not in DIRS:
                raise Refused("NL_FAILED", f"unknown direction {o.get('dir')!r}")
            clean["dir"] = o["dir"]
            clean["n"] = _int_only(o.get("n", 1), 1, 40, "n")
            unit = o.get("unit")
            if unit is not None and unit not in UNITS:
                raise Refused("NL_FAILED", f"unknown unit {unit!r}")
            clean["unit"] = unit
        elif kind == "rotate":
            clean["quarters"] = _int_only(o.get("quarters", 1), 0, 3, "quarters")
        elif kind == "add":
            part = o.get("part")
            if not isinstance(part, str) or part not in {k["part"] for k in table["kit"]}:
                raise Refused("NL_FAILED", f"{part!r} isn't a part I can add")
            clean["part"] = part
            col = o.get("colour", "Red")
            if not isinstance(col, str) or not colour_codes(col, table):
                raise Refused("NL_FAILED", f"unknown colour {col!r}")
            clean["colour"] = col
            on = o.get("on")
            clean["on"] = None if on in (None, "null") else _check_target(on, table, groups)
            clean["quarters"] = _int_only(o.get("quarters", 0), 0, 3, "quarters")
        out.append(clean)
    return {"route": "direct", "say": str(obj.get("say", "")), "ops": out}


def groups_of(table):
    """Parts grouped the way the model is allowed to point at them."""
    buckets: dict = {}
    for r in table["parts"]:
        key = (r["part"], r["colour"], r["body"], tuple(r["where"]))
        buckets.setdefault(key, []).append(r)
    ordered = sorted(buckets.items(), key=lambda kv: -len(kv[1]))
    out, index = [], {}
    for n, ((part, colour, body, where), rows) in enumerate(ordered[:150]):
        g = f"g{n}"
        index[g] = [r["id"] for r in rows]
        out.append({"g": g, "part": part, "name": rows[0]["name"], "colour": rows[0]["colour_name"],
                    "body": body, "tags": rows[0]["tags"], "where": list(where),
                    "ids": [r["id"] for r in rows][:40], "more": max(0, len(rows) - 40)})
    rest = sum(len(rows) for _, rows in ordered[150:])
    if rest:
        out.append({"g": "rest", "pieces": rest})
    return out, index


def _prompt(text, table, selection, groups):
    return json.dumps({
        "instruction": text,
        "selection": list(selection or []),
        "bodies": [{"name": b["name"], "pieces": b["count"],
                    "colours": sorted({partlib.colour_name(c) for c in b["colours"]}),
                    "where": sorted({w for r in table["parts"] if r["body"] == b["name"] for w in r["where"]})}
                   for b in table["bodies"][:40]],
        "groups": groups,
        "colours": sorted({r["colour_name"] for r in table["parts"]}) +
                   [p["name"] for p in table["palette"][:18]],
        "kit": [{"part": k["part"], "name": k["name"]} for k in table["kit"]],
    })


def offline() -> bool:
    return os.environ.get("PROVIDER") == "mock" or os.environ.get("DEMO_SAFE") == "1"


def default_ask(prompt: str, system: str) -> str:
    from brickify import pipeline as c
    return c.claude(prompt, [], system, c.FAST_MODEL, timeout=20, max_tokens=1500, effort="low")


def fast(text, table, selection, ask):
    """One call, one retry carrying the validation error, then we stop."""
    groups, index = groups_of(table)
    msg = _prompt(text, table, selection, groups)
    names = [g["g"] for g in groups if "g" in g]
    last = None
    for attempt in range(2):
        prompt = msg if attempt == 0 else msg + f"\n\nYour last reply was refused: {last}. Try again."
        try:
            raw = ask(prompt, SYSTEM)
        except Exception as e:                      # network, timeout, bad key
            raise Refused("NL_FAILED", f"the model call failed: {e}")
        try:
            return validate_reply(raw, table, names), index
        except Refused as r:
            last = r.why
            if attempt:
                raise
    raise Refused("NL_FAILED", "no usable reply")


def to_ops(reply, table, selection, index):
    """The model's shapes -> real ops. Every number here is computed by code."""
    ops = []
    for o in reply["ops"]:
        kind = o["op"]
        if kind == "add":
            on = None
            if o["on"]:
                ids = _expand(o["on"], table, selection, index)
                if isinstance(ids, tuple):
                    return ids
                on = ids[0] if ids else None
            codes = colour_codes(o["colour"], table)
            ops.append({"op": "add", "part": o["part"], "colour": codes[0], "on": on,
                        "quarters": o["quarters"], "settle": True})
            continue
        ids = _expand(o["target"], table, selection, index)
        if isinstance(ids, tuple):
            return ids
        if not ids:
            return ("NOT_FOUND", [])
        if kind == "recolour":
            buckets: dict = {}
            for i in ids:
                code = target_colour(o["colour"], table, _row(table, i)["colour"])
                buckets.setdefault(code, []).append(i)
            ops += [{"op": "recolour", "ids": v, "colour": c} for c, v in sorted(buckets.items())]
        elif kind == "delete":
            ops.append({"op": "delete", "ids": ids, "cascade": bool(o["cascade"])})
        elif kind == "duplicate":
            ops.append({"op": "duplicate", "ids": ids})
        elif kind == "rotate":
            q = o["quarters"] % 4
            if q == 0:
                continue
            ops.append({"op": "rotate", "ids": ids, "quarters": q, "settle": True})
        elif kind == "move":
            mult = {"stud": 1, "plate": 1, "brick": 3, None: 1}[o.get("unit")]
            if o["dir"] in ("up", "down") and o.get("unit") == "stud":
                return ("NOT_FOUND", [])
            n = o["n"] * mult
            ops.append({"op": "move", "ids": ids, "d": _vec(o["dir"], n), "settle": True})
    return ops


def _expand(target, table, selection, index):
    (key, val), = target.items()
    if key == "ids":
        return list(dict.fromkeys(val))
    if key == "groups":
        out: list = []
        for g in val:
            out += index.get(g, [])
        return list(dict.fromkeys(out))
    if key == "body":
        return [r["id"] for r in table["parts"] if r["body"] == val]
    if key == "colour":
        codes = set(colour_codes(val, table))
        return [r["id"] for r in table["parts"] if r["colour"] in codes]
    if key == "part":
        return [r["id"] for r in table["parts"] if r["part"] == val]
    if key == "selection":
        return list(selection or [])
    if key == "all":
        return [r["id"] for r in table["parts"]]
    got = resolve(val, table, selection)
    if got[0] == "ok":
        return got[1]
    return (got[0], got[1] if len(got) > 1 else [], val) + ((got[2],) if len(got) > 2 else ())


# ------------------------------------------------------------------- router
def handle(session, text, selection=None, base=None, mode="auto", ask=default_ask, table=None):
    """text -> (Version | None, the `edit` object the API returns)."""
    from brickify import edits as E
    from serialize import edit_json, nav_json

    model = session.model_at()
    if model is None:
        return None, dict(nav_json("direct", E.HUMAN["NO_MODEL"], accepted=False), code="NO_MODEL")
    if base is not None and base != session.head:
        return None, dict(nav_json("direct", E.HUMAN["STALE"], accepted=False), code="STALE")
    table = table or E.table(model)
    selection = [s for s in (selection or []) if any(r["id"] == s for r in table["parts"])]

    pre = None
    if mode != "brief":
        pre = preparse(text, table, selection)
    miss = pre if (pre and pre["kind"] == "miss") else None
    if miss:
        pre = None
    if pre and pre["kind"] == "nav":
        v = session.undo() if pre["dir"] == "undo" else session.redo()
        word = "Went back one change" if pre["dir"] == "undo" else "Went forward one change"
        return v, nav_json("nav", word)
    if pre and pre["kind"] == "reject":
        return None, _fail("preparse", pre["code"], pre["human"], pre["candidates"],
                           [("router", "edit.match", pre["human"], "fail")])
    if pre and pre["kind"] == "ops":
        head = [("router", "edit.match", _match_text(pre, table, selection), "ok")]
        return _run(session, chunk(pre["ops"]), text, "preparse", head, edit_json)

    # an injected `ask` is a deliberate test double and always runs; the real
    # one is skipped when the demo is offline
    use_model = mode != "brief" and ask is not None and not (ask is default_ask and offline())
    if use_model:
        try:
            reply, index = fast(text, table, selection, ask)
        except Refused as r:
            return None, _fail("fast", r.code, HUMAN[r.code], [],
                               [("router", "edit.route",
                                 "The model tried to place a piece by coordinates, which it isn't "
                                 "allowed to do. Nothing was changed."
                                 if r.code == "LLM_COORDINATE" else f"I couldn't use that answer: {r.why}",
                                 "fail")])
        if reply["route"] == "direct":
            ops = to_ops(reply, table, selection, index)
            if isinstance(ops, tuple):
                code, cands = ops[0], ops[1]
                phrase = ops[2] if len(ops) > 2 else text
                names = ops[3] if len(ops) > 3 else ""
                human = HUMAN[code].format(phrase=_bare(phrase), n=len(cands), names=names)
                return None, _fail("fast", code, human, cands,
                                   [("router", "edit.match", human, "fail")])
            head = [("router", "edit.match", reply["say"] or "Matched what you asked for", "ok"),
                    ("router", "edit.route", "That's a quick change, no redesign needed", "ok")]
            return _run(session, chunk(ops), text, "fast", head, edit_json)
        if reply["route"] == "unclear":
            cands = _candidates(reply.get("candidates") or {}, table, selection)
            human = reply.get("ask") or HUMAN["NL_FAILED"]
            return None, _fail("fast", "AMBIGUOUS", human, cands,
                               [("router", "edit.match", human, "fail")])
        # structural -> the brief path
        if mode == "direct":
            return None, _fail("fast", "STRUCTURAL_UNAVAILABLE", HUMAN["STRUCTURAL_UNAVAILABLE"], [],
                               [("router", "edit.route", HUMAN["STRUCTURAL_UNAVAILABLE"], "fail")])
    elif mode != "brief":
        if miss:
            human = HUMAN["NOT_FOUND"].format(phrase=_bare(miss["phrase"]))
            return None, _fail("preparse", "NOT_FOUND", human, miss.get("candidates") or [],
                               [("router", "edit.match", human, "fail")])
        if mode == "direct":
            return None, _fail("preparse", "NL_FAILED", HUMAN["NL_FAILED"], [],
                               [("router", "edit.route", HUMAN["NL_FAILED"], "fail")])
        cur = session.versions.get(session.head)
        if not cur or not cur.build.provenance.get("run"):
            return None, _fail("preparse", "NL_FAILED", HUMAN["NL_FAILED"], [],
                               [("router", "edit.route", HUMAN["NL_FAILED"], "fail")])

    return _brief(session, text, mode)


def _run(session, ops, text, path, head, edit_json):
    from brickify import edits as E
    try:
        v, res = session.edit_parts(ops, base=None, text=text, path=path)
    except E.OpError as e:
        return None, _fail(path, e.code, e.human, [],
                           head + [("inspector", "edit.gate", e.human, "fail")])
    return v, edit_json(res, path, tape=_tape(head + list(res.events)))


def _brief(session, text, mode):
    from serialize import edit_json, nav_json
    cur = session.versions.get(session.head)
    if not cur or not cur.build.provenance.get("run"):
        return None, _fail("brief", "STRUCTURAL_UNAVAILABLE", HUMAN["STRUCTURAL_UNAVAILABLE"], [],
                           [("router", "edit.route", HUMAN["STRUCTURAL_UNAVAILABLE"], "fail")])
    if mode == "direct":
        return None, _fail("brief", "STRUCTURAL_UNAVAILABLE", HUMAN["STRUCTURAL_UNAVAILABLE"], [],
                           [("router", "edit.route", HUMAN["STRUCTURAL_UNAVAILABLE"], "fail")])
    from tape import Tape
    tape = Tape()
    tape.emit("router", "edit.route", "That needs a redesign, so I'm rewriting the plan (1-3 minutes)")
    v = session.edit(text, tape=tape)
    dropped = v.op.get("dropped") or []
    human = f"Rebuilt from a new plan: {len(v.build.parts)} pieces"
    kept = v.op.get("reapplied") or []
    if kept or dropped:
        human += f" · kept {len(kept)} of your {len(kept) + len(dropped)} earlier changes"
    out = nav_json("brief", human)
    out["tape"] = [e for e in tape.events if e.get("kind") != "geometry"]
    return v, out


def _candidates(spec, table, selection):
    if not spec:
        return []
    got = _expand(spec, table, selection, {}) if len(spec) == 1 else []
    return got if isinstance(got, list) else []


def _match_text(pre, table, selection):
    ids = pre.get("matched") or []
    if not ids:
        return "Got it"
    if selection and set(ids) == set(selection):
        return f"Using the {len(ids)} piece{'s' if len(ids) != 1 else ''} you selected"
    names = {_row(table, i)["name"] for i in ids}
    what = next(iter(names)) if len(names) == 1 else "pieces"
    return f"“{pre.get('phrase', '')}” matched {len(ids)} {what}".strip()


MAX_IDS = 256
MAX_OPS = 16


def chunk(ops):
    """A phrase like 'make it red' can name thousands of pieces. Recolouring
    and removing don't care how the pieces are grouped, so split those into
    op-sized batches; anything that moves as a group stays whole."""
    out = []
    for o in ops:
        ids = o.get("ids")
        if not ids or len(ids) <= MAX_IDS or o["op"] not in ("recolour", "delete"):
            out.append(o)
            continue
        for i in range(0, len(ids), MAX_IDS):
            out.append(dict(o, ids=ids[i:i + MAX_IDS]))
    return out


def _tape(events):
    out, t = [], 0
    for actor, kind, text, status in events:
        t += 1
        out.append({"t": t, "actor": actor, "kind": kind, "text": text, "status": status,
                    "ms": 0, "tokens": 0})
    return out


def _fail(path, code, human, candidates, events):
    return {"accepted": False, "dry_run": False, "path": path, "code": code, "human": human,
            "ops": [], "changed": [], "added": [], "removed": [], "landed": [],
            "candidates": list(candidates), "culprits": [], "offer": None, "tape": _tape(events)}


# --------------------------------------------------------- chips (D.2)
def suggest(session, table, limit=4):
    """Chips derived from the model itself, each proved by a real dry run."""
    rows = table["parts"]
    colours = sorted(table["colours"], key=lambda c: -c["count"])
    main = colours[0]["name"] if colours else "Red"
    contrast = next((p["name"] for p in table["palette"]
                     if p["name"].lower() != main.lower() and not p["trans"]), "Yellow")
    ideas = []
    if any("light" in r["tags"] for r in rows):
        ideas.append("Make the lights blue")
    if any("wheel" in r["tags"] for r in rows):
        ideas.append("Make the wheels red")
    ideas.append(f"Make the {main.lower()} pieces {contrast.lower()}")
    big = [b for b in sorted(table["bodies"], key=lambda b: -b["count"])
           if b["count"] > 1 and not _auto_body(b["name"])]
    if len(big) > 1:
        ideas.append(f"Make the {big[0]['name']} {contrast.lower()}")
    ideas.append("Remove the top piece")
    if len(colours) > 1:
        ideas.append(f"Make the {colours[1]['name'].lower()} pieces {main.lower()}")
    out = []
    for idea in ideas:
        if len(out) >= limit:
            break
        pre = preparse(idea, table, [])
        if not pre or pre["kind"] != "ops":
            continue
        try:
            _, res = session.edit_parts(chunk(pre["ops"]), dry_run=True, base=None)
        except Exception:
            continue
        if res.accepted:
            out.append(idea)
    return out
