"""Zero-dependency HTTP API over the session (the seam to the frontend lane).
stdlib only, so it runs under DEMO_SAFE with wifi off.

  POST /api/build        {prompt}      -> {version, report, steps, tape, tree}
  POST /api/edit         {text, selection?, base?, mode?}  -> payload + {edit}
  POST /api/edit_direct  {ops, dry_run?, base}             -> payload + {edit}
  POST /api/load_ldr     {name, ldr, source?}              -> payload + {edit}
  POST /api/choose       {index|null, note?} -> {ok}   (pick a candidate design mid-run)
  POST /api/try_another  {}            -> {version, report, tree}
  POST /api/undo|redo    {}            -> {version, report, tree, edit}
  GET  /api/library                    -> {models:[...]}  every model designed here
  GET  /api/library/thumb?id=           -> png of that model
  POST /api/open         {id}           -> make a saved model the current one
  POST /api/library/remove {id}         -> move it to runs/removed/
  POST /api/library/keep {id, keep}     -> mark it to survive a clear
  POST /api/library/clear {}            -> remove everything not marked kept
  GET  /api/state                      -> current build/report/steps
  GET  /api/parts                      -> the editable part table (docs/EDITING.md D.2)
  GET  /api/ldr?version=                -> that version's model (default: current) as LDraw
  GET  /                               -> a tiny self-contained dev console

Run:  python bricolage/server.py   (then open http://localhost:8017)
Env:  ENGINE=c (default: pipeline C, brickify) or ENGINE=a (the layer builder);
      PROVIDER=mock for offline tests (implies ENGINE=a);  PORT to change the port.
"""
from __future__ import annotations
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from demo import rich_bin
from model import Inventory
from session import Session
from serialize import build_json, report_json, edit_json, nav_json
from ldraw import to_ldr
import engine_c
import nl_c
from brickify import edits as E

# Designs are never limited by a real bin: the app asks for an idea, the
# designer builds it.
SESSION = Session(Inventory({}, unlimited=True))
MAX_LDR = 4 * 1024 * 1024
_TABLE: dict = {}          # version id -> the part table, with its chips

# where a POSTed reference sketch is stored (single-user demo: one current sketch)
SKETCH_PATH = "/tmp/bricked_sketch.png"


def _payload(vid=None):
    v = SESSION.versions.get(vid or SESSION.head)
    if not v:
        return {"version": None, "tree": SESSION.tree_ascii()}
    from sequence import sequence, Unbuildable
    steps = None
    if engine_c.is_c(v.build):
        steps = engine_c.steps(v.build)
    elif v.report.ok:
        try:
            steps = sequence(v.build)
        except Unbuildable:
            pass
    # geometry events carry whole LDraw models for the live preview; the
    # finished version's tape is the story, and the model has its own endpoint
    tape = [e for e in v.tape.events if e.get("kind") != "geometry"] if v.tape else []
    prov = v.build.provenance
    if engine_c.is_c(v.build):
        phys = engine_c.physics(v.build)
    elif prov.get("backend") == "harness" and prov.get("bricks"):
        import physics
        ph = physics.analyze(prov["bricks"])
        phys = {"stable": physics.stands(prov["bricks"]), "studs": ph.get("studs", 0),
                "broken": physics.broken_bricks(prov["bricks"]),
                "backend": "harness", "com": None, "base": [], "failures": []}
    else:
        import stability
        phys = stability.report(v.build.parts)
    return {"version": v.id, "name": v.build.name,
            "build": build_json(v.build), "report": report_json(v.report),
            "steps": steps, "tape": tape, "tree": SESSION.tree_ascii(),
            "physics": phys, "head": SESSION.head}


