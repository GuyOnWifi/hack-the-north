"""Idea -> LEGO model. Pipeline C: the design loop, stage by stage.

    uv run python -m brickify.pipeline "dog"
    uv run python -m brickify.pipeline "hummingbird" --concept my.png --rounds 1
    uv run python -m brickify.pipeline --edit runs/<run> "make the ears longer"

Stages (each logs to <run>/tape.jsonl, in the app's agent-tape format):

1. distill   Claude (fast model) rewrites the idea into something buildable:
             calm pose, chunky shapes, props simplified (DISTILL.md).
             "dog holding an umbrella" -> "sitting dog wearing an umbrella hat".
2. concept   Codex (ChatGPT login, no API key) draws it as an official LEGO
             set. Skipped if a concept image is given.
3. views     Codex redraws the SAME model from the side and back, using the
             concept as a reference image, so the designer sees depth.
4. briefs    Claude (design model) reads the images + BRIEF.md and writes
             `--fan` build briefs at the same time: shapes on small grids,
             colours, connectors. Never 3D coordinates. Three designs cost the
             wall clock of one, and the critic gets a choice.
5. build     The kernel assembles real parts, then checks collisions and that
             the model stands (centre of mass over its base). Rejected briefs
             go back to Claude (fast model) with the reasons, up to 2 fixes.
6. render    Four fixed angles through the web app's /lab page (the app must
             be running at BRICKIFY_WEB, default http://localhost:3000).
7. pick      Claude looks at all the candidates next to the concept and keeps
             the one that reads best. `--rounds N` then lets the critic send
             notes back to the designer N times; the best round always wins.

`edit()` revises a finished run's brief from a plain-language request and
rebuilds it (no new images), which is how the app's "Change it" works.

Pipeline C merges B (this kernel-first loop) with the best of A (the
multi-agent layer builder, tag archive/pipeline-a): model calls from a clean
working directory without MCP servers, a fast model for small steps and a
strong one for design and judgement, a stability gate, and live streaming of
every event and every built round to the app.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .assembly import assemble, to_ldr
from .check import check_world, resolve, stands

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT.parent / "web"
RUNS = Path(os.environ.get("BRICKIFY_RUNS", ROOT / "runs"))
BRIEF_SPEC = (ROOT / "BRIEF.md").read_text()
DISTILL_SPEC = (ROOT / "DISTILL.md").read_text()
def _load_env(path: Path = Path(__file__).resolve().parent.parent / ".env.local"):
    """Local secrets (gitignored), so a key never has to live in the shell."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_env()
API_KEY = os.environ.get("ANTHROPIC_API_KEY")  # set: use the API; unset: the `claude` CLI
IMAGE_KEY = os.environ.get("OPENAI_API_KEY")  # set: images API; unset: the `codex` CLI
IMAGE_MODEL = os.environ.get("BRICKIFY_IMAGE_MODEL", "gpt-image-1")
# "high" is 31s against 8s for "low". Low art is blockier and closer to what
# this kit can build, but high looks like a real set photo, which is what the
# app shows you: worth the 23s.
IMAGE_QUALITY = os.environ.get("BRICKIFY_IMAGE_QUALITY", "high")
DESIGN_MODEL = os.environ.get("BRICKIFY_MODEL", "claude-opus-5")  # brief + critique
FAST_MODEL = os.environ.get("BRICKIFY_FAST", "claude-sonnet-5")  # distill + repair
BRIEF_TOKENS = 32000  # a full brief, or a critique carrying a revised one
WEB_URL = os.environ.get("BRICKIFY_WEB", "http://localhost:3000")

Listener = Callable[[dict], None]


# ------------------------------------------------------------------ plumbing

class Tape:
    """Append-only log of every step, in the app's agent-tape format. Listeners
    (the app's SSE stream) get each event as it happens."""

    def __init__(self, path: Path, listeners: tuple[Listener, ...] = (), echo: bool = True):
        self.path = path
        self.t0 = time.time()
        self.listeners = list(listeners)
        self.echo = echo

    def emit(self, actor: str, kind: str, text: str, status: str = "ok", **extra):
        ev = {"t": round((time.time() - self.t0) * 1000), "actor": actor, "kind": kind, "text": text, "status": status, **extra}
        with self.path.open("a") as f:
            f.write(json.dumps({k: v for k, v in ev.items() if k != "ldr"}) + "\n")
        if self.echo and kind != "geometry":
            print(f"[{ev['t'] / 1000:6.1f}s] {actor:9} {status:7} {text}", flush=True)
        for fn in self.listeners:
            fn(ev)


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "model"


# How hard the model thinks before answering. This is THE speed dial: left
# alone, these models think ~15k tokens before a ~1.5k-token brief, which is
# 219s instead of 21s. Measured on one brief (Opus, same concept image):
#   off 21s (13 collisions) · low 37s (8) · medium 73s (0) · default 219s
# So: cheap, mechanical steps get none, judgement gets a little.
EFFORT = {
    "none": {"thinking": {"type": "disabled"}},
    "low": {"thinking": {"type": "adaptive"}, "output_config": {"effort": "low"}},
    "medium": {"thinking": {"type": "adaptive"}, "output_config": {"effort": "medium"}},
    "high": {"thinking": {"type": "adaptive"}, "output_config": {"effort": "high"}},
}
BRIEF_EFFORT = os.environ.get("BRICKIFY_EFFORT", "medium")  # writing/revising a brief
JUDGE_EFFORT = os.environ.get("BRICKIFY_JUDGE_EFFORT", "medium")  # scoring renders and revising


def claude(prompt: str, images: list[Path], system: str, model: str = DESIGN_MODEL, timeout: int = 900, max_tokens: int = 16000, effort: str = "none", on_text: Callable[[str], None] | None = None) -> str:
    """One Claude call that can look at `images`.

    With ANTHROPIC_API_KEY set this is a direct API call (images inline, no
    agent loop, much faster). Without one it shells out to `claude -p`, which
    uses your Claude Code login and reads the images from disk."""
    if API_KEY:
        return _api(prompt, images, system, model, timeout, max_tokens, effort, on_text)
    return _cli(prompt, images, system, model, timeout)


MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}
MAX_SIDE = 768  # images are judged for shape and colour; more pixels only costs latency


def _image_bytes(img: Path) -> tuple[bytes, str]:
    """The image, shrunk to MAX_SIDE, as (bytes, media type)."""
    media = MEDIA.get(img.suffix.lower(), "image/png")
    try:
        from PIL import Image

        with Image.open(img) as im:
            if max(im.size) > MAX_SIDE:
                im = im.convert("RGB")
                im.thumbnail((MAX_SIDE, MAX_SIDE))
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=88)
                return buf.getvalue(), "image/jpeg"
    except Exception:
        pass  # unreadable or Pillow missing: send it as it is
    return img.read_bytes(), media


def _api(prompt: str, images: list[Path], system: str, model: str, timeout: int, max_tokens: int, effort: str = "none", on_text: Callable[[str], None] | None = None) -> str:
    content: list[dict] = []
    for img in images:
        if img.suffix.lower() not in MEDIA or not img.exists():
            continue
        raw, media = _image_bytes(img)
        content.append({"type": "text", "text": f"Image: {img.name}"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": media, "data": base64.b64encode(raw).decode()}})
    content.append({"type": "text", "text": prompt})
    body = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        # the spec is the same on every call of a run: let the API cache it
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": content}],
        **({"stream": True} if on_text else {}),
        **EFFORT.get(effort, EFFORT["none"]),
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={"content-type": "application/json", "x-api-key": API_KEY, "anthropic-version": "2023-06-01"},
    )
    for attempt in range(4):  # overloaded/rate-limited is normal; back off and retry
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out = _read_stream(r, on_text) if on_text else json.loads(r.read())
            text = "".join(b.get("text", "") for b in out.get("content", []))
            if out.get("stop_reason") == "max_tokens":
                raise RuntimeError(f"the reply hit the {max_tokens}-token limit; raise max_tokens or ask for less")
            if not text.strip():
                raise RuntimeError(f"empty reply (stop_reason={out.get('stop_reason')})")
            return text
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:300]
            if e.code not in (429, 500, 502, 503, 529) or attempt == 3:
                raise RuntimeError(f"Anthropic API {e.code}: {detail}") from None
            time.sleep(5 * (attempt + 1))
        except urllib.error.URLError as e:
            if attempt == 3:
                raise RuntimeError(f"Anthropic API unreachable: {e.reason}") from None
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("Anthropic API: out of retries")


def _read_stream(r, on_text: Callable[[str], None]) -> dict:
    """Server-sent events -> the same reply shape, calling `on_text` as the
    answer arrives. That is what lets the app build a model while it is still
    being written."""
    text, stop, usage = [], None, {}
    for line in r:
        line = line.decode().strip()
        if not line.startswith("data:"):
            continue
        ev = json.loads(line[5:])
        kind = ev.get("type")
        if kind == "content_block_delta" and ev.get("delta", {}).get("type") == "text_delta":
            chunk = ev["delta"]["text"]
            text.append(chunk)
            on_text("".join(text))
        elif kind == "message_delta":
            stop = ev.get("delta", {}).get("stop_reason", stop)
            usage = ev.get("usage", usage)
    return {"content": [{"type": "text", "text": "".join(text)}], "stop_reason": stop, "usage": usage}


# Model calls run from an empty directory with no MCP servers: repo instruction
# files never leak into the prompt, and a slow or broken MCP server can't stall
# a run. Images are shared explicitly with --add-dir.
CLEAN_CWD = Path(tempfile.gettempdir()) / "brickify-claude"


def _cli(prompt: str, images: list[Path], system: str, model: str, timeout: int) -> str:
    CLEAN_CWD.mkdir(exist_ok=True)
    cmd = ["claude", "-p", "--model", model, "--append-system-prompt", system, "--allowedTools", "Read", "--strict-mcp-config", "--output-format", "json"]
    for d in sorted({img.resolve().parent for img in images}):
        cmd += ["--add-dir", str(d)]
    if images:
        prompt += "\n\nImages to read: " + ", ".join(str(i.resolve()) for i in images)
    # prompt on stdin: --add-dir takes several values and would swallow it
    for attempt in range(2):  # one retry: a dropped session or rate limit shouldn't sink a run
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=CLEAN_CWD)
        if r.returncode == 0:
            return json.loads(r.stdout).get("result", "")
        time.sleep(5)
    # with --output-format json the reason is usually on stdout, not stderr
    raise RuntimeError(f"claude failed: {(r.stderr or r.stdout)[-400:].strip()}")


def make_image(prompt: str, out: Path, reference: Path | None = None, timeout: int = 420) -> bool:
    """Draw one image to `out`. Uses the OpenAI images API when a key is set
    (and edits the reference, if given, so the views match the concept);
    otherwise drives the `codex` CLI with a ChatGPT login."""
    if IMAGE_KEY:
        return _openai_image(prompt, out, reference, timeout)
    ask = (
        f"Use your image generation tool to create exactly one image: {prompt} "
        f"Save it as {out.name} in the current directory. Do not write code; just generate and save the image."
    )
    since = time.time()
    proc = codex_image(ask, out.parent, reference)
    return _codex_result(proc, out, since, reject=(".png",) if reference else ("-side", "-back"))


