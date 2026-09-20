"""Part-level editing of a finished LDraw model, with one gate in front of it.

`apply(model, ops)` is the only way a Model changes. It validates the op list,
applies the ops in order on a working copy, settles what it is asked to settle,
runs the gate (collisions + connectivity + stands, all baseline-relative) once
on the final state, and returns either a new Model + LDraw text or a rejection
that changed nothing at all.

Nothing here is random, nothing here calls a model, nothing here reads a clock:
replaying the same resolved ops on the same input reproduces the same bytes.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace

import numpy as np

from . import check, kit, partlib

STUD = kit.STUD
PLATE = kit.PLATE
UP = np.array([0.0, -1.0, 0.0])

MAX_OPS = 16
MAX_IDS = 256
MAX_PARTS = 5000

GATES = [0]   # full gates run; the settle budget and test 7 read this


class OpError(ValueError):
    """A malformed request: HTTP 400, never rounded into something legal."""

    def __init__(self, human: str, code: str = "BAD_OP"):
        super().__init__(human)
        self.human = human
        self.code = code


# ------------------------------------------------------------------- model
@dataclass(frozen=True, eq=False)
class EPart:
    id: str
    pid: str
    ref: str
    colour: int
    body: str
    M: np.ndarray           # 4x4 world transform
    step: int
    text: str | None = None  # the verbatim source line, while untouched


@dataclass(frozen=True, eq=False)
class Model:
    header: tuple
    parts: tuple
    lib: dict = field(default_factory=dict)
    next_id: int = 0
    cache: dict = field(default_factory=dict, compare=False, repr=False)


@dataclass(frozen=True, eq=False)
class Result:
    accepted: bool
    code: str | None
    human: str
    model: Model | None = None
    ldr: str | None = None
    ops: tuple = ()
    changed: tuple = ()
    added: tuple = ()
    removed: tuple = ()
    landed: tuple = ()
    culprits: tuple = ()
    offer: dict | None = None
    stability: dict = field(default_factory=dict)
    events: tuple = ()


# ------------------------------------------------------------------ parsing
def _fmt(v: float) -> str:
    return format(round(float(v), 3) + 0.0, ".10g")


def line_of(p: EPart) -> str:
    m = p.M
    nums = [m[0, 3], m[1, 3], m[2, 3],
            m[0, 0], m[0, 1], m[0, 2], m[1, 0], m[1, 1], m[1, 2], m[2, 0], m[2, 1], m[2, 2]]
    return "1 " + str(int(p.colour)) + " " + " ".join(_fmt(v) for v in nums) + " " + p.ref


_COLOUR_TOKEN = re.compile(r"^(\s*1\s+)(\S+)")


def _recoloured_text(text: str | None, colour: int) -> str | None:
    """Only the colour token changes, so every other byte of the line survives."""
    if text is None:
        return None
    out, n = _COLOUR_TOKEN.subn(lambda m: m.group(1) + str(int(colour)), text, count=1)
    return out if n else None


def flatten(text: str) -> tuple:
    """Any .ldr/.mpd -> (main model text, library text, body name per type-1 line).

    Sub-model references are expanded in place (matrices composed, colour 16
    inherited) so every type-1 line of the result references a real part."""
    blocks, names, pre = _split_files(text)
    if pre.strip() and not text.lstrip().startswith("0 FILE"):
        main_lines = pre.splitlines()
        lib_blocks = list(zip(names, blocks))
    elif blocks:
        main_lines = blocks[0]
        lib_blocks = list(zip(names[1:], blocks[1:]))
    else:
        main_lines, lib_blocks = pre.splitlines(), []
    # the viewer owns the colour table; drop it and anything above it
    last_colour = max((i for i, l in enumerate(main_lines) if l.startswith("0 !COLOUR")), default=-1)
    if last_colour >= 0:
        main_lines = main_lines[last_colour + 1:]

    lib = {partlib.norm_ref(n): ls for n, ls in lib_blocks}
    lib_text = "\n".join("0 FILE " + n + "\n" + "\n".join(ls) for n, ls in lib_blocks)

    out: list[str] = []
    bodies: list[str] = []
    _expand(main_lines, np.eye(4), None, lib, out, bodies, 0, None)
    return "\n".join(out), lib_text, bodies


def _split_files(text: str):
    pre: list[str] = []
    names: list[str] = []
    blocks: list[list[str]] = []
    cur: list[str] | None = None
    for line in text.splitlines():
        if line.startswith("0 FILE "):
            names.append(line[7:].strip())
            cur = []
            blocks.append(cur)
        elif cur is None:
            pre.append(line)
        else:
            cur.append(line)
    return blocks, names, "\n".join(pre)


_SUB_PREFIX = re.compile(r"^\d+\s*-\s*")


def _submodel_name(ref: str) -> str:
    base = ref.replace("\\", "/").rsplit("/", 1)[-1]
    base = re.sub(r"\.(ldr|mpd|dat)$", "", base, flags=re.I)
    return _SUB_PREFIX.sub("", base).strip() or base


def _expand(lines, M, colour, lib, out, bodies, depth, body):
    """Write `lines` transformed by `M` into `out`, expanding sub-models.
    At depth 0 every other line (the header, comments) is passed through
    byte for byte; deeper only parts and steps survive."""
    cur_body = body
    for line in lines:
        t = line.split(None, 14)          # refs may contain spaces ("1621 - Vehicle.ldr")
        if t and t[0] == "0" and len(t) >= 3 and t[1] == "!BODY":
            cur_body = " ".join(t[2:])
            continue
        if not t or t[0] != "1" or len(t) < 15:
            if t and t[0] == "0" and len(t) >= 2 and t[1] == "STEP":
                out.append("0 STEP")
            elif depth == 0:
                out.append(line)
            continue
        try:
            nums = [float(v) for v in t[2:14]]
            c = int(t[1])
        except ValueError:
            continue
        S = np.eye(4)
        S[:3, 3] = nums[0:3]
        S[:3, :3] = np.array(nums[3:12], float).reshape(3, 3)
        W = M @ S
        eff = colour if (c == 16 and colour is not None) else c
        ref = t[14].strip()
        sub = lib.get(partlib.norm_ref(ref))
        if sub is not None and re.search(r"\.(ldr|mpd)$", ref, re.I) and depth < 8:
            name = _submodel_name(ref) if depth == 0 else (cur_body or _submodel_name(ref))
            _expand(sub, W, eff, lib, out, bodies, depth + 1, name)
            out.append("0 STEP")
            continue
        p = EPart("", partlib.pid_of(ref), ref, eff, "", W, 0, None)
        out.append(line if depth == 0 and c != 16 else line_of(p))
        bodies.append(cur_body or "")


def parse(ldr: str, ids: list | None = None, bodies: list | None = None,
          lib: dict | None = None, next_id: int = 0) -> Model:
    header: list[str] = []
    parts: list[EPart] = []
    step = 0
    seen_part = False
    for line in ldr.splitlines():
        t = line.split(None, 14)
        if t and t[0] == "1" and len(t) >= 15:
            seen_part = True
            try:
                nums = [float(v) for v in t[2:14]]
                colour = int(t[1])
            except ValueError:
                continue
            M = np.eye(4)
            M[:3, 3] = nums[0:3]
            M[:3, :3] = np.array(nums[3:12], float).reshape(3, 3)
            i = len(parts)
            ref = t[14].strip()
            pk = ids[i] if ids and i < len(ids) else f"p{i}"
            bd = bodies[i] if bodies and i < len(bodies) else ""
            parts.append(EPart(pk, partlib.pid_of(ref), ref, colour, bd, M, step, line))
        elif t and t[0] == "0" and len(t) >= 2 and t[1] == "STEP":
            if seen_part:
                step += 1
        elif not seen_part:
            header.append(line)
    if len(parts) > MAX_PARTS:
        raise OpError(f"That model has {len(parts)} pieces, which is more than I can edit.", "TOO_BIG")
    model = Model(tuple(header), tuple(parts), lib or {}, next_id)
    if any(not p.body for p in parts):
        model = _cluster_bodies(model)
    return model


def _cluster_bodies(model: Model) -> Model:
    """Parts with no body name: connected same-colour clusters, named for their
    colour ('red', 'red 2', ...) — the words a person would use."""
    sc = scene(model)
    parent = list(range(len(model.parts)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for a, b in sc["edges"]:
        pa, pb = model.parts[a], model.parts[b]
        if pa.body or pb.body or pa.colour != pb.colour:
            continue
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    groups: dict[int, list[int]] = {}
    for i, p in enumerate(model.parts):
        if not p.body:
            groups.setdefault(find(i), []).append(i)
    by_colour: dict[int, list[list[int]]] = {}
    for root in sorted(groups, key=lambda r: min(groups[r])):
        idxs = groups[root]
        by_colour.setdefault(model.parts[idxs[0]].colour, []).append(idxs)
    parts = list(model.parts)
    for colour, clusters in by_colour.items():
        base = partlib.colour_name(colour).lower()
        for k, idxs in enumerate(clusters, start=1):
            name = base if len(clusters) == 1 else f"{base} {k}"
            for i in idxs:
                parts[i] = replace(parts[i], body=name)
    return Model(model.header, tuple(parts), model.lib, model.next_id)


def write(model: Model) -> str:
    out = list(model.header)
    cur = None
    for p in model.parts:
        if cur is not None and p.step != cur:
            out.append("0 STEP")
        cur = p.step
        out.append(p.text if p.text is not None else line_of(p))
    out.append("0 STEP")
    return "\n".join(out) + "\n"


# ------------------------------------------------------- geometry & the scene
def _samples_for(lib):
    return lambda pid: partlib.samples(pid, lib)


def _grown(pid: str, lib) -> np.ndarray:
    """Body box grown 1 LDU, on the 4-LDU lattice: 'these two touch'."""
    g = partlib.info(pid, lib)
    x0, x1, y0, y1, z0, z1 = g.box
    spans = ((x0 - 1, x1 + 1), (y0 - 1, y1 + 1), (z0 - 1, z1 + 1))
    axes = [np.arange(a, b + 1e-6, 4.0) for a, b in spans]
    axes = [a if len(a) else np.array([(lo + hi) / 2]) for a, (lo, hi) in zip(axes, spans)]
    X, Y, Z = np.meshgrid(*axes, indexing="ij")
    return np.stack([X.ravel(), Y.ravel(), Z.ravel(), np.ones(X.size)], axis=1)


def _world_studs(p: EPart, lib):
    g = partlib.info(p.pid, lib)
    R, t = p.M[:3, :3], p.M[:3, 3]
    studs = [(R @ np.asarray(pos) + t, R @ np.asarray(ax)) for pos, ax in g.studs]
    anti = [(R @ np.asarray(pos) + t, R @ np.asarray(ax)) for pos, ax in g.antistuds]
    return studs, anti


def _cell(v, size=4.0):
    return (int(math.floor(v[0] / size)), int(math.floor(v[1] / size)), int(math.floor(v[2] / size)))


def scene(model: Model) -> dict:
    """Everything the gate needs about one arrangement of parts, cached."""
    hit = model.cache.get("scene")
    if hit is not None:
        return hit
    parts, lib = model.parts, model.lib
    sample = _samples_for(lib)
    pts = [(p.M @ sample(p.pid).T).T[:, :3] for p in parts]
    ground = max((w[:, 1].max() for w in pts), default=0.0)
    grounded = {i for i, w in enumerate(pts) if w[:, 1].max() > ground - PLATE}
    edges = _edges(parts, pts, lib)
    out = {"pts": pts, "ground": float(ground), "grounded": grounded, "edges": edges}
    out["loose"] = _loose(parts, edges, grounded)
    model.cache["scene"] = out
    return out


def _edges(parts, pts, lib) -> set:
    edges: set = set()
    # (s) studs into antistuds
    index: dict = {}
    for i, p in enumerate(parts):
        _, anti = _world_studs(p, lib)
        for pos, ax in anti:
            index.setdefault(_cell(pos, 4.0), []).append((i, pos, ax))
    if index:
        for i, p in enumerate(parts):
            studs, _ = _world_studs(p, lib)
            for pos, ax in studs:
                cx, cy, cz = _cell(pos, 4.0)
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        for dz in (-1, 0, 1):
                            for j, apos, aax in index.get((cx + dx, cy + dy, cz + dz), ()):
                                if j == i:
                                    continue
                                if np.linalg.norm(pos - apos) <= 2.0 and float(ax @ aax) >= 0.99:
                                    edges.add((min(i, j), max(i, j)))
    # (x) designed interlocks
    by_pid: dict = {}
    for i, p in enumerate(parts):
        by_pid.setdefault(p.pid, []).append(i)
    for pair in check.EXEMPT:
        a, b = tuple(pair) if len(pair) == 2 else (next(iter(pair)), next(iter(pair)))
        for i in by_pid.get(a, ()):
            for j in by_pid.get(b, ()):
                if i != j and _share_bucket(pts[i], pts[j]):
                    edges.add((min(i, j), max(i, j)))
    # (c) contact, for parts whose shape we had to guess
    odd = [i for i, p in enumerate(parts) if partlib.info(p.pid, lib).source != "kit"]
    if odd:
        cells: dict = {}
        cache: dict = {}
        for i, p in enumerate(parts):
            g = cache.get(p.pid)
            if g is None:
                g = cache[p.pid] = _grown(p.pid, lib)
            w = (p.M @ g.T).T[:, :3]
            for key in map(tuple, np.floor(w / 4.0).astype(int)):
                cells.setdefault(key, set()).add(i)
        oddset = set(odd)
        hits: dict = {}
        for owners in cells.values():
            if len(owners) < 2:
                continue
            ow = sorted(owners)
            for a_i in range(len(ow)):
                for b_i in range(a_i + 1, len(ow)):
                    a, b = ow[a_i], ow[b_i]
                    if a in oddset or b in oddset:
                        hits[(a, b)] = hits.get((a, b), 0) + 1
        for (a, b), n in hits.items():
            if n >= 3:
                edges.add((a, b))
    return edges


def _share_bucket(pa, pb) -> bool:
    A = {tuple(k) for k in np.floor(pa / 4.0).astype(int)}
    for key in map(tuple, np.floor(pb / 4.0).astype(int)):
        if key in A:
            return True
    return False


def _loose(parts, edges, grounded) -> set:
    parent = list(range(len(parts)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    ok = {find(i) for i in grounded}
    return {parts[i].id for i in range(len(parts)) if find(i) not in ok}


def pairs(model: Model) -> set:
    hit = model.cache.get("pairs")
    if hit is None:
        r = check.check_world(list(model.parts), detail=True, same_body=True,
                              samples=_samples_for(model.lib))
        hit = model.cache["pairs"] = {frozenset((model.parts[a].id, model.parts[b].id))
                                      for a, b in r["pairs"]}
    return hit


def stand_of(model: Model) -> dict:
    hit = model.cache.get("stands")
    if hit is None:
        hit = model.cache["stands"] = check.stands(list(model.parts), detail=True,
                                                   samples=_samples_for(model.lib))
    return hit


# --------------------------------------------------------------------- gate
SIDE = {"-z": "front", "+z": "back", "-x": "left", "+x": "right"}

HUMAN = {
    "COLLIDES": "That would push it into the {name} next to it. Nothing was changed.",
    "FLOATING": "There's nothing there for it to click onto, so it would just float. Nothing was changed.",
    "NO_SPOT": "I looked for a free spot nearby and couldn't find one that holds. Try somewhere else.",
    "TIPS": "That would make it tip over toward the {side}. Nothing was changed.",
    "TIPS_WORSE": "It already leans, and that would make it lean more. Nothing was changed.",
    "EMPTY": "That would remove every piece.",
    "MIXED_TILT": "Those pieces sit at different angles, so they can't slide together. Move them one group at a time.",
    "UNKNOWN_ID": "One of those pieces isn't in the model any more.",
    "STALE": "The model changed while you were doing that. Try again.",
    "NO_MODEL": "Open a model first.",
}


def gate(before: Model, after: Model, touched: set) -> dict:
    GATES[0] += 1
    out = {"ok": True, "code": None, "culprits": [], "new_pairs": [], "new_loose": []}
    p0, p1 = pairs(before), pairs(after)
    new_pairs = p1 - p0
    if new_pairs:
        ids = {i for pair in new_pairs for i in pair}
        out.update(ok=False, code="COLLIDES", new_pairs=[sorted(p) for p in new_pairs],
                   culprits=sorted(ids - set(touched)) or sorted(ids))
        out["stands"] = stand_of(before)
        return out
    s0 = scene(before)
    s1 = scene(after)
    new_loose = s1["loose"] - s0["loose"]
    still_loose = {i for i in touched if i in s1["loose"]}
    if new_loose or still_loose:
        out["new_loose"] = sorted(new_loose | still_loose)
        if (set(touched) & new_loose) or still_loose:
            out.update(ok=False, code="FLOATING", culprits=sorted(new_loose - set(touched)))
        else:
            out.update(ok=False, code="WOULD_FALL", culprits=sorted(new_loose))
        out["stands"] = stand_of(before)
        return out
    a, b = stand_of(before), stand_of(after)
    out["stands"] = b
    if a["stable"] and not b["stable"]:
        out.update(ok=False, code="TIPS")
    elif not a["stable"] and b["margin"] < a["margin"] - 0.01:
        out.update(ok=False, code="TIPS_WORSE")
    return out


def gate_human(model: Model, verdict: dict, verb: str = "Moving") -> str:
    code = verdict["code"]
    if code == "COLLIDES":
        names = [_name(model, i) for i in verdict["culprits"][:1]] or ["piece"]
        return HUMAN["COLLIDES"].format(name=names[0])
    if code == "TIPS":
        side = SIDE.get((verdict.get("stands") or {}).get("direction"), "side")
        return HUMAN["TIPS"].format(side=side)
    if code == "WOULD_FALL":
        return _would_fall(model, verdict["culprits"], verb)
    return HUMAN.get(code, "That change didn't work. Nothing was changed.")


def _would_fall(model: Model, ids, verb: str) -> str:
    counts: dict = {}
    for i in ids:
        counts[_name(model, i)] = counts.get(_name(model, i), 0) + 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:3]
    listed = ", ".join(f"{n} {name}" for name, n in top)
    one = len(ids) == 1
    tail = ("Remove it too?" if one else "Remove those too?") if verb == "Removing" else "Nothing was changed."
    return (f"{verb} that would leave {len(ids)} piece{'' if one else 's'} with "
            f"nothing holding {'it' if one else 'them'} up ({listed}). {tail}")


def _name(model: Model, pid_or_id: str) -> str:
    for p in model.parts:
        if p.id == pid_or_id:
            return partlib.info(p.pid, model.lib).name
    return "piece"


# ------------------------------------------------------------ op validation
OPS = {"move", "rotate", "recolour", "delete", "duplicate", "add"}
DIRS = {"right": (1, 0, 0), "left": (-1, 0, 0), "up": (0, 1, 0),
        "down": (0, -1, 0), "forward": (0, 0, -1), "back": (0, 0, 1)}


def _int(v, lo, hi, field):
    if isinstance(v, bool) or not isinstance(v, int):
        raise OpError(f"'{field}' has to be a whole number.")
    if not (lo <= v <= hi):
        raise OpError(f"'{field}' has to be between {lo} and {hi}.")
    return v


def _bool(v, field, default=None):
    if v is None:
        return default
    if not isinstance(v, bool):
        raise OpError(f"'{field}' has to be true or false.")
    return v


def expand_selector(op: dict, model: Model) -> dict:
    """A request op may carry one selector instead of `ids`."""
    out = dict(op)
    if op.get("op") == "add":
        return out            # `add` takes no ids; its colour/part are its own
    out.pop("all", None)
    out.pop("body", None)
    if "ids" in op:
        return out
    if op.get("all") is True:
        out["ids"] = [p.id for p in model.parts]
    elif "body" in op:
        out["ids"] = [p.id for p in model.parts if p.body == op["body"]]
    elif "colour" in op and op.get("op") != "recolour":
        out["ids"] = [p.id for p in model.parts if p.colour == op["colour"]]
        out.pop("colour")
    elif "part" in op and op.get("op") != "add":
        out["ids"] = [p.id for p in model.parts if p.pid == str(op["part"])]
        out.pop("part")
    return out


def normalise(ops, model: Model) -> list:
    if not isinstance(ops, list) or not ops:
        raise OpError("I need at least one change to make.")
    if len(ops) > MAX_OPS:
        raise OpError(f"That's more than {MAX_OPS} changes at once.")
    known = {p.id for p in model.parts}
    out = []
    for raw in ops:
        if not isinstance(raw, dict):
            raise OpError("Each change has to be an object.")
        o = expand_selector(raw, model)
        kind = o.get("op")
        if kind not in OPS:
            raise OpError(f"I don't know how to '{kind}'.")
        clean = {"op": kind}
        if kind != "add":
            ids = o.get("ids")
            if not isinstance(ids, list) or not ids:
                raise OpError("Tap the pieces you mean first, then say that again.", "NEEDS_SELECTION")
            if len(ids) > MAX_IDS:
                raise OpError(f"That's more than {MAX_IDS} pieces at once.")
            seen = []
            for i in ids:
                if not isinstance(i, str):
                    raise OpError("Piece ids have to be text.")
                if i not in known:
                    raise OpError(HUMAN["UNKNOWN_ID"], "UNKNOWN_ID")
                if i not in seen:
                    seen.append(i)
            clean["ids"] = seen
        if kind in ("move", "duplicate"):
            d = o.get("d")
            if kind == "duplicate" and d is None:
                clean["d"] = None
            else:
                if not isinstance(d, list) or len(d) != 3:
                    raise OpError("A move needs three whole numbers.")
                d = [_int(v, -60, 60, "d") for v in d]
                # a request must go somewhere; a *resolved* op (settle already
                # baked in) may be a no-op, because that is where it landed
                if kind == "move" and not any(d) and o.get("settle") is not False:
                    raise OpError("That move doesn't go anywhere.")
                clean["d"] = d
            clean["settle"] = _bool(o.get("settle"), "settle", True)
        elif kind == "rotate":
            clean["quarters"] = _int(o.get("quarters", 1), 1, 3, "quarters")
            clean["settle"] = _bool(o.get("settle"), "settle", True)
        elif kind == "recolour":
            c = o.get("colour")
            if isinstance(c, bool) or not isinstance(c, int):
                raise OpError("'colour' has to be a whole number.")
            if c in (16, 24) or c not in partlib.colours():
                raise OpError("I don't know that colour.")
            clean["colour"] = c
        elif kind == "delete":
            clean["cascade"] = _bool(o.get("cascade"), "cascade", False)
        elif kind == "add":
            part = str(o.get("part", ""))
            if part not in kit.G or not partlib.info(part, model.lib).antistuds:
                raise OpError("I can't add that part.")
            c = o.get("colour", 4)
            if isinstance(c, bool) or not isinstance(c, int) or c not in partlib.colours():
                raise OpError("I don't know that colour.")
            on = o.get("on")
            if on is not None and (not isinstance(on, str) or on not in known):
                raise OpError(HUMAN["UNKNOWN_ID"], "UNKNOWN_ID")
            clean.update(part=part, colour=c, on=on,
                         quarters=_int(o.get("quarters", 0), 0, 3, "quarters"),
                         settle=_bool(o.get("settle"), "settle", True))
        out.append(clean)
    return out


# -------------------------------------------------------------- op geometry
def upright(M) -> bool:
    R = M[:3, :3]
    if abs(R[1, 1] - 1.0) > 1e-6:
        return False
    if np.abs(np.abs(R) - np.round(np.abs(R))).max() > 1e-6:
        return False
    if np.abs(np.round(R) - R).max() > 1e-6:
        return False
    return abs(np.linalg.det(R) - 1.0) < 1e-6


def world_box(p: EPart, lib):
    """Axis-aligned world bounds of the part's body box."""
    x0, x1, y0, y1, z0, z1 = partlib.info(p.pid, lib).box
    corners = np.array([[x, y, z, 1.0] for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)])
    w = (p.M @ corners.T).T[:, :3]
    return w.min(axis=0), w.max(axis=0)