def _label(v) -> str:
    """What a version did, in the words the user was shown."""
    from session import _direct_label
    kind = v.op.get("kind")
    if kind == "edit_direct_c":
        return _direct_label(v.op)
    if kind in ("edit_c", "edit"):
        return str(v.op.get("text") or "that change")
    if kind == "load_ldr":
        return f"opening {v.op.get('name')}"
    return "that change"


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self._send(204, "")

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        u = urlparse(self.path)
        if u.path == "/":
            return self._send(200, CONSOLE, "text/html; charset=utf-8")
        if u.path == "/api/state":
            return self._send(200, _payload())
        if u.path == "/api/parts":
            return self._parts()
        if u.path == "/api/ldr":
            # a version may be named: two designs racing must not hand back
            # each other's model
            want = parse_qs(u.query).get("version", [None])[0]
            v = SESSION.versions.get(want or SESSION.head)
            if v and engine_c.is_c(v.build):  # pipeline C writes its own LDraw, steps included
                lib = v.build.provenance.get("lib") or ""
                text = v.build.provenance["ldr"] + ("\n" + lib if lib else "")
                return self._send(200, text, "text/plain")
            # Include the sequenced 0 STEP markers (HANDOFF: "LDrawLoader reads steps natively").
            return self._send(200, to_ldr(v.build, _payload()["steps"]) if v else "", "text/plain")
        if u.path == "/api/library":
            return self._send(200, {"models": engine_c.library()})
        if u.path == "/api/library/thumb":
            f = engine_c.thumb(parse_qs(u.query).get("id", [""])[0])
            if not f:
                return self._send(404, {"error": "no picture for that one"})
            data = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        if u.path == "/api/build_stream":
            q = parse_qs(u.query)
            prompt = q.get("prompt", ["build a rover"])[0]
            use_sketch = q.get("sketch", ["0"])[0] in ("1", "true")
            sketch = SKETCH_PATH if use_sketch and os.path.exists(SKETCH_PATH) else None
            return self._stream_build(prompt, sketch)
        if u.path == "/api/compare":
            # split-screen: 'LLM places bricks' (floats/topples) vs our solver
            from pipeline import compare
            prompt = parse_qs(u.query).get("prompt", ["build me a flower"])[0]
            return self._send(200, compare(prompt, SESSION.inv))
        self._send(404, {"error": "not found"})

    def _stream_build(self, prompt, sketch=None):
        """Run a build and stream each tape event live as Server-Sent Events.
        Synchronous: the handler thread writes as Tape.emit fires."""
        import threading
        from tape import Tape
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")   # tell proxies not to buffer
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        # a 2KB comment preamble forces the proxy to flush its buffer so events
        # stream live instead of arriving batched when the first LLM call returns.
        self.wfile.write(b": " + b" " * 2048 + b"\n\n")
        self.wfile.flush()

        lock = threading.Lock()

        def push(ev):
            with lock:
                self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
                self.wfile.flush()

        # HEARTBEAT: a real `claude -p` design takes 60-130s, and a proxy/browser
        # will drop an SSE connection that goes silent that long — the client then
        # falls back to the stale fixture. A comment ping every 5s keeps the
        # connection alive through the long LLM call (comments are ignored by the
        # EventSource, so they never show up as tape events).
        alive = threading.Event(); alive.set()

        def heartbeat():
            while alive.is_set():
                if alive.wait(5):
                    break
                try:
                    with lock:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break
        hb = threading.Thread(target=heartbeat, daemon=True)
        hb.start()

        tape = Tape()
        tape.listeners.append(push)
        try:
            SESSION.build(prompt, tape=tape, sketch=sketch)
            done = _payload()
            done["event"] = "done"
            push(done)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            # never leave the stream hanging: emit a terminal error frame so the
            # frontend can show a failure instead of spinning forever.
            try:
                push({"event": "error", "error": str(e)})
            except (BrokenPipeError, ConnectionResetError):
                pass
        finally:
            alive.clear()

    def _parts(self):
        try:
            return self._parts_inner()
        except Exception as e:
            import traceback
            traceback.print_exc()
            return self._send(500, {"error": str(e), "human": "I couldn't read that model's piece list."})

    def _parts_inner(self):
        with SESSION.lock:
            model = SESSION.model_at()
            if model is None:
                return self._send(409, {"error": "NO_MODEL", "human": E.HUMAN["NO_MODEL"]})
            vid = SESSION.head
            cached = _TABLE.get(vid)
            if cached is None:
                t = E.table(model)
                t["suggestions"] = nl_c.suggest(SESSION, t)
                v = SESSION.versions[vid]
                t["version"] = vid
                t["source"] = v.build.provenance.get("source")
                cached = _TABLE[vid] = t
                if len(_TABLE) > 24:
                    _TABLE.pop(next(iter(_TABLE)))
            return self._send(200, cached)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n) if n else b""
        if len(raw) > MAX_LDR:
            return self._send(400, {"error": "TOO_BIG", "human": "That file is too big to open."})
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            return self._send(400, {"error": "BAD_JSON", "human": "I couldn't read that request."})
        if self.path in ("/api/edit_direct", "/api/load_ldr", "/api/edit"):
            return self._edit_route(body)
        try:
            extra = None
            if self.path == "/api/build":
                SESSION.build(body.get("prompt", "build a rover"))
            elif self.path == "/api/library/remove":
                return self._send(200, {"ok": engine_c.remove(body.get("id", ""))})
            elif self.path == "/api/library/keep":
                return self._send(200, {"ok": engine_c.keep(body.get("id", ""), bool(body.get("keep", True)))})
            elif self.path == "/api/library/clear":
                return self._send(200, {"ok": True, "removed": engine_c.clear_unkept()})
            elif self.path == "/api/open":
                # bring a saved model back as the current one
                b = engine_c.open_run(body.get("id", ""))
                SESSION._commit(None, {"kind": "build", "prompt": b.name, "seed": 0, "recipe": engine_c.recipe(b)},
                                b, engine_c.report(b))
            elif self.path == "/api/choose":
                # which of the candidate designs to keep (null = let the critic)
                engine_c.choose(body.get("index"), body.get("note", ""), body.get("ask", ""))
                return self._send(200, {"ok": True})
            elif self.path == "/api/try_another":
                cur = SESSION.versions.get(SESSION.head)
                if cur and cur.op.get("kind") in ("edit_direct_c", "load_ldr"):
                    extra = nav_json("nav", "There's only one way to make that change. "
                                            "Try a different change instead.", accepted=False)
                else:
                    SESSION.try_another()
            elif self.path == "/api/undo":
                cur = SESSION.versions.get(SESSION.head)
                if not cur or not cur.parent:
                    extra = nav_json("nav", "Nothing to undo.", accepted=False)
                else:
                    SESSION.undo()
                    extra = nav_json("nav", "Undid: " + _label(cur))
            elif self.path == "/api/redo":
                if not SESSION._redo_stack:
                    extra = nav_json("nav", "Nothing to redo.", accepted=False)
                else:
                    SESSION.redo()
                    extra = nav_json("nav", "Redid: " + _label(SESSION.versions[SESSION.head]))
            elif self.path == "/api/sketch":
                # store a reference sketch (data URL or bare base64 PNG) for the
                # next build_stream?sketch=1 — brickify designs toward it.
                import base64
                data = body.get("image", "")
                if "," in data:
                    data = data.split(",", 1)[1]
                with open(SKETCH_PATH, "wb") as f:
                    f.write(base64.b64decode(data))
                return self._send(200, {"ok": True})
            else:
                return self._send(404, {"error": "not found"})
        except Exception as e:
            return self._send(500, {"error": str(e)})
        out = _payload()
        if extra is not None:
            out["edit"] = extra
        self._send(200, out)

    def _edit_route(self, body):
        with SESSION.lock:
            try:
                if self.path == "/api/load_ldr":
                    text = body.get("ldr") or ""
                    if not isinstance(text, str) or not text.strip():
                        return self._send(400, {"error": "EMPTY", "human": "There are no pieces in that file."})
                    name = str(body.get("name") or "Model")
                    v = SESSION.load_ldr(name, text, body.get("source"))
                    out = _payload()
                    out["edit"] = dict(
                        nav_json("load", f"{name} is ready to change: {len(v.build.parts)} pieces"),
                        tape=[dict(e) for e in v.tape.events])
                    return self._send(200, out)

                if self.path == "/api/edit_direct":
                    ops = body.get("ops")
                    base = body.get("base")
                    dry = bool(body.get("dry_run"))
                    if SESSION.model_at() is None:
                        return self._send(409, {"error": "NO_MODEL", "human": E.HUMAN["NO_MODEL"]})
                    v, res = SESSION.edit_parts(ops, dry_run=dry, base=base)
                    out = _payload()
                    out["edit"] = edit_json(res, "direct", dry_run=dry)
                    return self._send(200, out)

                # /api/edit — plain language
                if SESSION.model_at() is None and engine_c.is_c(
                        getattr(SESSION.versions.get(SESSION.head), "build", None)):
                    return self._send(409, {"error": "NO_MODEL", "human": E.HUMAN["NO_MODEL"]})
                cur = SESSION.versions.get(SESSION.head)
                if not cur:
                    return self._send(409, {"error": "NO_MODEL", "human": E.HUMAN["NO_MODEL"]})
                if not engine_c.is_c(cur.build):
                    SESSION.edit(body.get("text", ""))
                    return self._send(200, _payload())
                _, edit = nl_c.handle(SESSION, body.get("text", ""), body.get("selection") or [],
                                      body.get("base"), body.get("mode", "auto"))
                out = _payload()
                out["edit"] = edit
                return self._send(200, out)
            except E.OpError as e:
                return self._send(400, {"error": e.code, "human": e.human})
            except Exception as e:
                import traceback
                traceback.print_exc()
                return self._send(500, {"error": str(e)})