def _openai_image(prompt: str, out: Path, reference: Path | None, timeout: int) -> bool:
    if reference:
        fields = {"model": IMAGE_MODEL, "prompt": prompt, "size": "1024x1024", "n": "1", "quality": IMAGE_QUALITY}
        body, ctype = _multipart(fields, [("image[]", reference, "image/png")])
        url = "https://api.openai.com/v1/images/edits"
    else:
        body = json.dumps({"model": IMAGE_MODEL, "prompt": prompt, "size": "1024x1024", "n": 1, "quality": IMAGE_QUALITY}).encode()
        ctype = "application/json"
        url = "https://api.openai.com/v1/images/generations"
    req = urllib.request.Request(url, data=body, headers={"content-type": ctype, "authorization": f"Bearer {IMAGE_KEY}"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            out.write_bytes(base64.b64decode(data["data"][0]["b64_json"]))
            return True
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:300]
            if e.code not in (429, 500, 502, 503, 529) or attempt == 2:
                raise RuntimeError(f"OpenAI images {e.code}: {detail}") from None
            time.sleep(5 * (attempt + 1))
        except urllib.error.URLError as e:
            if attempt == 2:
                raise RuntimeError(f"OpenAI images unreachable: {e.reason}") from None
            time.sleep(5 * (attempt + 1))
    return False


def _multipart(fields: dict[str, str], files: list[tuple[str, Path, str]]) -> tuple[bytes, str]:
    boundary = "----brickify" + os.urandom(8).hex()
    parts: list[bytes] = []
    for k, v in fields.items():
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    for name, path, media in files:
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{path.name}\"\r\nContent-Type: {media}\r\n\r\n".encode())
        parts.append(path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def codex_image(ask: str, cwd: Path, reference: Path | None = None) -> subprocess.Popen:
    """Start a Codex image generation working in `cwd` (returns the process)."""
    cmd = ["codex", "exec", "--skip-git-repo-check", "-s", "workspace-write", "-C", str(cwd)]
    if reference:
        cmd += ["-i", str(reference)]
    cmd += ["--", ask]  # -i takes several values; "--" keeps it from eating the prompt
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def first_json(text: str) -> dict:
    """The outermost JSON object in a reply (tolerates fences and chatter)."""
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in reply")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError("unterminated JSON object in reply")


def _json_at(text: str, i: int):
    """(value, end index) for the JSON value starting at text[i], or None if it
    hasn't finished arriving yet."""
    if i < 0 or i >= len(text):
        return None
    depth, in_str, esc = 0, False, False
    for j in range(i, len(text)):
        ch = text[j]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
                if depth == 0:  # a bare string value
                    try:
                        return json.loads(text[i : j + 1]), j + 1
                    except ValueError:
                        return None
            continue
        if ch == '"':
            in_str = True
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[i : j + 1]), j + 1
                except ValueError:
                    return None
    return None


def half_brief(text: str) -> dict | None:
    """A buildable brief from a reply that is still being written.

    The sub-assemblies arrive one after another, so everything finished so far
    can be built and shown while the rest is still being typed. Connectors and
    details that point at bodies which haven't arrived are left out."""
    palette = _json_at(text, text.find("{", text.find('"palette"') + 9)) if '"palette"' in text else None
    root = _json_at(text, text.find('"', text.find('"root"') + 6)) if '"root"' in text else None
    if not palette or not root or '"bodies"' not in text:
        return None
    bodies = []
    j = text.find("[", text.find('"bodies"') + 8) + 1
    while j > 0:
        start = text.find("{", j)
        got = _json_at(text, start) if start >= 0 else None
        if not got:
            break
        bodies.append(got[0])
        j = got[1]
    names = {b.get("name") for b in bodies}
    if root[0] not in names:
        return None
    for b in bodies:
        b["connectors"] = [c for c in b.get("connectors", []) if all(a.get("body") in names for a in c.get("attach", []))]
    return {"palette": palette[0], "root": root[0], "bodies": bodies}


def preflight(need_codex: bool):
    """Fail fast, with the fix, before spending minutes of model calls."""
    problems = []
    if not API_KEY and shutil.which("claude") is None:
        problems.append("no ANTHROPIC_API_KEY (.env.local) and no `claude` CLI: set one of them")
    if need_codex and not IMAGE_KEY:
        if shutil.which("codex") is None:
            problems.append("`codex` CLI not found: npm i -g @openai/codex, then `codex login` (ChatGPT)")
        else:
            st = subprocess.run(["codex", "login", "status"], capture_output=True, text=True)
            if "Logged in" not in (st.stdout + st.stderr):
                problems.append("Codex is not logged in: run `codex login` and sign in with ChatGPT")
    try:
        urllib.request.urlopen(f"{WEB_URL}/lab", timeout=10)
    except Exception:
        problems.append(f"web app not reachable at {WEB_URL}: start it (./run.sh, or cd web && npm run dev), or set BRICKIFY_WEB")
    if problems:
        raise RuntimeError("Can't start:\n  - " + "\n  - ".join(problems))


# ------------------------------------------------------------------ stages

def _keep(run: "Run | None", name: str, text: str):
    """Raw model replies, so a parse failure can be read back."""
    if run is None:
        return
    d = run.dir / "replies"
    d.mkdir(exist_ok=True)
    (d / f"{name}.txt").write_text(text)


@dataclass
class Run:
    idea: str
    slug: str
    dir: Path
    tape: Tape
    on_model: Listener | None = None
    on_image: Listener | None = None  # concept art, as it is drawn
    on_choice: Callable[[list[dict]], int | None] | None = None  # who picks the winner
    distilled: dict = field(default_factory=dict)
    concept: Path | None = None
    views: dict[str, Path] = field(default_factory=dict)

    def next_round(self) -> int:
        return len(list(self.dir.glob("r[0-9]*.ldr")))


def distill(run: Run) -> dict:
    run.tape.emit("planner", "distill", f"making '{run.idea}' buildable", "running")
    d = first_json(claude(f"Idea: {run.idea}", [], DISTILL_SPEC, FAST_MODEL, timeout=300, max_tokens=2000))  # effort: none
    (run.dir / "distilled.json").write_text(json.dumps(d, indent=1))
    changes = "; ".join(d.get("simplifications", [])[:2])
    run.tape.emit("planner", "distill", f"concept: {d.get('concept', '')}" + (f" (changed: {changes})" if changes else ""))
    return d