def _move_delta(p: EPart, d, lib):
    """World translation for one part, in its own lattice when it is tilted."""
    want = np.array([d[0] * STUD, -d[1] * PLATE, d[2] * STUD], float)
    if upright(p.M):
        return want, True
    R = p.M[:3, :3]
    total = np.zeros(3)
    aligned = True
    for axis, n, span in ((0, d[0], STUD), (1, -d[1], PLATE), (2, d[2], STUD)):
        if not n:
            continue
        target = np.zeros(3)
        target[axis] = 1.0 if n > 0 else -1.0
        best, bestdot = None, -2.0
        for k in range(3):
            for s in (1.0, -1.0):
                loc = np.zeros(3)
                loc[k] = s
                wdir = R @ loc
                nrm = float(np.linalg.norm(wdir))
                if nrm < 1e-9:
                    continue
                dot = float(target @ (wdir / nrm))
                if dot > bestdot:
                    best, bestdot = (k, s, wdir / nrm), dot
        if best is None:
            return want, False
        k, s, wdir = best
        if bestdot < math.cos(math.radians(1.0)):
            aligned = False
        step = PLATE if k == 1 else STUD
        total = total + abs(n) * step * wdir
    return total, aligned


def _resnap(before_min, after_min):
    """Put a turned part back on the stud lattice."""
    out = np.zeros(3)
    for k, axis in ((0, 0), (1, 2)):
        v = (before_min[axis] - after_min[axis]) % STUD
        if v > 10.0 + 1e-9:
            v -= STUD
        out[axis] = v
    return out