CONSOLE = """<!doctype html><meta charset=utf-8><title>Bricolage — Lane B console</title>
<style>
 body{background:#111;color:#ddd;font:14px/1.5 ui-monospace,Menlo,monospace;margin:0;padding:20px}
 h1{font-size:16px;color:#fff;margin:0 0 12px} .muted{color:#888}
 input,button{font:inherit;background:#1c1c1c;color:#eee;border:1px solid #333;border-radius:6px;padding:7px 10px}
 button{cursor:pointer} button:hover{background:#262626}
 .row{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
 .cols{display:grid;grid-template-columns:1fr 1fr;gap:18px}
 .card{background:#171717;border:1px solid #262626;border-radius:10px;padding:14px}
 pre{white-space:pre-wrap;margin:0}
 .ok{color:#4ade80}.fail{color:#f87171}.warn{color:#fbbf24}.run{color:#888}
 .ev{padding:2px 0}.actor{display:inline-block;width:80px;text-align:right;margin-right:10px}
 .designer{color:#22d3ee}.inspector{color:#c084fc}.repair{color:#fbbf24}.router{color:#60a5fa}.scribe{color:#4ade80}
</style>
<h1>🧱 Bricolage — Lane B console <span class=muted>the LLM decides what; code places every brick</span></h1>
<div class=row>
 <input id=prompt size=34 placeholder="build me a desk rover" value="build me a desk rover">
 <button onclick=build()>Build</button>
 <button onclick="edit('make the chassis longer')">chassis longer</button>
 <button onclick="edit('make the cabin taller')">cabin taller</button>
 <button onclick=post('/api/try_another')>try another</button>
 <button onclick=post('/api/undo')>undo</button>
 <button onclick=post('/api/redo')>redo</button>
</div>
<div class=cols>
 <div class=card><b>agent tape</b><div id=tape style=margin-top:8px></div></div>
 <div>
  <div class=card><b>report</b> <span id=report></span><pre id=stats class=muted style=margin-top:6px></pre></div>
  <div class=card style=margin-top:14px><b>version tree</b><pre id=tree style=margin-top:6px></pre></div>
 </div>
</div>
<script>
const $=s=>document.querySelector(s)
function addEv(e){
 const cls={ok:'ok',fail:'fail',warn:'warn',running:'run'}[e.status]||''
 const ic={ok:'✓',fail:'✗',warn:'!',running:'…'}[e.status]||' '
 $('#tape').insertAdjacentHTML('beforeend',
   `<div class=ev><span class="actor ${e.actor}">${e.actor}</span><span class=${cls}>${ic}</span> ${e.text}</div>`)
}
function build(){                       // live SSE — events stream from the server
 $('#tape').innerHTML=''
 const es=new EventSource('/api/build_stream?prompt='+encodeURIComponent($('#prompt').value))
 es.onmessage=m=>{const d=JSON.parse(m.data)
   if(d.event==='done'){es.close(); renderMeta(d)} else addEv(d)}
 es.onerror=()=>es.close()
}
async function edit(t){await post('/api/edit',{text:t})}
async function post(url,body){
 const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})})
 render(await r.json())
}
function renderMeta(d){
 const rep=d.report||{}
 $('#report').innerHTML = rep.ok?'<span class=ok>✓ valid</span>':'<span class=fail>✗ '+(rep.errors||[]).length+' issue(s)</span>'
 $('#stats').textContent = JSON.stringify(rep.stats||{},null,0)+
   ((rep.errors||[]).length?'\\n'+rep.errors.map(e=>'• '+e.human).join('\\n'):'')+
   (d.steps?`\\nsteps: ${d.steps.n_steps}`:'')
 $('#tree').textContent = d.tree||''
}
function render(d){
 $('#tape').innerHTML=''; (d.tape||[]).forEach(addEv); renderMeta(d)
}
fetch('/api/state').then(r=>r.json()).then(render)
</script>
"""


def main():
    port = int(os.environ.get("PORT", 8017))
    print(f"Bricolage Lane B API + console on http://localhost:{port}  "
          f"(PROVIDER={os.environ.get('PROVIDER', 'mock')})")
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()


if __name__ == "__main__":
    main()