def _codex_result(proc: subprocess.Popen, out: Path, since: float, reject: tuple[str, ...] = ()) -> bool:
    try:
        proc.wait(timeout=600)
    except subprocess.TimeoutExpired:
        proc.kill()
    if not out.exists():
        # Codex sometimes picks its own file name; take the newest image it wrote
        fresh = [p for p in out.parent.glob("*.png") if p.stat().st_mtime > since and not any(r in p.name for r in reject)]
        if fresh:
            shutil.move(max(fresh, key=lambda p: p.stat().st_mtime), out)
    return out.exists()


def concept(run: Run) -> Path:
    out = run.dir / "concept.png"
    prompt = run.distilled.get("image_prompt") or f"a studio product photo of an official LEGO set of {run.idea}"
    run.tape.emit("designer", "concept", "drawing the concept as an official LEGO set", "running")
    if not make_image(prompt, out):
        run.tape.emit("designer", "concept", "image generation failed", "fail")
        raise RuntimeError("concept image generation failed")
    run.tape.emit("designer", "concept", "concept ready")
    if run.on_image:
        run.on_image({"role": "concept", "path": str(out)})
    return out


VIEW_ANGLES = {
    "side": "a side view (rotated 90 degrees, the model's left side facing the camera, profile silhouette)",
    "back": "a view from behind (rotated 180 degrees)",
}


def views(run: Run) -> dict[str, Path]:
    """Side and back of the SAME model: the concept goes back in as a reference, in parallel."""
    run.tape.emit("designer", "views", "turning the concept to see its side and back", "running")

    def one(name: str, how: str) -> tuple[str, Path | None]:
        out = run.dir / f"concept-{name}.png"
        prompt = (
            "The attached image shows a LEGO model. Create one image of the exact same LEGO model, with identical "
            f"parts, colours and proportions, seen from {how}. Same plain light background and lighting, whole model in frame."
        )
        try:
            return name, out if make_image(prompt, out, reference=run.concept) else None
        except RuntimeError:
            return name, None  # a missing view costs depth, not the run

    with ThreadPoolExecutor(max_workers=len(VIEW_ANGLES)) as pool:
        got = {name: path for name, path in pool.map(lambda kv: one(*kv), VIEW_ANGLES.items()) if path}
    for name, path in got.items():
        if run.on_image:
            run.on_image({"role": name, "path": str(path)})
    run.tape.emit("designer", "views", f"got {len(got)} extra view(s): {', '.join(got) or 'none'}", "ok" if got else "warn")
    return got


def _views_text(extra: dict[str, Path]) -> str:
    if not extra:
        return ""
    lines = ", ".join(f"{v.name} is the {k}" for k, v in extra.items())
    return f"\nThe same model is also attached from other angles ({lines}); the main concept image wins if they disagree. Use them for the side profile, depth and the back."


def _images(run: Run) -> list[Path]:
    """The concept and its extra views, as files the model can look at."""
    return [p for p in [run.concept, *run.views.values()] if p and p.exists()]


# Each candidate is asked for a different take, so the three are worth choosing
# between. The names are what the app shows under each one.
STYLES = ["Closest to the art", "Chunkier and simpler", "Bolder features"]
ANGLES = [
    "",
    "\nThis is one of several designs being compared: go chunkier and simpler than you normally would, "
    "with bigger, bolder shapes and fewer sub-assemblies.",
    "\nThis is one of several designs being compared: spend your parts on the signature features "
    "(the head, the face, whatever makes it recognisable) and keep the rest plain.",
]


def _stream_bricks(run: Run) -> Callable[[str], None] | None:
    """Build the sub-assemblies of a brief as they are written, and push each
    one to the app. The bricks are real - they are simply not all there yet."""
    if not run.on_model:
        return None
    seen = {"bodies": 0, "chars": 0}

    def on_text(text: str):
        if len(text) - seen["chars"] < 400:  # parsing every token would cost more than it shows
            return
        seen["chars"] = len(text)
        half = half_brief(text)
        # one lone base plate fills the screen and says nothing: wait for shape
        if not half or len(half["bodies"]) < 2 or len(half["bodies"]) <= seen["bodies"]:
            return
        seen["bodies"] = len(half["bodies"])
        try:
            parts = resolve(assemble(half))
        except Exception:
            return  # a body that isn't legal on its own: wait for the next one
        run.on_model({"round": "draft", "draft": True, "parts": len(parts), "stands": True,
                      "ldr": to_ldr(parts, run.distilled.get("subject") or run.idea)})

    return on_text


def write_briefs(run: Run, n: int) -> list[tuple[dict, str]]:
    """n designs from the same concept, written at the same time. The brief is
    the long pole of a run, so three cost what one costs, and the critic gets a
    choice instead of one attempt to polish."""
    if n == 1:
        return [(write_brief(run), STYLES[0])]
    run.tape.emit("designer", "brief", f"working up {n} designs from the concept", "running")
    with ThreadPoolExecutor(max_workers=n) as pool:
        # only the first design streams to the screen: three at once would fight
        out = list(pool.map(lambda i: _brief_or_none(run, ANGLES[i % len(ANGLES)], i, _stream_bricks(run) if i == 0 else None), range(n)))
    briefs = [(b, STYLES[i % len(STYLES)]) for i, b in enumerate(out) if b]
    if not briefs:
        raise RuntimeError("no usable design came back")
    run.tape.emit("designer", "brief", f"{len(briefs)} designs to choose from")
    return briefs


def _brief_or_none(run: Run, angle: str, i: int, on_text: Callable[[str], None] | None = None) -> dict | None:
    try:
        return write_brief(run, angle, quiet=True, tag=f"c{i}", on_text=on_text)
    except (RuntimeError, ValueError) as e:  # one candidate failing is not the run failing
        run.tape.emit("designer", "brief", f"design {i + 1} didn't come back: {e}", "warn")
        return None