def _translate(p: EPart, v) -> EPart:
    M = p.M.copy()
    M[:3, 3] = M[:3, 3] + v
    return replace(p, M=M, text=None)


# ------------------------------------------------------------------ settle
COLUMNS = sorted([(ox, oz) for ox in range(-2, 3) for oz in range(-2, 3)],
                 key=lambda t: (abs(t[0]) + abs(t[1]), abs(t[0]), t[0], t[1]))
MAX_LOCAL = 400
MAX_GATES = 3


class _Static:
    """The parts that aren't moving, indexed once per settle."""

    def __init__(self, parts, lib, moving: set):
        self.lib = lib
        self.idx = [i for i in range(len(parts)) if i not in moving]
        self.parts = [parts[i] for i in self.idx]
        sample = _samples_for(lib)
        self.cells: dict = {}
        self.ground = -1e18
        for n, p in enumerate(self.parts):
            w = (p.M @ sample(p.pid).T).T[:, :3]
            self.ground = max(self.ground, float(w[:, 1].max()))
            for key in map(tuple, np.floor(w / 4.0).astype(int)):
                self.cells.setdefault(key, set()).add(n)
        self.anti: dict = {}
        self.studs: dict = {}
        for n, p in enumerate(self.parts):
            s, a = _world_studs(p, lib)
            for pos, ax in a:
                self.anti.setdefault(_cell(pos), []).append((n, pos, ax))
            for pos, ax in s:
                self.studs.setdefault(_cell(pos), []).append((n, pos, ax))
        self.pids = [p.pid for p in self.parts]
        self.odd = {n for n, p in enumerate(self.parts)
                    if partlib.info(p.pid, lib).source != "kit"}

    def free(self, group, offset) -> bool:
        sample = _samples_for(self.lib)
        for p in group:
            w = (p.M @ sample(p.pid).T).T[:, :3] + offset
            hits: dict = {}
            for key in map(tuple, np.floor(w / 4.0).astype(int)):
                for n in self.cells.get(key, ()):
                    if frozenset((self.pids[n], p.pid)) in check.EXEMPT:
                        continue
                    hits[n] = hits.get(n, 0) + 1
                    if hits[n] >= 3:
                        return False
        return True

    def held(self, group, offset) -> bool:
        sample = _samples_for(self.lib)
        for p in group:
            w = (p.M @ sample(p.pid).T).T[:, :3] + offset
            if float(w[:, 1].max()) > self.ground - PLATE:
                return True
        for p in group:
            studs, anti = _world_studs(p, self.lib)
            for pos, ax in studs:
                if self._touch(self.anti, pos + offset, ax):
                    return True
            for pos, ax in anti:
                if self._touch(self.studs, pos + offset, ax):
                    return True
            if partlib.info(p.pid, self.lib).source != "kit" or self.odd:
                if self._contact(p, offset):
                    return True
        return False

    def _touch(self, index, pos, ax) -> bool:
        cx, cy, cz = _cell(pos)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for _, apos, aax in index.get((cx + dx, cy + dy, cz + dz), ()):
                        if np.linalg.norm(pos - apos) <= 2.0 and float(ax @ aax) >= 0.99:
                            return True
        return False

    def _contact(self, p, offset) -> bool:
        mine = partlib.info(p.pid, self.lib).source != "kit"
        w = (p.M @ _grown(p.pid, self.lib).T).T[:, :3] + offset
        hits: dict = {}
        for key in map(tuple, np.floor(w / 4.0).astype(int)):
            for n in self.cells.get(key, ()):
                if not mine and n not in self.odd:
                    continue
                hits[n] = hits.get(n, 0) + 1
                if hits[n] >= 3:
                    return True
        return False

    def lowest(self, group, offset) -> float:
        sample = _samples_for(self.lib)
        return max(float((p.M @ sample(p.pid).T).T[:, 1].max()) + offset[1] for p in group)


