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
4. brief     Claude (design model) reads the images + BRIEF.md and writes the
             build brief: shapes on small grids, colours, connectors. Never 3D
             coordinates.
5. build     The kernel assembles real parts, then checks collisions and that
             the model stands (centre of mass over its base). Rejected briefs
             go back to Claude (fast model) with the reasons, up to 2 fixes.
6. render    Four fixed angles through the web app's /lab page (the app must
             be running at BRICKIFY_WEB, default http://localhost:3000).
7. critique  Claude (design model) compares the renders with the concept, scores
             0-10 and returns a revised brief. Steps 5-7 repeat; the best round
             wins.

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


def claude(prompt: str, images: list[Path], system: str, model: str = DESIGN_MODEL, timeout: int = 900, max_tokens: int = 16000) -> str:
    """One Claude call that can look at `images`.

    With ANTHROPIC_API_KEY set this is a direct API call (images inline, no
    agent loop, much faster). Without one it shells out to `claude -p`, which
    uses your Claude Code login and reads the images from disk."""
    if API_KEY:
        return _api(prompt, images, system, model, timeout, max_tokens)
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


def _api(prompt: str, images: list[Path], system: str, model: str, timeout: int, max_tokens: int) -> str:
    content: list[dict] = []
    for img in images:
        if img.suffix.lower() not in MEDIA or not img.exists():
            continue
        raw, media = _image_bytes(img)
        content.append({"type": "text", "text": f"Image: {img.name}"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": media, "data": base64.b64encode(raw).decode()}})
    content.append({"type": "text", "text": prompt})
    body = json.dumps({"model": model, "max_tokens": max_tokens, "system": system, "messages": [{"role": "user", "content": content}]}).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={"content-type": "application/json", "x-api-key": API_KEY, "anthropic-version": "2023-06-01"},
    )
    for attempt in range(4):  # overloaded/rate-limited is normal; back off and retry
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out = json.loads(r.read())
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
        fields = {"model": IMAGE_MODEL, "prompt": prompt, "size": "1024x1024", "n": "1"}
        body, ctype = _multipart(fields, [("image[]", reference, "image/png")])
        url = "https://api.openai.com/v1/images/edits"
    else:
        body = json.dumps({"model": IMAGE_MODEL, "prompt": prompt, "size": "1024x1024", "n": 1}).encode()
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
    distilled: dict = field(default_factory=dict)
    concept: Path | None = None
    views: dict[str, Path] = field(default_factory=dict)

    def next_round(self) -> int:
        return len(list(self.dir.glob("r*.ldr")))


def distill(run: Run) -> dict:
    run.tape.emit("planner", "distill", f"making '{run.idea}' buildable", "running")
    d = first_json(claude(f"Idea: {run.idea}", [], DISTILL_SPEC, FAST_MODEL, timeout=300, max_tokens=2000))
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


def write_brief(run: Run) -> dict:
    run.tape.emit("designer", "brief", "reading the concept and writing the build brief", "running")
    features = ", ".join(run.distilled.get("features", []))
    reply = claude(
        f"Design brief for: {run.distilled.get('concept') or run.idea}.\n"
        + (f"Signature features to keep: {features}.\n" if features else "")
        + "The concept image is attached. Study it, then write the build brief following the spec. "
        "Match the concept's pose, proportions, colour blocking and signature details." + _views_text(run.views),
        _images(run),
        BRIEF_SPEC,
        max_tokens=BRIEF_TOKENS,
    )
    _keep(run, f"brief-{run.next_round()}", reply)
    brief = first_json(reply)
    run.tape.emit("designer", "brief", f"brief written: {len(brief.get('bodies', []))} sub-assemblies")
    return brief


def build(brief: dict):
    """(parts, report, problems): problems are plain-language kernel objections."""
    try:
        parts = resolve(assemble(brief))
    except Exception as e:  # malformed brief: missing body, bad colour key, bad part
        return None, None, [f"The brief could not be built: {type(e).__name__}: {e}"]
    report = check_world(parts)
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
        + f"\n\nBrief:\n{json.dumps(brief)}\n\nFix them and reply with the full corrected brief. The concept image is attached.",
        _images(run),
        BRIEF_SPEC,
        FAST_MODEL,
        max_tokens=BRIEF_TOKENS,
    )
    _keep(run, f"repair-{run.next_round()}", reply)
    run.tape.emit("repair", "fix", "revised the brief to clear the kernel's objections")
    return first_json(reply)