def write_brief(run: Run, angle: str = "", quiet: bool = False, tag: str = "", on_text: Callable[[str], None] | None = None) -> dict:
    if not quiet:
        run.tape.emit("designer", "brief", "reading the concept and writing the build brief", "running")
    features = ", ".join(run.distilled.get("features", []))
    reply = claude(
        f"Design brief for: {run.distilled.get('concept') or run.idea}.\n"
        + (f"Signature features to keep: {features}.\n" if features else "")
        + "The concept image is attached. Study it, then write the build brief following the spec. "
        "Match the concept's pose, proportions, colour blocking and signature details." + _views_text(run.views) + angle,
        _images(run),
        BRIEF_SPEC,
        max_tokens=BRIEF_TOKENS,
        effort=BRIEF_EFFORT,
        on_text=on_text or (_stream_bricks(run) if not quiet else None),
    )
    _keep(run, tag or f"brief-{run.next_round()}", reply)
    brief = first_json(reply)
    if not quiet:
        run.tape.emit("designer", "brief", f"brief written: {len(brief.get('bodies', []))} sub-assemblies")
    return brief


def merge_brief(base: dict, patch: dict) -> dict:
    """Apply a patch to a brief.

    A model may reply with a whole brief, or with just the parts it changed
    (bodies as {name: body}, or as a short list of complete bodies). Patches
    are the fast path: a repair is a few hundred tokens instead of a few
    thousand, and what already worked can't drift while it is rewritten."""
    if not isinstance(patch, dict) or "bodies" not in patch:
        return base
    bodies = patch["bodies"]
    if isinstance(bodies, list) and "palette" in patch and "root" in patch:
        return patch  # a whole brief, stands on its own
    changed = bodies.items() if isinstance(bodies, dict) else [(b["name"], b) for b in bodies if b.get("name")]
    out = json.loads(json.dumps(base))
    by_name = {b["name"]: i for i, b in enumerate(out["bodies"])}
    for name, body in changed:
        body = {**body, "name": name}
        if name in by_name:
            out["bodies"][by_name[name]] = body
        else:
            out["bodies"].append(body)
    for key in ("root", "details", "name"):
        if key in patch:
            out[key] = patch[key]
    if isinstance(patch.get("palette"), dict):
        out["palette"] = {**out["palette"], **patch["palette"]}
    return out


PATCH_RULE = (
    "\n\nReply with ONLY what changes, as JSON: {\"bodies\": {\"<name>\": <the whole body object>, ...}} "
    "plus \"palette\", \"details\" or \"root\" if those change. Every body you name is replaced entirely, so "
    "include all of its layers and connectors. Leave out bodies you are not changing: they stay as they are."
)


def build(brief: dict):
    """(parts, report, problems): problems are plain-language kernel objections."""
    try:
        raw = assemble(brief)
    except Exception as e:  # malformed brief: missing body, bad colour key, bad part
        return None, None, [f"The brief could not be built: {type(e).__name__}: {e}"]
    parts = resolve(raw)  # trims slivers where a sub-assembly reaches into its parent
    report = check_world(parts)
    report["trimmed"] = len(raw) - len(parts)
    problems = [f"{a} in body '{ab}' collides with {b} in body '{bb}'" for a, ab, b, bb, _ in report["worst"]]
    if report["parts"] < 12:
        problems.append(f"Only {report['parts']} parts were produced; the shapes are probably empty or mis-sized.")
    report["stands"] = stands(parts)
    s = report["stands"]
    if not s["stable"]:
        where = f", toward {s['direction']}" if s["direction"] else ""
        problems.append(
            f"The model would tip over: its centre of mass is {abs(s['margin']):.1f} studs outside the base it stands on{where}. "
            "Widen or extend the base (or the stand) on that side, or move weight back over it."
        )
    return parts, report, problems


def repair(run: Run, brief: dict, problems: list[str]) -> dict:
    run.tape.emit("inspector", "reject", "; ".join(problems[:3]), "fail")
    reply = claude(
        "This build brief has problems the kernel rejected:\n- " + "\n- ".join(problems[:8])
        + f"\n\nBrief:\n{json.dumps(brief)}\n\nFix them. The concept image is attached." + PATCH_RULE,
        _images(run),
        BRIEF_SPEC,
        FAST_MODEL,
        max_tokens=BRIEF_TOKENS,
        effort="low",
    )
    _keep(run, f"repair-{run.next_round()}", reply)
    patch = first_json(reply)
    changed = list(patch.get("bodies", {}) if isinstance(patch.get("bodies"), dict) else [])
    run.tape.emit("repair", "fix", "reworked " + (", ".join(changed[:3]) if changed else "the brief") + " to clear the kernel's objections")
    return merge_brief(brief, patch)


def build_checked(run: Run, brief: dict, fixes: int = 1):
    """Build, sending kernel objections back for repair. Returns (brief, parts, report, problems)."""
    parts, report, problems = build(brief)
    for _ in range(fixes):
        if not problems:
            break
        brief = repair(run, brief, problems)
        parts, report, problems = build(brief)
    return brief, parts, report, problems


def publish(run: Run, label: str, brief: dict, parts, report: dict) -> Path:
    """Save a built model and stream it to the app."""
    text = to_ldr(parts, run.distilled.get("subject") or run.idea)
    path = run.dir / f"{label}.ldr"
    path.write_text(text)
    (run.dir / f"brief-{label}.json").write_text(json.dumps(brief, indent=1))
    st = report["stands"]
    trimmed = f" (trimmed {report['trimmed']})" if report.get("trimmed") else ""
    run.tape.emit(
        "builder", "build",
        f"round {label}: {report['parts']} parts, {report['collisions']} collisions, "
        + ("stands" if st["stable"] else f"tips {st['direction'] or ''}".strip()) + trimmed,
        "ok" if st["stable"] and not report["collisions"] else "warn",
    )
    if run.on_model:
        run.on_model({"round": label, "ldr": text, "parts": report["parts"], "stands": st["stable"]})
    return path