# ------------------------------------------------------------------- apply
def apply(model: Model, ops, seed: int = 0) -> Result:
    ops = normalise(ops, model)
    parts = list(model.parts)
    next_id = model.next_id
    touched: set = set()
    moved: set = set()
    added: list = []
    removed: list = []
    changed: list = []
    landed: list = []
    resolved: list = []
    new_ids: list = []
    events: list = []
    bits: list = []
    settle_notes: list = []

    def pos_of(pid_str):
        for i, p in enumerate(parts):
            if p.id == pid_str:
                return i
        raise OpError(HUMAN["UNKNOWN_ID"], "UNKNOWN_ID")

    def reject(code, human, culprits=(), off=None, land=()):
        return Result(False, code, human, None, None, (), (), (), (), tuple(land),
                      tuple(culprits), off, stand_of(model), tuple(events))

    for op in ops:
        kind = op["op"]
        if kind == "recolour":
            colour = op["colour"]
            for i in (pos_of(x) for x in op["ids"]):
                p = parts[i]
                parts[i] = replace(p, colour=colour, text=_recoloured_text(p.text, colour))
                changed.append(p.id)
            # a recolour moves nothing, so it is not "touched" for the gate:
            # repainting a piece that was already floating is not a new fault
            resolved.append({"op": "recolour", "ids": list(op["ids"]), "colour": colour})
            n = len(op["ids"])
            events.append(("designer", "edit.apply",
                           f"Recoloured {n} piece{'s' if n != 1 else ''} {partlib.colour_name(colour)}", "ok"))
            bits.append(f"{n} piece{'s' if n != 1 else ''} recoloured {partlib.colour_name(colour)}")
            continue

        if kind == "delete":
            idxs = sorted({pos_of(x) for x in op["ids"]}, reverse=True)
            if len(idxs) >= len(parts):
                return reject("EMPTY", HUMAN["EMPTY"])
            gone = [parts[i].id for i in sorted(idxs)]
            names = _count_names(model, gone)
            for i in idxs:
                parts.pop(i)
            after = _build(model, parts, next_id)
            if op["cascade"]:
                extra = sorted(scene(after)["loose"] - scene(model)["loose"])
                if extra:
                    keep = set(extra)
                    parts = [p for p in parts if p.id not in keep]
                    gone += extra
                    after = _build(model, parts, next_id)
                if not parts:
                    return reject("EMPTY", HUMAN["EMPTY"])
            verdict = gate(model, after, set())
            if not verdict["ok"]:
                if verdict["code"] == "WOULD_FALL" and not op["cascade"]:
                    events.append(("designer", "edit.apply", f"Tried removing {names}", "ok"))
                    n_fall = len(verdict["culprits"])
                    events.append(("inspector", "edit.gate",
                                   f"{n_fall} piece{'' if n_fall == 1 else 's'} would be left with "
                                   f"nothing holding {'it' if n_fall == 1 else 'them'} up, so "
                                   f"nothing was changed", "fail"))
                    return Result(False, "WOULD_FALL", _would_fall(model, verdict["culprits"], "Removing"),
                                  None, None, (), (), (), (), (), tuple(verdict["culprits"]),
                                  {"cascade": True}, stand_of(model), tuple(events))
                events.append(("designer", "edit.apply", f"Tried removing {names}", "ok"))
                events.append(("inspector", "edit.gate", _fail_text(verdict), "fail"))
                return reject(verdict["code"], gate_human(model, verdict, "Removing"),
                              verdict["culprits"])
            removed += gone
            resolved.append({"op": "delete", "ids": gone, "cascade": False})
            extra_n = len(gone) - len(op["ids"])
            n = len(op["ids"])
            events.append(("designer", "edit.apply",
                           f"Removed {names}" + (f" and {extra_n} it was holding up" if extra_n else ""), "ok"))
            bits.append(f"Removed {n} piece{'s' if n != 1 else ''}"
                        + (f" (and {extra_n} it was holding up)" if extra_n else ""))
            continue

        # ---- placement ops: move / rotate / duplicate / add
        if kind == "add":
            new = _new_part(model, parts, op, next_id)
            next_id += 1
            new_ids.append(new.id)
            parts.append(new)
            group_idx = [len(parts) - 1]
            want = [0, 0, 0]
        elif kind == "duplicate":
            src = [pos_of(x) for x in op["ids"]]
            d = op["d"]
            if d is None:
                lo = np.min([world_box(parts[i], model.lib)[0] for i in src], axis=0)
                hi = np.max([world_box(parts[i], model.lib)[1] for i in src], axis=0)
                d = [0, max(1, int(round((hi[1] - lo[1]) / PLATE))), 0]
            copies = []
            for i in src:
                p = parts[i]
                nid = f"n{next_id}"
                next_id += 1
                new_ids.append(nid)
                copies.append(replace(p, id=nid, text=None, M=p.M.copy()))
            group_idx = list(range(len(parts), len(parts) + len(copies)))
            parts += copies
            want = d
        else:
            group_idx = [pos_of(x) for x in op["ids"]]
            want = op.get("d") or [0, 0, 0]

        group_ids = [parts[i].id for i in group_idx]
        moving = set(group_idx)

        if kind == "rotate":
            err = _rotate_group(parts, group_idx, op["quarters"], model.lib)
            if err:
                return reject(err, HUMAN[err])
        elif kind in ("move", "duplicate") and any(want):
            deltas = []
            aligned_all = True
            has_upright = any(upright(parts[i].M) for i in group_idx)
            has_tilted = any(not upright(parts[i].M) for i in group_idx)
            for i in group_idx:
                v, ok = _move_delta(parts[i], want, model.lib)
                aligned_all = aligned_all and ok
                deltas.append(v)
            if has_upright and has_tilted and not aligned_all:
                return reject("MIXED_TILT", HUMAN["MIXED_TILT"])
            for i, v in zip(group_idx, deltas):
                parts[i] = _translate(parts[i], v)
        elif kind in ("move", "duplicate"):
            for i in group_idx:
                parts[i] = replace(parts[i], text=None)

        all_upright = all(upright(parts[i].M) for i in group_idx)
        do_settle = op.get("settle", True) and all_upright
        offset = np.zeros(3)
        settled = False
        first_bad = None
        if do_settle:
            static = _Static(parts, model.lib, moving)
            group = [parts[i] for i in group_idx]
            if static.free(group, offset) and static.held(group, offset):
                after = _build(model, parts, next_id)
                verdict = gate(model, after, set(group_ids) | touched)
                if verdict["ok"]:
                    do_settle = False
                else:
                    first_bad = verdict
            if do_settle:
                found, settled, first_bad = _search(model, parts, group_idx, static,
                                                    set(group_ids) | touched, next_id, first_bad)
                if found is None:
                    # Say WHY, with the real pieces named: the whole verdict is
                    # carried out of the search, not just its code, so COLLIDES
                    # and WOULD_FALL don't end up with an empty list in the copy.
                    bad = first_bad or {"code": "NO_SPOT", "culprits": []}
                    code = bad["code"]
                    land = [_land(parts[i], i, want, want, False) for i in group_idx]
                    events.append(("inspector", "edit.gate", _fail_text(bad), "fail"))
                    return reject(code, gate_human(model, bad, "Moving"),
                                  bad.get("culprits") or (), None, land)
                offset = found
                if np.abs(offset).max() > 1e-9:
                    for i in group_idx:
                        parts[i] = _translate(parts[i], offset)

        total = _total_d(want, offset)
        if settled:
            settle_notes.append(_settle_note(want, total))
        for i in group_idx:
            p = parts[i]
            landed.append(_land(p, -1, want, total, settled))
            if kind in ("move", "rotate"):
                changed.append(p.id)
            touched.add(p.id)
            moved.add(p.id)
        if kind in ("duplicate", "add"):
            added += group_ids

        if kind == "move":
            resolved.append({"op": "move", "ids": list(op["ids"]), "d": total, "settle": False})
            what = _what_move(len(op["ids"]), want)
            events.append(("designer", "edit.apply", what, "ok"))
            bits.append(what)
        elif kind == "rotate":
            resolved.append({"op": "rotate", "ids": list(op["ids"]), "quarters": op["quarters"],
                             "settle": False, "d": total})
            n = len(op["ids"])
            turn = {1: "a quarter turn", 2: "around", 3: "a quarter turn the other way"}[op["quarters"]]
            events.append(("designer", "edit.apply", f"Turned {n} piece{'s' if n != 1 else ''} {turn}", "ok"))
            bits.append(f"Turned {n} piece{'s' if n != 1 else ''} {turn}")
        elif kind == "duplicate":
            resolved.append({"op": "duplicate", "ids": list(op["ids"]), "d": total, "settle": False})
            n = len(op["ids"])
            events.append(("designer", "edit.apply", f"Copied {n} piece{'s' if n != 1 else ''}", "ok"))
            bits.append(f"Copied {n} piece{'s' if n != 1 else ''}")
        else:
            resolved.append({"op": "add", "part": op["part"], "colour": op["colour"], "on": op["on"],
                             "quarters": op["quarters"], "d": total, "settle": False})
            what = (f"Added a {partlib.colour_name(op['colour'])} "
                    f"{partlib.info(op['part'], model.lib).name}")
            events.append(("designer", "edit.apply", what, "ok"))
            bits.append(what)

    if not parts:
        return reject("EMPTY", HUMAN["EMPTY"])

    parts = _reorder(model, parts, moved - set(added), set(added))
    after = _build(model, parts, next_id)
    verdict = gate(model, after, touched)
    if not verdict["ok"]:
        events.append(("inspector", "edit.gate", _fail_text(verdict), "fail"))
        verb = "Removing" if ops and ops[-1]["op"] == "delete" else "Moving"
        return reject(verdict["code"], gate_human(model, verdict, verb), verdict["culprits"])

    for note in settle_notes:
        events.append(("repair", "edit.settle", note, "ok"))
    st = stand_of(after)
    events.append(("inspector", "edit.gate",
                   "Nothing overlaps, everything is still attached, and it "
                   + ("still stands" if st["stable"] else "leans no worse than before"), "ok"))
    ldr = write(after)
    n_steps = sum(1 for p_i, p in enumerate(after.parts) if p_i == 0 or p.step != after.parts[p_i - 1].step)
    events.append(("scribe", "edit.steps", f"Manual updated: {n_steps} steps", "ok"))

    index = {p.id: i for i, p in enumerate(after.parts)}
    landed = [dict(l, line=index.get(l["id"], -1)) for l in landed]
    human = _human(model, after, bits, settle_notes)
    return Result(True, None, human, after, ldr, tuple(resolved), tuple(dict.fromkeys(changed)),
                  tuple(added), tuple(removed), tuple(landed), (), None, st, tuple(events),)


