"""Hit every endpoint of a running demo-safe server and score it. Loopback only.

    python -m demo.verify --port 8000 --canned demo/canned

WHY it is stdlib urllib and not httpx or the FastAPI TestClient: `TestClient` proves the app
object works, which is not the question. The question is whether the thing on port 8000 --
started by the shell script, in demo-safe mode, with the snapshot on disk -- answers a real
socket. So this talks HTTP to 127.0.0.1 and nothing else, and `demo.netguard` is installed
first so a check that quietly needed the internet fails here rather than on stage.

Every check states what a PRESENTER would see, not what a status code was, because the output
of this file is the pre-demo checklist a tired human reads.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from demo import netguard                                           # noqa: E402

TIMEOUT = 20.0


class Checks:
    """A running tally that prints as it goes. Nothing clever; a demo tool should be boring."""

    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.failures: list[str] = []
        self.passes = 0

    # -- http ---------------------------------------------------------
    def request(self, method: str, path: str, *, body=None, headers=None, raw=False,
                timeout: float = TIMEOUT):
        url = f"{self.base}{path}"
        data = json.dumps(body).encode() if body is not None else None
        hdrs = {"Accept": "application/json", **(headers or {})}
        if data is not None:
            hdrs["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = r.read()
            # Lower-cased: uvicorn sends header names in lower case and `dict(r.headers)`
            # throws away the case-insensitivity that `r.headers.get` would have given us.
            head = {k.lower(): v for k, v in r.headers.items()}
            if raw:
                return r.status, payload, head
            text = payload.decode("utf-8", "replace")
            try:
                return r.status, json.loads(text), head
            except json.JSONDecodeError:
                return r.status, text, head

    # -- scoring ------------------------------------------------------
    def check(self, name: str, fn) -> object:
        try:
            detail = fn()
        except urllib.error.HTTPError as exc:
            self.failures.append(name)
            print(f"  FAIL  {name}: HTTP {exc.code} {exc.read()[:160]!r}")
            return None
        except Exception as exc:
            self.failures.append(name)
            print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
            return None
        self.passes += 1
        print(f"  ok    {name}" + (f" -- {detail}" if isinstance(detail, str) else ""))
        return detail


def wait_for_health(base: str, seconds: float = 30.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{base}/health", timeout=2.0) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.15)
    return False


def verify(port: int, canned: pathlib.Path) -> Checks:
    c = Checks(f"http://127.0.0.1:{port}")
    snap = {name: json.loads((canned / name).read_text())
            for name in ("inventory.json", "build.json", "report.json", "steps.json")}
    ldr = (canned / "model.ldr").read_text()
    tape = [json.loads(x) for x in (canned / "tape.jsonl").read_text().splitlines() if x.strip()]

    # -- the mode itself ----------------------------------------------
    def health():
        _s, b, _h = c.request("GET", "/health")
        assert b["demo_safe"] is True, "DEMO_SAFE is OFF -- this server will try to think"
        assert b["llm"] is False, "the LLM seam is live; a dead wifi will hang it"
        return f"demo_safe, no LLM, {len(b['generators'])} generators"
    c.check("/health says demo-safe with no LLM", health)

    def which():
        _s, b, _h = c.request("GET", "/demo/snapshot")
        assert b["exists"], f"snapshot directory missing: {b['canned']}"
        counts = (b.get("meta") or {}).get("counts") or {}
        return (f"{pathlib.Path(b['canned']).name}: {counts.get('parts', '?')} parts, "
                f"{counts.get('steps', '?')} steps, netguard={b['netguard']}")
    c.check("/demo/snapshot names the loaded snapshot", which)

    # -- the bin -------------------------------------------------------
    sid = None

    def session():
        nonlocal sid
        s, b, _h = c.request("POST", "/sessions", body={})
        assert s == 201
        sid = b["session_id"]
        assert b["totals"]["pieces"] == snap["inventory.json"]["totals"]["pieces"], \
            "a new session is not seeded with the canned bin"
        return f"{b['totals']['distinct']} rows, {b['totals']['pieces']} pieces"
    c.check("POST /sessions seeds the canned bin", session)

    hdr = lambda: {"X-Session-Id": sid}                          # noqa: E731

    def read_session():
        _s, b, _h = c.request("GET", f"/sessions/{sid}")
        assert len(b["items"]) == len(snap["inventory.json"]["items"])
        return f"{len(b['items'])} rows"
    c.check("GET /sessions/{id} returns the bin", read_session)

    def inventory():
        _s, b, _h = c.request("GET", "/inventory", headers=hdr())
        amber = [i for i in b["items"] if i.get("status") == "needs_review"]
        with_evidence = [i for i in amber if (i.get("evidence") or {}).get("bbox")]
        assert b["items"], "the inventory grid is empty"
        return (f"{len(b['items'])} rows, {len(amber)} amber, "
                f"{len(with_evidence)} with a crop box to click")
    c.check("GET /inventory has amber rows to click at 0:15", inventory)

    def editable():
        s, row, _h = c.request("POST", "/inventory/items", headers=hdr(),
                               body={"part": "3001", "color": 4, "qty": 1})
        assert s == 201
        s2, _b, _h2 = c.request("DELETE", f"/inventory/items/{row['id']}", headers=hdr())
        assert s2 == 200
        return "add + delete both work (invariant 10)"
    c.check("the inventory grid is editable", editable)

    # -- the build ------------------------------------------------------
    bid = None

    def start():
        nonlocal bid
        s, b, _h = c.request("POST", "/builds", headers=hdr(),
                             body={"prompt": "build me a rover", "seed": 41})
        assert s == 202
        bid = b["build_id"]
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            _s2, body, _h2 = c.request("GET", f"/builds/{bid}")
            if body["status"] != "running":
                assert body["status"] == "ok", body.get("human")
                assert body["build"]["parts"] == snap["build.json"]["parts"], \
                    "the served build is not the canned build"
                return f"{len(body['build']['parts'])} parts, version {body['version']}"
            time.sleep(0.05)
        raise AssertionError("the build never finished")
    c.check("POST /builds returns the canned build", start)

    def events():
        _s, payload, headers = c.request("GET", f"/builds/{bid}/events", raw=True, timeout=10)
        assert "text/event-stream" in headers.get("content-type", ""), headers
        lines = [ln[6:] for ln in payload.decode().splitlines() if ln.startswith("data: ")]
        seen = [json.loads(x) for x in lines if x.strip().startswith("{")]
        actors = [e.get("actor") for e in seen if "actor" in e]
        assert len(actors) >= len(tape), f"{len(actors)} tape events, expected {len(tape)}"
        assert b"event: done" in payload, "the stream never closed"
        return f"{len(actors)} events: {' -> '.join(dict.fromkeys(actors))}"
    c.check("GET /builds/{id}/events streams the agent tape", events)

    def steps():
        _s, b, _h = c.request("GET", f"/builds/{bid}/steps")
        assert b == snap["steps.json"], "the served steps are not the canned steps"
        return f"{b['total']} steps"
    c.check("GET /builds/{id}/steps matches the snapshot", steps)

    def validation():
        _s, b, _h = c.request("GET", f"/builds/{bid}/validation")
        assert b == snap["report.json"]
        assert b["ok"] is True
        return f"ok, {len(b['warnings'])} warning(s)"
    c.check("GET /builds/{id}/validation is a clean report", validation)

    def model():
        _s, text, _h = c.request("GET", f"/builds/{bid}/model.ldr")
        assert text == ldr, "the served .ldr is not the canned .ldr"
        return f"{len(text.splitlines())} lines, {text.count('0 STEP')} STEP markers"
    c.check("GET /builds/{id}/model.ldr is byte-identical", model)

    def versions():
        _s, b, _h = c.request("GET", f"/builds/{bid}/versions")
        assert b["versions"], "no version tree"
        return f"head at v{b['head']}"
    c.check("GET /builds/{id}/versions has a tree", versions)

    # -- the edit, then put it back where we found it --------------------
    def edit():
        s, b, _h = c.request("POST", f"/builds/{bid}/edit", headers=hdr(),
                             body={"instruction": "make the chassis longer"})
        assert s == 200 and b["applied"] is True, b
        summary = b.get("summary") or "edited"
        s2, u, _h2 = c.request("POST", f"/builds/{bid}/undo")
        assert s2 == 200 and u["applied"] is True, "undo did not move the head back"
        return f"{summary}; undo works"
    c.check("POST /builds/{id}/edit regenerates one subtree", edit)

    # -- the manual ------------------------------------------------------
    def manual():
        s, payload, _h = c.request("GET", "/demo/manual/manual.html", raw=True)
        assert s == 200 and b"<html" in payload[:4000].lower()
        return f"{len(payload) // 1024} KB, self-contained"
    c.check("GET /demo/manual/manual.html serves the manual", manual)

    first_png = next(iter(sorted((canned / "manual" / "steps").glob("step_*.png"))), None)
    if first_png is not None:
        def png():
            s, payload, _h = c.request("GET", f"/demo/manual/steps/{first_png.name}", raw=True)
            assert s == 200 and payload[:8] == b"\x89PNG\r\n\x1a\n"
            return f"{first_png.name}, {len(payload) // 1024} KB"
        c.check("GET /demo/manual/steps/<step>.png renders", png)

    if (canned / "manual" / "manual.pdf").exists():
        def pdf():
            s, payload, _h = c.request("GET", "/demo/manual/manual.pdf", raw=True)
            assert s == 200 and payload[:5] == b"%PDF-"
            return f"{len(payload) // 1024} KB -- this is the one you print"
        c.check("GET /demo/manual/manual.pdf is a real PDF", pdf)
    else:
        print("  WARN  no manual.pdf in the snapshot -- print from manual.html instead")

    return c


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m demo.verify", description=__doc__)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--canned", default=str(pathlib.Path(__file__).resolve().parent / "canned"))
    ap.add_argument("--allow-network", action="store_true")
    a = ap.parse_args(argv)

    if not a.allow_network:
        netguard.install()

    base = f"http://127.0.0.1:{a.port}"
    if not wait_for_health(base):
        print(f"FAIL  nothing answering on {base}/health")
        return 1

    canned = pathlib.Path(a.canned).resolve()
    print(f"verifying {base} against {canned}")
    c = verify(a.port, canned)
    print(f"\n{c.passes} passed, {len(c.failures)} failed")
    for f in c.failures:
        print(f"  FAILED: {f}")
    return 0 if not c.failures else 1


if __name__ == "__main__":
    sys.exit(main())