def render(run: Run, *labels: str) -> list[Path]:
    """Four fixed views of each model, all in one browser."""
    outs = [run.dir / f"views-{label}" for label in labels]
    pairs = [f"{run.dir / f'{label}.ldr'}={out}" for label, out in zip(labels, outs)]
    r = subprocess.run(["node", "scripts/render-views.mjs", "--base", WEB_URL, *pairs], cwd=WEB, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        raise RuntimeError(f"rendering failed: {(r.stderr or r.stdout)[-400:].strip()}")
    return outs


JUDGE = """You are the critic for a LEGO design pipeline. Compare the rendered build with the concept image(s).
Judge: does it read as the subject at a glance, does the pose match, do proportions and colour blocking match,
are the signature details present, does it look like an official LEGO set?
Reply with only JSON: {"score": <0-10>, "issues": ["short, specific issue, worst first", ...]}."""

PICK = """You are the critic for a LEGO design pipeline. Several designs of the same concept were built and rendered.
Pick the one that reads best as the subject (silhouette, proportions, colour blocking, signature details), then say
what is worst about it. Reply with only JSON: {"best": <design number>, "score": <0-10>, "issues": ["...", ...]}."""

REVISE = """You are the designer for a LEGO design pipeline. The critic looked at renders of your build next to the
concept and listed what is wrong. Change the brief to fix the most important issues, keeping what already works."""


def judge(run: Run, renders: Path, problems: list[str] = ()) -> tuple[float, list[str]]:
    """Score one build against the concept. Small reply, so it stays cheap."""
    run.tape.emit("critic", "critique", "comparing the renders with the concept", "running")
    shots = [renders / f"{v}.png" for v in ("front", "left", "back", "right")]
    reply = claude(
        f"{JUDGE}\n\nThe concept image is attached{_views_text(run.views)}\n"
        "Then four renders of the build, in this order: front, left, back, right.\n"
        + ("\nThe kernel also reports:\n- " + "\n- ".join(problems[:4]) + "\n" if problems else ""),
        [*_images(run), *shots],
        JUDGE,
        max_tokens=2000,
        effort=JUDGE_EFFORT,
    )
    _keep(run, f"judge-{run.next_round() - 1}", reply)
    out = first_json(reply)
    score, issues = float(out.get("score", 0)), out.get("issues", [])
    run.tape.emit("critic", "critique", f"score {score:g}/10: " + "; ".join(issues[:3]), "ok" if score >= 7 else "warn")
    return score, issues


def pick(run: Run, renders: list[Path]) -> tuple[int, float, list[str]]:
    """Choose between candidate designs from their front views (one call)."""
    run.tape.emit("critic", "pick", f"comparing {len(renders)} designs with the concept", "running")
    shots = [r / "front.png" for r in renders] + [r / "left.png" for r in renders]
    reply = claude(
        f"{PICK}\n\nThe concept image is attached{_views_text(run.views)}\n"
        f"Then {len(renders)} designs from the front (designs 1..{len(renders)} in order), "
        f"then the same {len(renders)} designs from the left, in the same order.",
        [*_images(run), *shots],
        PICK,
        max_tokens=2000,
        effort=JUDGE_EFFORT,
    )
    _keep(run, "pick", reply)
    out = first_json(reply)
    i = max(0, min(len(renders) - 1, int(out.get("best", 1)) - 1))
    score, issues = float(out.get("score", 0)), out.get("issues", [])
    run.tape.emit("critic", "pick", f"design {i + 1} of {len(renders)} reads best: {score:g}/10. " + "; ".join(issues[:2]))
    return i, score, issues


def revise(run: Run, brief: dict, issues: list[str], problems: list[str] = (), renders: Path | None = None) -> dict:
    """The designer's answer to the critic: a patch, not a rewrite. It sees the
    renders too - fixing a build you can't look at is how a design drifts."""
    run.tape.emit("designer", "revise", "reworking the design from the critic's notes", "running")
    shots = [renders / f"{v}.png" for v in ("front", "left")] if renders else []
    reply = claude(
        f"{REVISE}\n\nThe critic says:\n- " + "\n- ".join(issues[:8])
        + ("\nThe kernel says:\n- " + "\n- ".join(problems[:4]) if problems else "")
        + "\n\nThe concept image is attached first, then the current build from the front and the left."
        + f"\n\nCurrent brief:\n{json.dumps(brief)}" + PATCH_RULE,
        [*_images(run), *shots],
        BRIEF_SPEC,
        max_tokens=BRIEF_TOKENS,
        effort=BRIEF_EFFORT,
    )
    _keep(run, f"revise-{run.next_round()}", reply)
    patch = first_json(reply)
    changed = list(patch.get("bodies", {}) if isinstance(patch.get("bodies"), dict) else [])
    run.tape.emit("designer", "revise", "reworked " + (", ".join(changed[:3]) if changed else "the design"))
    return merge_brief(brief, patch)


# ------------------------------------------------------------------ the loop

def _new_run(idea: str, on_event: Listener | None, on_model: Listener | None, echo: bool) -> Run:
    slug = slugify(idea)
    run_dir = RUNS / f"{time.strftime('%Y%m%d-%H%M%S')}-{slug}"
    run_dir.mkdir(parents=True)
    return Run(idea, slug, run_dir, Tape(run_dir / "tape.jsonl", (on_event,) if on_event else (), echo), on_model)


def _finish(run: Run, best: dict) -> dict:
    best.pop("report_obj", None)  # working state, not part of the record
    best.update(
        idea=run.idea,
        run=str(run.dir),
        distilled=run.distilled.get("concept"),
        concept=str(run.concept) if run.concept else None,
        views={k: str(v) for k, v in run.views.items()},
        seconds=round(time.time() - run.tape.t0),
    )
    if best.get("round") is not None:
        label = best.get("label") or f"r{best['round']}"
        best["ldr"] = str(run.dir / f"{label}.ldr")
        best["brief"] = str(run.dir / f"brief-{label}.json")
    (run.dir / "result.json").write_text(json.dumps(best, indent=1))
    return best


def _remember(best: dict, rnd: int, score: float | None, issues: list[str], report: dict, problems: list[str], label: str = ""):
    """Keep the round to ship: a legal build always beats a prettier broken one."""
    clean = not report["collisions"] and report["stands"]["stable"]
    if best["round"] is not None and (clean, score if score is not None else -1.0) <= (best.get("clean", False), best["score"] if best["score"] is not None else -1.0):
        return
    best.update(score=score, round=rnd, label=label or f"r{rnd}", parts=report["parts"], stands=report["stands"]["stable"],
                collisions=report["collisions"], clean=clean, issues=issues, issues_kernel=problems)


def _first_round(run: Run, briefs: list[tuple[dict, str]], best: dict) -> tuple[dict, float | None, list[str], Path | None]:
    """Build every candidate, render them together, and keep the one that reads best."""
    built = []
    for i, (b, style) in enumerate(briefs):
        b, parts, report, problems = build_checked(run, b)
        if parts is not None:
            label = f"r0{'abcdefg'[i] if len(briefs) > 1 else ''}"
            publish(run, label, b, parts, report)
            built.append((label, b, report, problems, style))
    if not built:
        return briefs[0], None, [], None
    renders = render(run, *[label for label, *_ in built])
    if len(built) == 1:
        i, (score, issues) = 0, judge(run, renders[0], built[0][3])
    else:
        i, score, issues = pick(run, renders)
    label, brief, report, problems, _ = built[i]
    _remember(best, 0, score, issues, report, problems, label)
    best["report_obj"] = report
    return brief, score, issues, renders[i]


def review(run: Run, rounds_built: list[dict], best: dict):
    """The last word is yours. Every version built this run is offered, the
    critic's favourite marked, with a box to say what to change. Showing only
    the critic's pick meant watching it improve a model and then being handed
    the older one."""
    usable = [r for r in rounds_built if r.get("shots")]
    if not run.on_choice or not usable:
        return
    answer = run.on_choice([{
        "label": r["label"], "style": r["style"], "parts": r["report"]["parts"],
        "stands": r["report"]["stands"]["stable"], "preferred": r["label"] == best.get("label"),
        "front": str(r["shots"] / "front.png"), "ldr": (run.dir / f"{r['label']}.ldr").read_text(),
    } for r in usable])
    if not isinstance(answer, dict):
        return  # they left it to the critic
    i, note = answer.get("index"), (answer.get("note") or "").strip()
    chosen = usable[max(0, min(len(usable) - 1, i))] if i is not None else next((r for r in usable if r["label"] == best.get("label")), usable[-1])
    if i is not None and chosen["label"] != best.get("label"):
        run.tape.emit("critic", "pick", f"you kept {chosen['style'].lower()}")
        best.update(score=chosen["score"], round=chosen["round"], label=chosen["label"], parts=chosen["report"]["parts"],
                    stands=chosen["report"]["stands"]["stable"], collisions=chosen["report"]["collisions"],
                    clean=not chosen["report"]["collisions"] and chosen["report"]["stands"]["stable"],
                    issues=chosen["issues"], issues_kernel=chosen["problems"])
    if not note:
        return
    brief, report, problems, changed = _apply_note(run, chosen["brief"], note, chosen["problems"], chosen["shots"])
    if report is not None:
        best["clean"] = False  # your word beats the score: this is the one to ship
        _remember(best, chosen["round"] + 1, None, [note], report, problems, changed)


def _apply_note(run: Run, brief: dict, note: str, problems: list[str], shots: Path):
    """Someone picked a design and said what to change: do that before going on."""
    run.tape.emit("designer", "steer", f"your note: {note}", "running")
    try:
        brief = revise(run, brief, [note], problems, shots)
        brief, parts, report, problems = build_checked(run, brief)
    except (RuntimeError, ValueError) as e:
        run.tape.emit("designer", "steer", f"couldn't make that change: {e}", "warn")
        return brief, None, problems, ""
    if parts is None:
        run.tape.emit("inspector", "reject", "that change wouldn't build; keeping the design you picked", "warn")
        return brief, None, problems, ""
    label = "r0-steered"
    publish(run, label, brief, parts, report)
    return brief, report, problems, label


def design(
    idea: str,
    concept_path: Path | None = None,
    rounds: int = 1,
    target: float = 8.0,
    fan: int = 1,
    multiview: bool = True,
    do_distill: bool = True,
    on_event: Listener | None = None,
    on_model: Listener | None = None,
    on_image: Listener | None = None,
    on_choice: Callable[[list[dict]], int | None] | None = None,
    echo: bool = True,
) -> dict:
    """The full loop. Raises on anything that leaves no model (no silent fallbacks)."""
    preflight(need_codex=concept_path is None or multiview)
    run = _new_run(idea, on_event, on_model, echo)
    run.on_image, run.on_choice = on_image, on_choice
    run.tape.emit("router", "route", f"'{idea}': concept art, {fan} designs to choose from, then up to {rounds} rounds of notes")

    if do_distill and concept_path is None:
        run.distilled = distill(run)
    if concept_path:
        run.concept = run.dir / "concept.png"
        shutil.copy(concept_path, run.concept)
    else:
        run.concept = concept(run)
    # the side and back views are drawn while the brief is written: the designer
    # works from the concept, the critic gets every angle
    pool = ThreadPoolExecutor(max_workers=1)
    pending_views = pool.submit(views, run) if multiview else None
    try:
        briefs = write_briefs(run, fan)
    finally:
        if pending_views:
            run.views = pending_views.result()
        pool.shutdown()
    best: dict = {"score": None, "round": None}
    brief, score, issues, shots = _first_round(run, briefs, best)
    # every version built this run, so you can be offered the choice at the end
    rounds_built = [{"label": best.get("label", "r0"), "style": "First build", "brief": brief, "shots": shots,
                     "report": best.get("report_obj", {"parts": best.get("parts", 0), "collisions": best.get("collisions", 0),
                                                       "stands": {"stable": best.get("stands", True)}}),
                     "score": score, "issues": issues, "problems": best.get("issues_kernel", []), "round": 0}]
    for rnd in range(1, rounds + 1):
        if best["score"] is not None and best["score"] >= target:
            break
        brief = revise(run, brief, issues, best.get("issues_kernel", []), shots)
        brief, parts, report, problems = build_checked(run, brief)
        if parts is None:
            run.tape.emit("inspector", "reject", "that revision wouldn't build; keeping the last model", "fail")
            break
        publish(run, f"r{rnd}", brief, parts, report)
        try:
            shots = render(run, f"r{rnd}")[0]
            score, issues = judge(run, shots, problems)
        except (RuntimeError, ValueError, subprocess.SubprocessError) as e:
            run.tape.emit("critic", "error", f"couldn't judge that round, keeping the best so far: {e}", "fail")
            break
        _remember(best, rnd, score, issues, report, problems, f"r{rnd}")
        rounds_built.append({"label": f"r{rnd}", "style": "After the critic's notes", "brief": brief, "shots": shots,
                             "report": report, "score": score, "issues": issues, "problems": problems, "round": rnd})

    review(run, rounds_built, best)

    if best["round"] is None:
        run.tape.emit("scribe", "done", "no buildable model came out of this run", "fail")
        _finish(run, best)
        raise RuntimeError(f"no buildable model for '{idea}' (see {run.dir / 'tape.jsonl'})")
    result = _finish(run, best)
    run.tape.emit("scribe", "done", f"best: round {best['round']} scored {best['score']}/10 ({best['parts']} parts) in {result['seconds']}s")
    return result


def edit(run_dir: Path, instruction: str, on_event: Listener | None = None, on_model: Listener | None = None, echo: bool = True) -> dict:
    """Change a finished model in plain language: revise its best brief and rebuild."""
    prev = json.loads((run_dir / "result.json").read_text())
    run = Run(prev["idea"], slugify(prev["idea"]), run_dir, Tape(run_dir / "tape.jsonl", (on_event,) if on_event else (), echo), on_model)
    run.concept = Path(prev["concept"]) if prev.get("concept") else None
    run.views = {k: Path(v) for k, v in prev.get("views", {}).items()}
    brief = json.loads(Path(prev["brief"]).read_text())

    run.tape.emit("designer", "edit", f"changing it: {instruction}", "running")
    reply = claude(
        f"The user wants this change to their LEGO model: {instruction}\n"
        "Revise the build brief to make exactly that change and keep everything else as it is. "
        "Reply with the full revised brief.\n"
        + ("The original concept image is attached (for reference only; the user's request wins).\n" if run.concept else "")
        + f"\nCurrent brief:\n{json.dumps(brief)}",
        _images(run) if run.concept else [],
        BRIEF_SPEC,
        max_tokens=BRIEF_TOKENS,
        effort="low",
    )
    brief, parts, report, problems = build_checked(run, first_json(reply))
    if parts is None:
        run.tape.emit("inspector", "reject", "couldn't build that change; keeping the previous model", "fail")
        raise RuntimeError("that change produced an unbuildable model: " + "; ".join(problems[:2]))
    rnd = run.next_round()
    publish(run, f"r{rnd}", brief, parts, report)
    best = {**prev, "score": None, "round": rnd, "label": f"r{rnd}", "parts": report["parts"],
            "stands": report["stands"]["stable"], "collisions": report["collisions"], "issues": problems, "edit": instruction}
    return _finish(run, best)


def main():
    ap = argparse.ArgumentParser(prog="brickify.pipeline", description="Idea -> LEGO model (see module docstring).")
    ap.add_argument("idea", nargs="?", help='what to build, e.g. "dog" or "hummingbird" (or the change, with --edit)')
    ap.add_argument("--concept", type=Path, help="use this concept image instead of generating one")
    ap.add_argument("--rounds", type=int, default=0, help="rounds of critic notes after the first build. Default 0: "
                    "measured over four runs, revising the winner scored worse every time (5->3, 5->3, 5->2, 5->2), "
                    "so the pipeline ships the best of --fan candidates instead")
    ap.add_argument("--fan", type=int, default=1, help="candidate designs to write in parallel and choose between (default 1; more gives the critic, or you, a choice)")
    ap.add_argument("--target", type=float, default=8.0, help="stop early at this critic score (default 8)")
    ap.add_argument("--single-view", action="store_true", help="skip the side/back concept views")
    ap.add_argument("--no-distill", action="store_true", help="send the idea to the image model as-is")
    ap.add_argument("--edit", type=Path, metavar="RUN_DIR", help="change a finished run: the positional argument is the change")
    a = ap.parse_args()
    if not a.idea:
        ap.error("say what to build (or what to change, with --edit)")
    if a.edit:
        result = edit(a.edit, a.idea)
    else:
        result = design(a.idea, a.concept, a.rounds, a.target, fan=a.fan, multiview=not a.single_view, do_distill=not a.no_distill)
    # the CLI also publishes the model for the dev lab page (/lab?m=<slug>)
    lab = WEB / "public/lab" / f"{slugify(result['idea'])}.ldr"
    shutil.copy(result["ldr"], lab)
    result["url"] = f"{WEB_URL}/lab?m={lab.stem}"
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