def build_checked(run: Run, brief: dict, fixes: int = 2):
    """Build, sending kernel objections back for repair. Returns (brief, parts, report, problems)."""
    parts, report, problems = build(brief)
    for _ in range(fixes):
        if not problems:
            break
        brief = repair(run, brief, problems)
        parts, report, problems = build(brief)
    return brief, parts, report, problems


def publish(run: Run, rnd: int, brief: dict, parts, report: dict) -> Path:
    """Save a built round and stream it to the app."""
    text = to_ldr(parts, run.distilled.get("subject") or run.idea)
    path = run.dir / f"r{rnd}.ldr"
    path.write_text(text)
    (run.dir / f"brief-{rnd}.json").write_text(json.dumps(brief, indent=1))
    st = report["stands"]
    run.tape.emit(
        "builder", "build",
        f"round {rnd}: {report['parts']} parts, {report['collisions']} collisions, " + ("stands" if st["stable"] else f"tips {st['direction'] or ''}".strip()),
        "ok" if st["stable"] and not report["collisions"] else "warn",
    )
    if run.on_model:
        run.on_model({"round": rnd, "ldr": text, "parts": report["parts"], "stands": st["stable"]})
    return path


def render(run: Run, rnd: int) -> Path:
    out = run.dir / f"views-r{rnd}"
    r = subprocess.run(["node", "scripts/render-views.mjs", str(run.dir / f"r{rnd}.ldr"), str(out), WEB_URL], cwd=WEB, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"rendering failed: {(r.stderr or r.stdout)[-400:].strip()}")
    return out


CRITIC = """You are the critic for a LEGO design pipeline. Compare the rendered build with the concept image(s).
Judge: does it read as the subject at a glance, does the pose match, do proportions and colour blocking match,
are the signature details present, does it look like an official LEGO set? Then improve the brief.
Reply with only JSON: {"score": <0-10>, "issues": ["short, specific issue", ...], "brief": <the full revised brief>}.
Revise the brief to fix the most important issues; keep what already works."""


def critique(run: Run, brief: dict, renders: Path, problems: list[str] = ()) -> tuple[float, list[str], dict]:
    run.tape.emit("critic", "critique", "comparing the renders with the concept", "running")
    shots = [renders / f"{v}.png" for v in ("front", "left", "back", "right")]
    reply = claude(
        f"{CRITIC}\n\nThe concept image is attached{_views_text(run.views)}\n"
        "Then four renders of the build, in this order: front, left, back, right.\n"
        "Compare matching angles where you can.\n"
        + ("\nThe kernel could not fix these; fix them in the brief too:\n- " + "\n- ".join(problems[:6]) + "\n" if problems else "")
        + f"\nCurrent brief:\n{json.dumps(brief)}",
        [*_images(run), *shots],
        BRIEF_SPEC,
        max_tokens=BRIEF_TOKENS,
    )
    _keep(run, f"critique-{run.next_round() - 1}", reply)
    out = first_json(reply)
    score = float(out.get("score", 0))
    issues = out.get("issues", [])
    run.tape.emit("critic", "critique", f"score {score:g}/10: " + "; ".join(issues[:3]), "ok" if score >= 7 else "warn")
    return score, issues, out.get("brief", brief)


# ------------------------------------------------------------------ the loop

def _new_run(idea: str, on_event: Listener | None, on_model: Listener | None, echo: bool) -> Run:
    slug = slugify(idea)
    run_dir = RUNS / f"{time.strftime('%Y%m%d-%H%M%S')}-{slug}"
    run_dir.mkdir(parents=True)
    return Run(idea, slug, run_dir, Tape(run_dir / "tape.jsonl", (on_event,) if on_event else (), echo), on_model)


