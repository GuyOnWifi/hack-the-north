"""Idea -> LEGO model. The whole design loop, stage by stage.

    uv run python -m brickify.pipeline "dog"
    uv run python -m brickify.pipeline "hummingbird" --concept my.png --rounds 1

Stages (each logs to runs/<slug>/tape.jsonl, the app's agent tape):

1. distill   Claude rewrites the idea into something buildable: calm pose,
             chunky shapes, props simplified (DISTILL.md). "dog holding an
             umbrella" -> "sitting dog wearing an umbrella hat".
2. concept   Codex (ChatGPT login, no API key) draws it as an official LEGO
             set. Skipped if --concept is given.
3. views     Codex redraws the SAME model from the side and back, using the
             concept as a reference image, so the designer sees depth.
4. brief     Claude reads the images + BRIEF.md and writes the build brief:
             shapes on small grids, colours, connectors. Never 3D coordinates.
5. build     The kernel assembles real parts and checks collisions; rejected
             briefs go back to Claude with the reasons (up to 2 fixes).
6. render    Four fixed angles, via the web app's /lab page (dev server must
             be running on BRICKIFY_WEB, default http://localhost:3210).
7. critique  Claude compares renders with the concept views, scores 0-10 and
             returns a revised brief. Steps 5-7 repeat for --rounds; the best
             round wins and is published as web/public/lab/<slug>.ldr.

Outputs: runs/<slug>/ (tape, briefs, renders, result.json) and the model at
http://localhost:3210/lab?m=<slug>.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .assembly import assemble, to_ldr
from .check import check_world, resolve

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT.parent / "web"
BRIEF_SPEC = (ROOT / "BRIEF.md").read_text()
DISTILL_SPEC = (ROOT / "DISTILL.md").read_text()
CLAUDE_MODEL = os.environ.get("BRICKIFY_MODEL", "claude-opus-5")
WEB_URL = os.environ.get("BRICKIFY_WEB", "http://localhost:3210")


# ------------------------------------------------------------------ plumbing

class Tape:
    """Append-only log of every step, in the app's agent-tape format."""

    def __init__(self, path: Path):
        self.path = path
        self.t0 = time.time()

    def emit(self, actor: str, kind: str, text: str, status: str = "ok", **extra):
        ev = {"t": round((time.time() - self.t0) * 1000), "actor": actor, "kind": kind, "text": text, "status": status, **extra}
        with self.path.open("a") as f:
            f.write(json.dumps(ev) + "\n")
        print(f"[{ev['t'] / 1000:6.1f}s] {actor:9} {status:7} {text}", flush=True)


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "model"


def claude(prompt: str, dirs: list[Path], system: str, timeout: int = 900) -> str:
    """One headless Claude call that may read files in `dirs` (images)."""
    cmd = ["claude", "-p", "--model", CLAUDE_MODEL, "--append-system-prompt", system, "--allowedTools", "Read", "--output-format", "json"]
    for d in dirs:
        cmd += ["--add-dir", str(Path(d).resolve())]
    # prompt on stdin: --add-dir takes several values and would swallow it
    for attempt in range(2):  # one retry: a dropped session or rate limit shouldn't sink a run
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=str(ROOT))
        if r.returncode == 0:
            return json.loads(r.stdout).get("result", "")
        time.sleep(5)
    # with --output-format json the reason is usually on stdout, not stderr
    raise RuntimeError(f"claude failed: {(r.stderr or r.stdout)[-400:].strip()}")


def codex_image(ask: str, out: Path, reference: Path | None = None) -> subprocess.Popen:
    """Start a Codex image generation that saves to `out` (returns the process)."""
    cmd = ["codex", "exec", "--skip-git-repo-check", "-s", "workspace-write", "-C", str(out.parent)]
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
    if shutil.which("claude") is None:
        problems.append("`claude` CLI not found: install Claude Code and sign in")
    if need_codex:
        if shutil.which("codex") is None:
            problems.append("`codex` CLI not found: npm i -g @openai/codex, then `codex login` (ChatGPT)")
        else:
            st = subprocess.run(["codex", "login", "status"], capture_output=True, text=True)
            if "Logged in" not in (st.stdout + st.stderr):
                problems.append("Codex is not logged in: run `codex login` and sign in with ChatGPT")
    try:
        urllib.request.urlopen(f"{WEB_URL}/lab", timeout=10)
    except Exception:
        problems.append(f"web app not reachable at {WEB_URL}: cd web && npm run dev -- -p 3210")
    if problems:
        raise SystemExit("Can't start:\n  - " + "\n  - ".join(problems))


# ------------------------------------------------------------------ stages

@dataclass
class Run:
    idea: str
    slug: str
    dir: Path
    tape: Tape
    distilled: dict = field(default_factory=dict)
    concept: Path | None = None
    views: dict[str, Path] = field(default_factory=dict)


