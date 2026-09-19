"""API tests. Every endpoint gets at least one, and DEMO_SAFE gets its own.

These run with no network and no API key, which is the same condition the demo runs in. The LLM
seam is exercised with a stub module injected into `sys.modules` -- that proves the lazy import
actually works without depending on a package another lane is still writing.
"""

from __future__ import annotations

import json
import pathlib
import sys
import time
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient

from api import engine
from api.main import create_app

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def env(monkeypatch):
    """Default test environment: no demo mode, no LLM, a short wall-clock budget."""
    monkeypatch.setenv("DEMO_SAFE", "0")
    monkeypatch.setenv("BRICOLAGE_NO_LLM", "1")
    return monkeypatch


@pytest.fixture
def client(env):
    # The context manager form runs the lifespan and keeps one event loop alive, which is what
    # lets the background build task make progress between requests.
    with TestClient(create_app()) as c:
        yield c


def fixture_items() -> list[dict]:
    return json.loads((FIXTURES / "inventory.json").read_text())["items"]


def new_session(client, items=None) -> str:
    r = client.post("/sessions", json={"items": items if items is not None else fixture_items()})
    assert r.status_code == 201
    return r.json()["session_id"]


def wait_for(client, build_id: str, timeout: float = 20.0) -> dict:
    """Poll until the async job settles. Builds take milliseconds; the timeout is for a hang."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/builds/{build_id}").json()
        if body["status"] != "running":
            return body
        time.sleep(0.02)
    raise AssertionError(f"build {build_id} never finished")


# ---------------------------------------------------------------- meta + sessions


def test_health(client):
    body = client.get("/health").json()
    assert body["ok"] is True
    assert body["demo_safe"] is False
    assert body["llm"] is False
    assert "chassis" in body["generators"]


def test_create_session_empty(client):
    body = client.post("/sessions", json={"items": []}).json()
    assert body["session_id"].startswith("ses_")
    assert body["totals"] == {"pieces": 0, "distinct": 0, "unknown": 0}


def test_read_session_and_404(client):
    sid = new_session(client)
    assert client.get(f"/sessions/{sid}").json()["session_id"] == sid
    assert client.get("/sessions/ses_nope").status_code == 404


# ---------------------------------------------------------------- inventory


def test_inventory_crud(client):
    sid = new_session(client, items=[])
    h = {"X-Session-Id": sid}

    r = client.post("/inventory/items", json={"part": "3001", "color": 4, "qty": 6}, headers=h)
    assert r.status_code == 201
    item_id = r.json()["id"]

    # same element again is a quantity change, not a second row
    client.post("/inventory/items", json={"part": "3001", "color": 4, "qty": 2}, headers=h)
    inv = client.get("/inventory", headers=h).json()
    assert inv["totals"] == {"pieces": 8, "distinct": 1, "unknown": 0}

    assert client.patch(f"/inventory/items/{item_id}", json={"qty": 3},
                        headers=h).json()["qty"] == 3
    assert client.patch("/inventory/items/inv_999", json={"qty": 1}, headers=h).status_code == 404

    assert client.delete(f"/inventory/items/{item_id}", headers=h).status_code == 200
    assert client.delete(f"/inventory/items/{item_id}", headers=h).status_code == 404
    assert client.get("/inventory", headers=h).json()["items"] == []


def test_inventory_bulk_replace_and_clear(client):
    sid = new_session(client, items=[])
    h = {"X-Session-Id": sid}
    body = client.post("/inventory", json={"items": [{"part": "3024", "color": 4, "qty": 5},
                                                     {"part": "3005", "color": 15, "qty": 2}],
                                           "color_mode": "exact"}, headers=h).json()
    assert body["totals"]["pieces"] == 7
    assert body["color_mode"] == "exact"
    assert client.delete("/inventory", headers=h).json()["items"] == []


def test_unknown_rows_are_excluded_from_the_solver(client):
    sid = new_session(client, items=[])
    h = {"X-Session-Id": sid}
    client.post("/inventory/items", json={"part": "3001", "color": 4, "qty": 4}, headers=h)
    client.post("/inventory/items", json={"part": "3003", "color": 4, "qty": 9,
                                          "status": "unknown"}, headers=h)
    totals = client.get("/inventory", headers=h).json()["totals"]
    assert totals["pieces"] == 13 and totals["unknown"] == 9

    store = client.app.state.store
    assert store.session(sid).inventory().total == 4          # Contract 1


def test_unknown_session_is_404(client):
    assert client.get("/inventory", headers={"X-Session-Id": "ses_nope"}).status_code == 404


def test_import_set_is_an_honest_stub(client):
    sid = new_session(client, items=[])
    r = client.post("/inventory/import-set", json={"set_num": "42100"},
                    headers={"X-Session-Id": sid})
    assert r.status_code == 501
    assert "data/sets/42100.json" in r.json()["detail"]["human"]


def test_import_set_reads_a_local_file(client, tmp_path, monkeypatch):
    from api.routes import inventory as inv_routes

    monkeypatch.setattr(inv_routes, "SETS_DIR", tmp_path)
    (tmp_path / "9999.json").write_text(json.dumps([{"part": "3001", "color": 4, "qty": 3}]))
    sid = new_session(client, items=[])
    r = client.post("/inventory/import-set", json={"set_num": "9999"},
                    headers={"X-Session-Id": sid})
    assert r.json()["imported"] == 1
    assert r.json()["totals"]["pieces"] == 3


# ---------------------------------------------------------------- builds


def test_build_end_to_end(client):
    sid = new_session(client)
    h = {"X-Session-Id": sid}
    r = client.post("/builds", json={"prompt": "build me a desk rover", "seed": 41}, headers=h)
    assert r.status_code == 202
    bid = r.json()["build_id"]

    body = wait_for(client, bid)
    assert body["status"] == "ok"
    assert body["steps_ready"] is True
    assert body["version"] == 1
    assert body["build"]["parts"]

    # invariant 1 survives the trip to the wire: integers only, right-angle rotations only
    for p in body["build"]["parts"]:
        assert all(isinstance(v, int) for v in p["pos"])
        assert p["rot"] in (0, 90, 180, 270)

    val = client.get(f"/builds/{bid}/validation").json()
    assert set(val) == {"ok", "errors", "warnings", "stats"}
    assert val == body["validation"]

    steps = client.get(f"/builds/{bid}/steps").json()
    assert steps["total"] == len(steps["steps"]) > 0
    assert steps["steps"][0]["callout"][0]["name"]

    ldr = client.get(f"/builds/{bid}/model.ldr")
    assert ldr.headers["content-type"].startswith("text/plain")
    assert ldr.text.count("0 STEP") == steps["total"]

    versions = client.get(f"/builds/{bid}/versions").json()
    assert versions["head"] == 1 and versions["versions"][0]["op"]["kind"] == "generate"


def test_build_404s(client):
    assert client.get("/builds/bld_nope").status_code == 404
    assert client.get("/builds/bld_nope/steps").status_code == 404


def test_events_are_contract_4(client):
    sid = new_session(client)
    bid = client.post("/builds", json={"prompt": "a small tower"},
                      headers={"X-Session-Id": sid}).json()["build_id"]
    wait_for(client, bid)

    with client.stream("GET", f"/builds/{bid}/events") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        payloads = [line[6:] for line in r.iter_lines() if line.startswith("data: ")]

    events = [json.loads(p) for p in payloads]
    assert events, "the tape must replay from the top for a client that connects late"
    tail = events[-1]
    assert tail["status"] == "ok"                       # the `event: done` frame
    for ev in events[:-1]:
        assert ev["actor"] in {"designer", "inspector", "repair", "scribe", "cataloguer"}
        assert ev["status"] in {"ok", "fail", "warn", "running"}
        assert isinstance(ev["t"], int) and ev["text"]
    assert {e["actor"] for e in events[:-1]} >= {"cataloguer", "designer", "inspector"}


def test_idempotency_key_does_not_start_two_builds(client):
    sid = new_session(client)
    h = {"X-Session-Id": sid, "Idempotency-Key": "demo-tap-1"}
    first = client.post("/builds", json={"prompt": "a rover"}, headers=h).json()["build_id"]
    second = client.post("/builds", json={"prompt": "a rover"}, headers=h).json()
    assert second["build_id"] == first and second["idempotent"] is True
    wait_for(client, first)
    assert len(client.app.state.store.builds) == 1


def test_small_bin_is_refused_with_a_sentence(client):
    sid = new_session(client, items=[{"part": "3024", "color": 4, "qty": 6},
                                     {"part": "3005", "color": 4, "qty": 3}])
    bid = client.post("/builds", json={"prompt": "a rover"},
                      headers={"X-Session-Id": sid}).json()["build_id"]
    body = wait_for(client, bid)
    assert body["status"] == "failed"
    assert "usable bricks" in body["human"]
    assert body["build"] is None
    # and it is a refusal, not a crash: the tape says so and the steps endpoint 409s
    assert client.get(f"/builds/{bid}/steps").status_code == 409


# ---------------------------------------------------------------- the edit loop


def _rover(client) -> tuple[str, str]:
    sid = new_session(client)
    bid = client.post("/builds", json={"prompt": "a desk rover", "seed": 41},
                      headers={"X-Session-Id": sid}).json()["build_id"]
    wait_for(client, bid)
    return sid, bid


def _extent(body: dict, sub: str) -> int:
    """How far a subassembly reaches along X, in studs. Needs the part metadata, not just pos."""
    from core import meta

    spans = []
    for p in body["build"]["parts"]:
        if p["sub"] != sub:
            continue
        w, _d = meta.get(p["part"]).footprint(p["rot"])
        spans.append(p["pos"][0] + w)
    return max(spans)


def test_edit_makes_the_chassis_longer(client):
    sid, bid = _rover(client)
    before = client.get(f"/builds/{bid}").json()
    r = client.post(f"/builds/{bid}/edit", json={"instruction": "make the chassis longer"},
                    headers={"X-Session-Id": sid})
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == 2 and body["can_undo"] is True
    assert "chassis.length" in body["summary"]

    after = client.get(f"/builds/{bid}").json()
    # Part COUNT is the wrong assertion -- a longer chassis built from longer bricks can use
    # the same number of pieces. Footprint is the thing the user asked to change.
    assert _extent(after, "chassis") > _extent(before, "chassis")
    assert after["version"] == 2
    assert after["validation"]["ok"] is True


def test_edit_recolor_and_remove(client):
    sid, bid = _rover(client)
    h = {"X-Session-Id": sid}
    r = client.post(f"/builds/{bid}/edit", json={"instruction": "make the cabin white"},
                    headers=h).json()
    assert "15" in r["summary"]
    colors = {p["color"] for p in client.get(f"/builds/{bid}").json()["build"]["parts"]
              if p["sub"] == "cabin"}
    # 15, plus whatever the allocator had to substitute -- colour is a hint, not a constraint
    # (Contract 1), so the assertion is "it asked for white and got some", not "all white".
    assert 15 in colors

    r = client.post(f"/builds/{bid}/edit", json={"instruction": "remove the cabin"},
                    headers=h).json()
    assert r["applied"] is True
    subs = {p["sub"] for p in client.get(f"/builds/{bid}").json()["build"]["parts"]}
    assert "cabin" not in subs


def test_edit_it_cannot_do_says_what_it_can(client):
    sid, bid = _rover(client)
    r = client.post(f"/builds/{bid}/edit", json={"instruction": "make it look like a dragon"},
                    headers={"X-Session-Id": sid})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "EDIT_NOT_UNDERSTOOD"
    assert "chassis" in detail["human"] and "chassis" in detail["nodes"]


def test_undo_redo_is_a_pointer_move(client):
    sid, bid = _rover(client)
    h = {"X-Session-Id": sid}
    v1_parts = len(client.get(f"/builds/{bid}").json()["build"]["parts"])
    client.post(f"/builds/{bid}/edit", json={"instruction": "make the chassis longer"}, headers=h)
    v2_parts = len(client.get(f"/builds/{bid}").json()["build"]["parts"])

    assert client.post(f"/builds/{bid}/undo").json()["version"] == 1
    assert len(client.get(f"/builds/{bid}").json()["build"]["parts"]) == v1_parts

    assert client.post(f"/builds/{bid}/undo").json() == {
        "build_id": bid, "applied": False, "human": "Nothing to undo -- this is the first version.",
        "version": 1, "can_undo": False, "can_redo": True}

    assert client.post(f"/builds/{bid}/redo").json()["version"] == 2
    assert len(client.get(f"/builds/{bid}").json()["build"]["parts"]) == v2_parts
    assert client.post(f"/builds/{bid}/redo").json()["applied"] is False


def test_edit_before_the_build_finishes_is_409(client):
    sid = new_session(client)
    store = client.app.state.store
    rec = store.create_build(sid, "a rover", "compose", 41)     # never started
    r = client.post(f"/builds/{rec.id}/edit", json={"instruction": "make it longer"})
    assert r.status_code == 409


# ---------------------------------------------------------------- DEMO_SAFE


@pytest.fixture
def demo_client(monkeypatch):
    monkeypatch.setenv("DEMO_SAFE", "1")
    monkeypatch.delenv("BRICOLAGE_NO_LLM", raising=False)
    with TestClient(create_app()) as c:
        yield c


def test_demo_safe_serves_everything_from_fixtures(demo_client, monkeypatch):
    # Prove it: any attempt to reach the LLM lane in this mode is a test failure.
    def explode(*_a, **_k):
        raise AssertionError("DEMO_SAFE must not touch the LLM")

    monkeypatch.setattr(engine, "plan", explode)
    assert engine._llm_module() is None

    health = demo_client.get("/health").json()
    assert health["demo_safe"] is True and health["llm"] is False

    sid = demo_client.post("/sessions", json={}).json()["session_id"]
    inv = demo_client.get("/inventory", headers={"X-Session-Id": sid}).json()
    fixture_totals = json.loads((FIXTURES / "inventory.json").read_text())["totals"]
    assert inv["totals"]["pieces"] == fixture_totals["pieces"]

    bid = demo_client.post("/builds", json={"prompt": "a desk rover"},
                           headers={"X-Session-Id": sid}).json()["build_id"]
    body = wait_for(demo_client, bid)
    assert body["status"] == "ok" and body["steps_ready"] is True

    fixture_build = json.loads((FIXTURES / "build.json").read_text())
    # NOT byte-equality: the loader deliberately translates ids across the lane seam
    # ("3023" -> LDraw "3023b", see core.meta.resolve_id) and skips parts we have no geometry
    # for (e.g. 4073) rather than dying on them. What must hold is that every part we DID load
    # kept its identity and position.
    served = {p["id"]: p for p in body["build"]["parts"]}
    fixture = {p["id"]: p for p in fixture_build["parts"]}
    assert served, "demo-safe served an empty build"
    assert set(served) <= set(fixture), "served a part that is not in the fixture"
    for pid, sp in served.items():
        fp = fixture[pid]
        assert sp["pos"] == fp["pos"] and sp["rot"] == fp["rot"] and sp["color"] == fp["color"]
        assert sp["part"] in (fp["part"], f'{fp["part"]}a', f'{fp["part"]}b'), (
            f'{pid}: {sp["part"]} is not a variant of {fp["part"]}')

    # Compare SEMANTICALLY, not byte-for-byte. fixtures/ is a seam between two lanes: the build
    # lane writes `"sub": null` where our serializer omits the key entirely, and both mean "no
    # subassembly". Asserting exact equality across that seam breaks every time the other lane
    # changes a null convention, which is noise, not a regression.
    def drop_nulls(x):
        if isinstance(x, dict):
            return {k: drop_nulls(v) for k, v in x.items() if v is not None}
        if isinstance(x, list):
            return [drop_nulls(v) for v in x]
        return x

    assert drop_nulls(body["validation"]) == \
        drop_nulls(json.loads((FIXTURES / "report.json").read_text()))

    served_steps = demo_client.get(f"/builds/{bid}/steps").json()
    fixture_steps = json.loads((FIXTURES / "steps.json").read_text())
    assert len(served_steps["steps"]) == len(fixture_steps["steps"])
    # Again structural, not byte-equal: our writer emits its own header and omits the parts we
    # have no geometry for, so an exact match would only ever assert "the other lane has not
    # touched its fixture". What matters is that it is a valid, steppable LDraw file.
    ldr = demo_client.get(f"/builds/{bid}/model.ldr").text
    refs = [ln for ln in ldr.splitlines() if ln.startswith("1 ")]
    assert len(refs) == len(body["build"]["parts"]), "every loaded part must reach the .ldr"
    assert ldr.count("0 STEP") == len(served_steps["steps"])
    assert all(ln.split()[-1].endswith(".dat") for ln in refs)

    tape = [json.loads(line) for line in (FIXTURES / "tape.jsonl").read_text().splitlines()]
    assert demo_client.app.state.store.build(bid).events == tape


def test_demo_safe_still_edits(demo_client):
    """An edit in demo mode re-runs the generators locally -- still zero network, zero LLM."""
    sid = demo_client.post("/sessions", json={}).json()["session_id"]
    bid = demo_client.post("/builds", json={"prompt": "a desk rover"},
                           headers={"X-Session-Id": sid}).json()["build_id"]
    wait_for(demo_client, bid)
    r = demo_client.post(f"/builds/{bid}/edit", json={"instruction": "make the chassis longer"},
                         headers={"X-Session-Id": sid})
    assert r.status_code == 200 and r.json()["version"] == 2


def test_demo_safe_import_set_falls_back_to_the_fixture_bin(demo_client):
    sid = demo_client.post("/sessions", json={"items": []}).json()["session_id"]
    r = demo_client.post("/inventory/import-set", json={"set_num": "42100"},
                         headers={"X-Session-Id": sid}).json()
    assert r["source"] == "fixtures" and r["imported"] > 0


# ---------------------------------------------------------------- the LLM seam


def _stub_llm(monkeypatch, **fns) -> types.ModuleType:
    """Install a fake `api.llm` for one test.

    Both halves are needed: `sys.modules` for a fresh import, and the attribute on the `api`
    package for the case where something else in the suite already imported the real module --
    `from api import llm` then reads the attribute and never looks at sys.modules again.
    """
    import api

    mod = types.ModuleType("api.llm")
    for name, fn in fns.items():
        setattr(mod, name, fn)
    monkeypatch.setenv("BRICOLAGE_NO_LLM", "0")
    monkeypatch.setitem(sys.modules, "api.llm", mod)
    monkeypatch.setattr(api, "llm", mod, raising=False)
    return mod


def test_llm_is_used_when_the_lane_exists(client, monkeypatch):
    seen = {}

    def propose(**kw):
        seen.update(kw)
        return {"root": "tower", "nodes": [{"id": "tower", "gen": "tower",
                                            "args": {"height": 9, "size": 3}, "color": 4}]}

    _stub_llm(monkeypatch, propose=propose)
    sid = new_session(client)
    bid = client.post("/builds", json={"prompt": "a lookout"},
                      headers={"X-Session-Id": sid}).json()["build_id"]
    body = wait_for(client, bid)

    assert body["status"] == "ok"
    assert {p["sub"] for p in body["build"]["parts"]} == {"tower"}
    assert "catalog" in seen and "chassis(" in seen["catalog"]     # it gets the catalogue
    assert seen["prompt"] == "a lookout"


def test_a_dead_llm_degrades_to_the_offline_planner(client, monkeypatch):
    def propose(**_kw):
        raise RuntimeError("connection refused")

    _stub_llm(monkeypatch, propose=propose)
    sid = new_session(client)
    bid = client.post("/builds", json={"prompt": "a rover"},
                      headers={"X-Session-Id": sid}).json()["build_id"]
    body = wait_for(client, bid)

    assert body["status"] == "ok"                       # degraded, not failed
    events = client.app.state.store.build(bid).events
    assert any(e["kind"] == "degrade" and "offline planner" in e["text"] for e in events)


def test_llm_edit_is_used_when_present(client, monkeypatch):
    def edit(**kw):
        comp = kw["composition"]
        comp["nodes"][0]["args"]["length"] = 14
        return comp

    sid, bid = _rover(client)
    _stub_llm(monkeypatch, edit=edit)
    r = client.post(f"/builds/{bid}/edit", json={"instruction": "anything at all"},
                    headers={"X-Session-Id": sid}).json()
    assert r["version"] == 2
    head = client.app.state.store.build(bid).tree.current()
    assert head.op.args["composition"]["nodes"][0]["args"]["length"] == 14
    assert head.op.args["source"] == "llm"


# ---------------------------------------------------------------- planner determinism


def test_offline_planner_is_deterministic(client):
    from core.model import Inventory

    inv = Inventory.from_pairs([("3001", 4, 30), ("3003", 4, 10), ("3024", 15, 20)])
    a = engine.offline_plan("a rover", inv, seed=41)
    b = engine.offline_plan("a rover", inv, seed=41)
    c = engine.offline_plan("a rover", inv, seed=42)
    assert engine.comp_to_dict(a) == engine.comp_to_dict(b)
    assert engine.comp_to_dict(a) != engine.comp_to_dict(c)      # "try another" must differ
    assert engine.comp_to_dict(a)["nodes"][0]["color"] == 4      # the bin's main colour


def test_planner_never_emits_a_coordinate(client):
    """Invariant 4, asserted rather than hoped for."""
    from core.model import Inventory

    inv = Inventory.from_pairs([("3001", 4, 20), ("3024", 15, 40)])
    for prompt in ("a rover", "a tall tower", "a wall", "a small house", "a jet"):
        comp = engine.offline_plan(prompt, inv, seed=7)
        for node in comp.nodes:
            assert not {"pos", "x", "y", "z", "at_xyz"} & set(node.get("args") or {})


# ---------------------------------------------------------------- the real build-system lane


@pytest.fixture
def live_client(monkeypatch):
    """No demo mode, no LLM block, and no API key -- the lane's own offline stub must carry it."""
    monkeypatch.setenv("DEMO_SAFE", "0")
    monkeypatch.delenv("BRICOLAGE_NO_LLM", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with TestClient(create_app()) as c:
        yield c


def test_the_real_fix_loop_is_delegated_to_when_it_exists(live_client):
    """When api/llm ships `build_with_fixes`, the API hands it the whole job and keeps its tape."""
    llm = pytest.importorskip("api.llm")
    if not hasattr(llm, "build_with_fixes"):
        pytest.skip("the build-system lane has no build_with_fixes yet")

    sid = new_session(live_client)
    bid = live_client.post("/builds", json={"prompt": "a desk rover", "seed": 41},
                           headers={"X-Session-Id": sid}).json()["build_id"]
    body = wait_for(live_client, bid)

    assert body["status"] == "ok" and body["build"]["parts"]
    head = live_client.app.state.store.build(bid).tree.current()
    assert head.op.args["source"] == "llm_loop"
    assert head.op.args["composition"]                     # the recipe came back, so edits work

    events = live_client.app.state.store.build(bid).events
    assert events, "the lane's tape must reach the SSE stream"
    for ev in events:
        assert ev["actor"] in {"designer", "inspector", "repair", "scribe", "cataloguer"}
        assert ev["status"] in {"ok", "fail", "warn", "running"}

    r = live_client.post(f"/builds/{bid}/edit", json={"instruction": "make the chassis longer"},
                         headers={"X-Session-Id": sid})
    assert r.status_code == 200 and r.json()["version"] == 2