def _build(model: Model, parts, next_id) -> Model:
    return Model(model.header, tuple(parts), model.lib, next_id)


def _total_d(want, offset):
    return [int(want[0] + round(offset[0] / STUD)),
            int(want[1] + round(-offset[1] / PLATE)),
            int(want[2] + round(offset[2] / STUD))]


def _land(p: EPart, line, requested, d, settled) -> dict:
    m = p.M
    return {"id": p.id, "line": line, "requested": list(requested), "d": list(d),
            "settled": bool(settled),
            "origin": [round(float(m[0, 3]), 3), round(float(m[1, 3]), 3), round(float(m[2, 3]), 3)],
            "matrix": [round(float(m[r, c]), 6) for r in range(3) for c in range(3)]}


def _search(model, parts, group_idx, static, touched, next_id, first_bad):
    """C.3: 25 columns, a plate at a time, at most 3 full gates."""
    local = [0]
    gates = 0
    base = [parts[i] for i in group_idx]
    saved = [p.M.copy() for p in base]
    for ox, oz in COLUMNS:
        if gates >= MAX_GATES or local[0] >= MAX_LOCAL:
            break
        offset = np.array([ox * STUD, 0.0, oz * STUD])
        raised = 0
        while raised <= 36 and local[0] < MAX_LOCAL:
            local[0] += 1
            if static.free(base, offset):
                break
            offset = offset + np.array([0.0, -PLATE, 0.0])
            raised += 1
        else:
            continue
        if raised > 36:
            continue
        dropped = 0
        while dropped < 60 and local[0] < MAX_LOCAL:
            down = offset + np.array([0.0, PLATE, 0.0])
            if static.lowest(base, down) > static.ground + 1e-6:
                break
            local[0] += 1
            if not static.free(base, down):
                break
            offset = down
            dropped += 1
        if not static.held(base, offset):
            continue
        if gates >= MAX_GATES:
            break
        for i, p, M in zip(group_idx, base, saved):
            NM = M.copy()
            NM[:3, 3] = NM[:3, 3] + offset
            parts[i] = replace(p, M=NM, text=None)
        after = _build(model, parts, next_id)
        gates += 1
        verdict = gate(model, after, touched)
        for i, p, M in zip(group_idx, base, saved):
            parts[i] = replace(p, M=M.copy(), text=None)
        if verdict["ok"]:
            return offset, bool(np.abs(offset).max() > 1e-9), first_bad
        first_bad = first_bad or verdict
    return None, False, first_bad