def _finish(run: Run, best: dict) -> dict:
    best.update(
        idea=run.idea,
        run=str(run.dir),
        distilled=run.distilled.get("concept"),
        concept=str(run.concept) if run.concept else None,
        views={k: str(v) for k, v in run.views.items()},
        seconds=round(time.time() - run.tape.t0),
    )
    if best.get("round") is not None:
        best["ldr"] = str(run.dir / f"r{best['round']}.ldr")
        best["brief"] = str(run.dir / f"brief-{best['round']}.json")
    (run.dir / "result.json").write_text(json.dumps(best, indent=1))
    return best


def design(
    idea: str,
    concept_path: Path | None = None,
    rounds: int = 2,
    target: float = 8.0,
    multiview: bool = True,
    do_distill: bool = True,
    on_event: Listener | None = None,
    on_model: Listener | None = None,
    echo: bool = True,
) -> dict:
    """The full loop. Raises on anything that leaves no model (no silent fallbacks)."""
    preflight(need_codex=concept_path is None or multiview)
    run = _new_run(idea, on_event, on_model, echo)
    run.tape.emit("router", "route", f"'{idea}': distill, concept, views, brief, then build/critique x{rounds + 1} max")

    if do_distill and concept_path is None:
        run.distilled = distill(run)
    if concept_path:
        run.concept = run.dir / "concept.png"
        shutil.copy(concept_path, run.concept)
    else:
        run.concept = concept(run)
    if multiview:
        run.views = views(run)

    brief = write_brief(run)
    best: dict = {"score": None, "round": None}
    for rnd in range(rounds + 1):
        brief, parts, report, problems = build_checked(run, brief)
        if parts is None:
            run.tape.emit("inspector", "reject", "the brief is still unbuildable; stopping", "fail")
            break
        publish(run, rnd, brief, parts, report)
        clean = not report["collisions"] and report["stands"]["stable"]
        if best["round"] is None:  # anything built beats nothing, even unscored
            best = {"score": None, "round": rnd, "parts": report["parts"], "stands": report["stands"]["stable"],
                    "collisions": report["collisions"], "clean": clean, "issues": problems}
        try:
            score, issues, revised = critique(run, brief, render(run, rnd), problems)
        except (RuntimeError, ValueError, subprocess.SubprocessError) as e:
            run.tape.emit("critic", "error", f"critique failed, keeping the best so far: {e}", "fail")
            break
        # a legal build always beats a prettier one that overlaps or tips over
        if (clean, score) > (best.get("clean", False), best["score"] if best["score"] is not None else -1.0):
            best = {"score": score, "round": rnd, "parts": report["parts"], "stands": report["stands"]["stable"],
                    "collisions": report["collisions"], "clean": clean, "issues": issues}
        if score >= target or rnd == rounds:
            break
        brief = revised

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
    )
    brief, parts, report, problems = build_checked(run, first_json(reply))
    if parts is None:
        run.tape.emit("inspector", "reject", "couldn't build that change; keeping the previous model", "fail")
        raise RuntimeError("that change produced an unbuildable model: " + "; ".join(problems[:2]))
    rnd = run.next_round()
    publish(run, rnd, brief, parts, report)
    best = {**prev, "score": None, "round": rnd, "parts": report["parts"], "stands": report["stands"]["stable"], "issues": problems, "edit": instruction}
    return _finish(run, best)


def main():
    ap = argparse.ArgumentParser(prog="brickify.pipeline", description="Idea -> LEGO model (see module docstring).")
    ap.add_argument("idea", nargs="?", help='what to build, e.g. "dog" or "hummingbird" (or the change, with --edit)')
    ap.add_argument("--concept", type=Path, help="use this concept image instead of generating one")
    ap.add_argument("--rounds", type=int, default=2, help="critique/revise rounds after the first build (default 2)")
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
        result = design(a.idea, a.concept, a.rounds, a.target, multiview=not a.single_view, do_distill=not a.no_distill)
    # the CLI also publishes the model for the dev lab page (/lab?m=<slug>)
    lab = WEB / "public/lab" / f"{slugify(result['idea'])}.ldr"
    shutil.copy(result["ldr"], lab)
    result["url"] = f"{WEB_URL}/lab?m={lab.stem}"
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
