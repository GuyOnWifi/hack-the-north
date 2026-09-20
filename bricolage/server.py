"""Zero-dependency HTTP API over the session (the seam to the frontend lane).
stdlib only, so it runs under DEMO_SAFE with wifi off.

  POST /api/build        {prompt}      -> {version, report, steps, tape, tree}
  POST /api/edit         {text}        -> {version, report, tape?, tree}
  POST /api/choose       {index|null, note?} -> {ok}   (pick a candidate design mid-run)
  POST /api/try_another  {}            -> {version, report, tree}
  POST /api/undo|redo    {}            -> {version, report, tree}
  GET  /api/library                    -> {models:[...]}  every model designed here
  GET  /api/library/thumb?id=           -> png of that model
  POST /api/open         {id}           -> make a saved model the current one
  GET  /api/state                      -> current build/report/steps
  GET  /api/ldr                        -> current model as text/plain LDraw
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
from serialize import build_json, report_json
from ldraw import to_ldr
import engine_c

# Designs are never limited by a real bin: the app asks for an idea, the
# designer builds it.
SESSION = Session(Inventory({}, unlimited=True))


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
        if u.path == "/api/ldr":
            v = SESSION.versions.get(SESSION.head)
            if v and engine_c.is_c(v.build):  # pipeline C writes its own LDraw, steps included
                return self._send(200, v.build.provenance["ldr"], "text/plain")
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
            prompt = parse_qs(u.query).get("prompt", ["build a rover"])[0]
            return self._stream_build(prompt)
        if u.path == "/api/compare":
            # split-screen: 'LLM places bricks' (floats/topples) vs our solver
            from pipeline import compare
            prompt = parse_qs(u.query).get("prompt", ["build me a flower"])[0]
            return self._send(200, compare(prompt, SESSION.inv))
        self._send(404, {"error": "not found"})

    def _stream_build(self, prompt):
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
            SESSION.build(prompt, tape=tape)
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

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or "{}") if n else {}
        try:
            if self.path == "/api/build":
                SESSION.build(body.get("prompt", "build a rover"))
            elif self.path == "/api/edit":
                SESSION.edit(body.get("text", ""))
            elif self.path == "/api/open":
                # bring a saved model back as the current one
                b = engine_c.open_run(body.get("id", ""))
                SESSION._commit(None, {"kind": "build", "prompt": b.name, "seed": 0, "recipe": engine_c.recipe(b)},
                                b, engine_c.report(b))
            elif self.path == "/api/choose":
                # which of the candidate designs to keep (null = let the critic)
                engine_c.choose(body.get("index"), body.get("note", ""))
                return self._send(200, {"ok": True})
            elif self.path == "/api/try_another":
                SESSION.try_another()
            elif self.path == "/api/undo":
                SESSION.undo()
            elif self.path == "/api/redo":
                SESSION.redo()
            else:
                return self._send(404, {"error": "not found"})
        except Exception as e:
            return self._send(500, {"error": str(e)})
        self._send(200, _payload())


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