def _rotate_group(parts, group_idx, quarters, lib):
    """A quarter turn about the vertical, then back onto the stud lattice."""
    tilted = [i for i in group_idx if not upright(parts[i].M)]
    if len(group_idx) == 1:
        i = group_idx[0]
        p = parts[i]
        if tilted:
            axis = p.M[:3, :3] @ np.array([0.0, 1.0, 0.0])
            R = kit.rot_axis(axis, 90.0 * quarters)[:3, :3]
        else:
            R = kit.rot_y(quarters)
        b0 = world_box(p, lib)[0]
        M = p.M.copy()
        M[:3, :3] = R @ p.M[:3, :3]
        q = replace(p, M=M, text=None)
        if not tilted:
            b1 = world_box(q, lib)[0]
            M2 = M.copy()
            M2[:3, 3] = M[:3, 3] + _resnap(b0, b1)
            q = replace(p, M=M2, text=None)
        parts[i] = q
        return None
    lo = np.min([world_box(parts[i], lib)[0] for i in group_idx], axis=0)
    hi = np.max([world_box(parts[i], lib)[1] for i in group_idx], axis=0)
    c = np.array([round((lo[0] + hi[0]) / 2 / 10.0) * 10.0, 0.0, round((lo[2] + hi[2]) / 2 / 10.0) * 10.0])
    R = kit.rot_y(quarters)
    first = group_idx[0]
    b0 = world_box(parts[first], lib)[0]
    for i in group_idx:
        p = parts[i]
        M = p.M.copy()
        M[:3, :3] = R @ p.M[:3, :3]
        M[:3, 3] = c + R @ (p.M[:3, 3] - c)
        parts[i] = replace(p, M=M, text=None)
    if not tilted:
        b1 = world_box(parts[first], lib)[0]
        shift = _resnap(b0, b1)
        for i in group_idx:
            parts[i] = _translate(parts[i], shift)
    return None