def distill(run: Run) -> dict:
    run.tape.emit("router", "distill", f"making '{run.idea}' buildable", "running")
    d = first_json(claude(f"Idea: {run.idea}", [], DISTILL_SPEC, timeout=300))
    (run.dir / "distilled.json").write_text(json.dumps(d, indent=1))
    changes = "; ".join(d.get("simplifications", [])[:2])
    run.tape.emit("router", "distill", f"concept: {d.get('concept', '')}" + (f" (changed: {changes})" if changes else ""))
    return d


def concept(run: Run) -> Path:
    out = ROOT / "concepts" / f"{run.slug}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    prompt = run.distilled.get("image_prompt") or f"a studio product photo of an official LEGO set of {run.idea}"
    run.tape.emit("designer", "concept", "drawing the concept as an official LEGO set", "running")
    ask = f"Use your image generation tool to create exactly one image: {prompt}. Save it as {out.name} in the current directory. Do not write code; just generate and save the image."
    proc = codex_image(ask, out)
    try:
        proc.wait(timeout=600)
    except subprocess.TimeoutExpired:
        proc.kill()
    if not out.exists():
        # Codex sometimes picks its own file name; take the newest image it wrote
        fresh = [p for p in out.parent.glob("*.png") if p.stat().st_mtime > run.tape.t0 and "-side" not in p.name and "-back" not in p.name]
        if fresh:
            shutil.move(max(fresh, key=lambda p: p.stat().st_mtime), out)
    if not out.exists():
        err = proc.stderr.read() if proc.stderr else ""
        run.tape.emit("designer", "concept", "image generation failed: " + err[-300:], "fail")
        raise RuntimeError("concept image generation failed")
    run.tape.emit("designer", "concept", f"concept ready ({out.name})")
    return out


VIEW_ANGLES = {
    "side": "a side view (rotated 90 degrees, the model's left side facing the camera, profile silhouette)",
    "back": "a view from behind (rotated 180 degrees)",
}


def views(run: Run) -> dict[str, Path]:
    """Side and back of the SAME model: the concept goes back in as a reference, in parallel."""
    main = run.concept
    run.tape.emit("designer", "views", "turning the concept to see its side and back", "running")
    procs = {}
    for name, how in VIEW_ANGLES.items():
        out = main.with_name(f"{main.stem}-{name}.png")
        out.unlink(missing_ok=True)
        ask = (
            "The attached image shows a LEGO model. Use your image generation tool to create one image of the exact "
            f"same LEGO model, with identical parts, colours and proportions, seen from {how}. Same plain light "
            f"background and lighting, whole model in frame. Save it as {out.name} in the current directory. "
            "Do not write code; just generate and save the image."
        )
        procs[name] = (out, codex_image(ask, out, reference=main))
    got = {}
    for name, (out, proc) in procs.items():
        try:
            proc.wait(timeout=600)
        except subprocess.TimeoutExpired:
            proc.kill()
        if out.exists():
            got[name] = out
    run.tape.emit("designer", "views", f"got {len(got)} extra view(s): {', '.join(got) or 'none'}", "ok" if got else "warn")
    return got


def _views_text(extra: dict[str, Path]) -> str:
    if not extra:
        return ""
    lines = "\n".join(f"- {k} view: {v}" for k, v in extra.items())
    return f"\nExtra views of the same model (if they disagree with the main image, the main image wins):\n{lines}\nUse them for the side profile, depth and the back."


def write_brief(run: Run) -> dict:
    run.tape.emit("designer", "brief", "reading the concept and writing the build brief", "running")
    features = ", ".join(run.distilled.get("features", []))
    reply = claude(
        f"Design brief for: {run.distilled.get('concept') or run.idea}.\n"
        + (f"Signature features to keep: {features}.\n" if features else "")
        + f"The main concept image is at {run.concept}. Read it, then write the build brief following the spec. "
        "Match the concept's pose, proportions, colour blocking and signature details." + _views_text(run.views),
        [run.concept.parent],
        BRIEF_SPEC,
    )
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
    return parts, report, problems


def repair(run: Run, brief: dict, problems: list[str]) -> dict:
    run.tape.emit("inspector", "reject", "; ".join(problems[:3]), "fail")
    reply = claude(
        "This build brief has problems the kernel rejected:\n- " + "\n- ".join(problems[:8])
        + f"\n\nBrief:\n{json.dumps(brief)}\n\nFix them and reply with the full corrected brief. The concept is at {run.concept}.",
        [run.concept.parent],
        BRIEF_SPEC,
    )
    run.tape.emit("repair", "fix", "revised the brief to clear the kernel's objections")
    return first_json(reply)


def render(run: Run, rnd: int, parts) -> Path:
    lab = f"{run.slug}-r{rnd}"
    text = to_ldr(parts, run.distilled.get("subject") or run.idea)
    (WEB / "public/lab" / f"{lab}.ldr").write_text(text)
    (run.dir / f"{lab}.ldr").write_text(text)
    out = run.dir / f"views-r{rnd}"
    subprocess.run(["node", "scripts/render-views.mjs", lab, str(out), WEB_URL], cwd=WEB, check=True, capture_output=True, timeout=600)
    return out