def _new_part(model: Model, parts, op, next_id) -> EPart:
    lib = model.lib
    g = partlib.info(op["part"], lib)
    R = kit.rot_y(op["quarters"])
    M = np.eye(4)
    M[:3, :3] = R
    probe = EPart(f"n{next_id}", op["part"], f"{op['part']}.dat", op["colour"], "", M, 0, None)
    lo, hi = world_box(probe, lib)
    if op["on"]:
        on = next(p for p in parts if p.id == op["on"])
        olo, ohi = world_box(on, lib)
        target = np.array([olo[0], olo[1] - (hi[1] - lo[1]), olo[2]])
        body = on.body
        step = on.step
    else:
        alo = np.min([world_box(p, lib)[0] for p in parts], axis=0)
        ahi = np.max([world_box(p, lib)[1] for p in parts], axis=0)
        anchor = next((p for p in parts if upright(p.M)), parts[0])
        plo = world_box(anchor, lib)[0]
        cx = plo[0] + round(((alo[0] + ahi[0]) / 2 - (hi[0] - lo[0]) / 2 - plo[0]) / STUD) * STUD
        cz = plo[2] + round(((alo[2] + ahi[2]) / 2 - (hi[2] - lo[2]) / 2 - plo[2]) / STUD) * STUD
        target = np.array([cx, alo[1] - PLATE - (hi[1] - lo[1]), cz])
        body = parts[0].body
        step = parts[-1].step + 1
    M[:3, 3] = target - lo
    return EPart(f"n{next_id}", op["part"], f"{op['part']}.dat", op["colour"], body, M, step, None)


def _reorder(model: Model, parts, moved: set, added: set):
    """A.4 line order: a moved line only slides down the file when it now
    rests on a line that comes later; a new line goes straight after the last
    piece holding it up (or becomes a new final step)."""
    parts = list(parts)
    if not moved and not added:
        return parts
    tmp = _build(model, parts, 0)
    sc = scene(tmp)
    boxes = [world_box(p, model.lib) for p in parts]
    yc = [(b[0][1] + b[1][1]) / 2 for b in boxes]       # LDraw +y is down
    sup: dict = {}
    for a, b in sc["edges"]:
        if yc[b] > yc[a] + 1e-6:
            sup.setdefault(parts[a].id, set()).add(parts[b].id)
        elif yc[a] > yc[b] + 1e-6:
            sup.setdefault(parts[b].id, set()).add(parts[a].id)

    def slide(ident, always):
        idx = {p.id: i for i, p in enumerate(parts)}
        i = idx.get(ident)
        if i is None:
            return
        pos = [idx[s] for s in sup.get(ident, ()) if s in idx and idx[s] != i]
        if always:
            if not pos:                       # resting on the ground: a new final step
                p = parts.pop(i)
                parts.append(replace(p, step=(max(q.step for q in parts) + 1) if parts else 0))
                return
            last = max(pos)
        else:
            later = [j for j in pos if j > i]
            if not later:
                return
            last = max(later)
        p = parts.pop(i)
        tgt = last - 1 if last > i else last
        parts.insert(tgt + 1, replace(p, step=parts[tgt].step))

    for ident in [p.id for p in parts if p.id in added]:
        slide(ident, True)
    for ident in [p.id for p in parts if p.id in moved]:
        slide(ident, False)
    # steps must stay non-decreasing along the file
    cur = 0
    out = []
    for p in parts:
        cur = max(cur, p.step)
        out.append(p if p.step == cur else replace(p, step=cur, text=p.text))
    return out


# ----------------------------------------------------------------- wording
UNIT = {0: "stud", 1: "plate", 2: "stud"}


def _dir_word(d):
    if d[0]:
        return ("right" if d[0] > 0 else "left"), abs(d[0]), "stud"
    if d[1]:
        return ("up" if d[1] > 0 else "down"), abs(d[1]), "plate"
    if d[2]:
        return ("back" if d[2] > 0 else "forward"), abs(d[2]), "stud"
    return "", 0, "stud"