CRITIC = """You are the critic for a LEGO design pipeline. Compare the rendered build with the concept image(s).
Judge: does it read as the subject at a glance, does the pose match, do proportions and colour blocking match,
are the signature details present, does it look like an official LEGO set? Then improve the brief.
Reply with only JSON: {"score": <0-10>, "issues": ["short, specific issue", ...], "brief": <the full revised brief>}.
Revise the brief to fix the most important issues; keep what already works."""


def critique(run: Run, brief: dict, renders: Path) -> tuple[float, list[str], dict]:
    run.tape.emit("inspector", "critique", "comparing the renders with the concept", "running")
    files = ", ".join(str(renders / f"{v}.png") for v in ("front", "left", "back", "right"))
    reply = claude(
        f"{CRITIC}\n\nConcept image: {run.concept}{_views_text(run.views)}\n"
        f"Renders of the build (front, left, back, right): {files}\n"
        "Compare matching angles where you can.\n\n"
        f"Current brief:\n{json.dumps(brief)}",
        [run.concept.parent, renders],
        BRIEF_SPEC,
    )
    out = first_json(reply)
    score = float(out.get("score", 0))
    issues = out.get("issues", [])
    run.tape.emit("inspector", "critique", f"score {score:g}/10: " + "; ".join(issues[:3]), "ok" if score >= 7 else "warn")
    return score, issues, out.get("brief", brief)


# ------------------------------------------------------------------ the loop

def design(idea: str, concept_path: Path | None = None, rounds: int = 2, target: float = 8.0, multiview: bool = True, do_distill: bool = True) -> dict:
    preflight(need_codex=concept_path is None or multiview)
    slug = slugify(idea)
    run_dir = ROOT / "runs" / slug
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    run = Run(idea, slug, run_dir, Tape(run_dir / "tape.jsonl"))
    run.tape.emit("router", "route", f"'{idea}': distill, concept, views, brief, then build/critique x{rounds + 1} max")

    if do_distill and concept_path is None:
        run.distilled = distill(run)
    run.concept = concept_path.resolve() if concept_path else concept(run)
    if multiview:
        run.views = views(run)

    brief = write_brief(run)
    best = {"score": -1.0}
    for rnd in range(rounds + 1):
        parts, report, problems = build(brief)
        fixes = 0
        while problems and fixes < 2:
            brief = repair(run, brief, problems)
            parts, report, problems = build(brief)
            fixes += 1
        if parts is None:
            run.tape.emit("inspector", "reject", "brief still unbuildable; stopping", "fail")
            break
        (run.dir / f"brief-{rnd}.json").write_text(json.dumps(brief, indent=1))
        run.tape.emit("scribe", "build", f"round {rnd}: {report['parts']} parts, {report['collisions']} collisions")
        renders = render(run, rnd, parts)
        try:
            score, issues, revised = critique(run, brief, renders)
        except (RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
            # keep what was built: an unscored round still beats no model at all
            run.tape.emit("inspector", "error", f"critique failed, stopping with the best so far: {e}", "fail")
            if not best.get("lab"):
                best = {"score": None, "round": rnd, "lab": f"{slug}-r{rnd}", "parts": report["parts"], "issues": []}
            break
        if score > best["score"]:
            best = {"score": score, "round": rnd, "lab": f"{slug}-r{rnd}", "parts": report["parts"], "issues": issues}
        if score >= target or rnd == rounds:
            break
        brief = revised

    if best.get("lab"):
        shutil.copy(WEB / "public/lab" / f"{best['lab']}.ldr", WEB / "public/lab" / f"{slug}.ldr")
        best["url"] = f"{WEB_URL}/lab?m={slug}"
    best.update(idea=idea, distilled=run.distilled.get("concept"), concept=str(run.concept), seconds=round(time.time() - run.tape.t0))
    run.tape.emit("scribe", "done", f"best: round {best.get('round')} scored {best.get('score')}/10 ({best.get('parts')} parts) in {best['seconds']}s")
    (run.dir / "result.json").write_text(json.dumps(best, indent=1))
    return best


def main():
    ap = argparse.ArgumentParser(prog="brickify.pipeline", description="Idea -> LEGO model (see module docstring).")
    ap.add_argument("idea", help='what to build, e.g. "dog" or "hummingbird"')
    ap.add_argument("--concept", type=Path, help="use this concept image instead of generating one")
    ap.add_argument("--rounds", type=int, default=2, help="critique/revise rounds after the first build (default 2)")
    ap.add_argument("--target", type=float, default=8.0, help="stop early at this critic score (default 8)")
    ap.add_argument("--single-view", action="store_true", help="skip the side/back concept views")
    ap.add_argument("--no-distill", action="store_true", help="send the idea to the image model as-is")
    a = ap.parse_args()
    result = design(a.idea, a.concept, a.rounds, a.target, multiview=not a.single_view, do_distill=not a.no_distill)
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