def _what_move(count, d):
    word, n, unit = _dir_word(d)
    pieces = f"{count} piece{'s' if count != 1 else ''}"
    if not word:
        return f"Moved {pieces}"
    return f"Moved {pieces} {n} {unit}{'s' if n != 1 else ''} {word}"


def _settle_note(want, total):
    dy = total[1] - want[1]
    dx, dz = total[0] - want[0], total[2] - want[2]
    if dy and not (dx or dz):
        n = abs(dy)
        return (f"It had nothing under it there, so it came to rest {n} "
                f"plate{'s' if n != 1 else ''} {'higher' if dy > 0 else 'lower'}")
    return "That exact spot was taken, so it clicked into the nearest one that holds"


def _count_names(model, ids):
    counts: dict = {}
    for i in ids:
        counts[_name(model, i)] = counts.get(_name(model, i), 0) + 1
    return ", ".join(f"{n} {name}" for name, n in sorted(counts.items(), key=lambda kv: -kv[1])[:3])


def _fail_text(verdict) -> str:
    return {"COLLIDES": "Those pieces would overlap, so nothing was changed",
            "FLOATING": "It would have nothing to hold on to, so nothing was changed",
            "WOULD_FALL": "Some pieces would be left with nothing holding them up, so nothing was changed",
            "TIPS": "It would tip over, so nothing was changed",
            "TIPS_WORSE": "It would lean further than it already does, so nothing was changed",
            "NO_SPOT": "I couldn't find a free spot nearby that holds"}.get(
        verdict.get("code"), "That change didn't hold, so nothing was changed")


_RECOLOUR_BIT = re.compile(r"^(\d+) pieces? recoloured (.+)$")


def _merge(bits):
    """'256 pieces recoloured Red, 55 pieces recoloured Red' is one sentence."""
    out: list = []
    for bit in bits:
        m = _RECOLOUR_BIT.match(bit)
        if m:
            for i, seen in enumerate(out):
                s2 = _RECOLOUR_BIT.match(seen)
                if s2 and s2.group(2) == m.group(2):
                    n = int(s2.group(1)) + int(m.group(1))
                    out[i] = f"{n} piece{'s' if n != 1 else ''} recoloured {m.group(2)}"
                    break
            else:
                out.append(bit)
            continue
        out.append(bit)
    return out


def _human(before: Model, after: Model, bits, notes) -> str:
    bits = _merge(bits)
    a, b = stand_of(before), stand_of(after)
    if b["stable"]:
        tail = "still stands" if a["stable"] else "it stands now"
    else:
        tail = "still leans, as it did before"
    out = ", ".join(bits) or "Nothing to do"
    return " · ".join([out] + notes + [tail])


# ------------------------------------------------------------------- table
def stability(model: Model) -> dict:
    s = stand_of(model)
    out = {"stable": s["stable"], "margin": s["margin"], "direction": s["direction"],
           "com": s.get("com"), "base": s.get("base", []), "ground": s.get("ground", 0),
           "backend": "brickify", "studs": 0, "broken": [], "failures": []}
    if not s["stable"]:
        out["failures"] = [{"code": "UNSTABLE",
                            "human": f"it would tip over toward the {SIDE.get(s['direction'], 'side')}"}]
    return out


def table(model: Model) -> dict:
    lib = model.lib
    sc = scene(model)
    loose = sc["loose"]
    boxes = [world_box(p, lib) for p in model.parts]
    lo = np.min([b[0] for b in boxes], axis=0)
    hi = np.max([b[1] for b in boxes], axis=0)
    rows = []
    for i, p in enumerate(model.parts):
        g = partlib.info(p.pid, lib)
        blo, bhi = boxes[i]
        where = []
        if bhi[1] > hi[1] - PLATE:
            where.append("bottom")
        if blo[1] < lo[1] + PLATE:
            where.append("top")
        cx, cz = (blo[0] + bhi[0]) / 2, (blo[2] + bhi[2]) / 2
        if hi[0] - lo[0] > 1e-6:
            f = (cx - lo[0]) / (hi[0] - lo[0])
            if f < 1 / 3:
                where.append("left")
            elif f > 2 / 3:
                where.append("right")
        if hi[2] - lo[2] > 1e-6:
            f = (cz - lo[2]) / (hi[2] - lo[2])
            if f < 1 / 3:
                where.append("front")
            elif f > 2 / 3:
                where.append("back")
        trans = partlib.is_trans(p.colour)
        tags = []
        if trans and g.size[0] <= 2 and g.size[2] <= 2 and g.kind in ("plate", "tile", "round", "brick", "slope"):
            tags.append("light")
        if p.pid in ("98138", "6141", "85861", "4073") and p.colour in (0, 15):
            tags.append("eye")
        if g.kind == "window" or (trans and "light" not in tags):
            tags.append("window")
        if g.kind in ("wheel", "tyre"):
            tags.append("wheel")
        m = p.M
        rows.append({
            "id": p.id, "line": i, "part": p.pid, "name": g.name, "kind": g.kind,
            "geometry": g.source, "colour": int(p.colour), "colour_name": partlib.colour_name(p.colour),
            "trans": trans, "body": p.body,
            "pos": [int(round(m[0, 3] / STUD)), int(round(-m[1, 3] / PLATE)), int(round(m[2, 3] / STUD))],
            "rot": (int(round(math.degrees(math.atan2(-m[2, 0], m[0, 0])) / 90)) % 4) * 90,
            "upright": bool(upright(m)), "size": list(g.size),
            "origin": [round(float(m[0, 3]), 3), round(float(m[1, 3]), 3), round(float(m[2, 3]), 3)],
            "step": p.step, "where": where, "tags": tags, "loose": p.id in loose,
        })
    bodies: dict = {}
    for r in rows:
        b = bodies.setdefault(r["body"], {"name": r["body"], "count": 0, "colours": []})
        b["count"] += 1
        if r["colour"] not in b["colours"]:
            b["colours"].append(r["colour"])
    cols: dict = {}
    for r in rows:
        c = cols.setdefault(r["colour"], {"code": r["colour"], "name": r["colour_name"],
                                          "count": 0, "trans": r["trans"]})
        c["count"] += 1
    ordered = sorted(cols.values(), key=lambda c: -c["count"])
    palette = []
    for code in [c["code"] for c in ordered] + [4, 14, 1, 2, 25, 15, 0, 71, 72, 70, 19, 27, 5, 33, 36, 46, 47, 34]:
        if any(p["code"] == code for p in palette):
            continue
        meta = partlib.colours().get(code)
        if meta:
            palette.append({"code": code, "name": meta["name"], "hex": meta["hex"], "trans": meta["trans"]})
    kit_rows = []
    for pid in sorted(kit.G):
        g = partlib.info(pid, lib)
        if g.studs:
            kit_rows.append({"part": pid, "name": g.name, "kind": g.kind, "size": list(g.size)})
    return {"count": len(rows), "parts": rows, "bodies": list(bodies.values()),
            "colours": ordered, "kit": kit_rows, "palette": palette, "suggestions": []}
