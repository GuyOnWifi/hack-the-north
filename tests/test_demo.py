"""The demo package: the canned snapshot, the offline guard, and the one command.

These tests are the reason anyone can trust `scripts/demo_safe.sh` at the judging table. They
assert three things and nothing else:

  1. the snapshot in `demo/canned/` is internally consistent -- the steps reference only parts
     in the build, and the build uses only parts the bin actually has;
  2. `demo.netguard` really does stop a non-loopback connection, so "no network" is a property
     of the program rather than a claim about the room;
  3. `scripts/demo_safe.sh --check` exits 0 end to end, with the guard installed, which means
     the server it starts could not have reached the internet even if it wanted to.

The last one starts a real uvicorn in a subprocess, because `TestClient` would prove the app
object works and the question is whether the thing on a port works.
"""

from __future__ import annotations

import json
import pathlib
import socket
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest

from demo import netguard
from demo.check import check_snapshot
from demo.snapshot import run_once

ROOT = pathlib.Path(__file__).resolve().parents[1]
CANNED = ROOT / "demo" / "canned"
SCRIPT = ROOT / "scripts" / "demo_safe.sh"

pytestmark = pytest.mark.skipif(not CANNED.is_dir(),
                                reason="no snapshot yet -- run python -m demo.snapshot")


@pytest.fixture(scope="module")
def snap() -> dict:
    return {p.stem: json.loads(p.read_text()) for p in CANNED.glob("*.json")}


# ---------------------------------------------------------------- the snapshot


def test_canned_snapshot_passes_its_own_checker():
    r = check_snapshot(CANNED)
    assert r.ok, "\n".join(r.errors)


def test_steps_reference_only_parts_in_the_build(snap):
    """A step calling for a part the model does not contain is a manual nobody can follow."""
    build_ids = {p["id"] for p in snap["build"]["parts"]}
    step_ids = [p["id"] for s in snap["steps"]["steps"] for p in s["parts"]]
    assert set(step_ids) <= build_ids
    assert set(step_ids) == build_ids, "some part of the model is never built"
    assert len(step_ids) == len(set(step_ids)), "a part is placed in two different steps"


def test_build_uses_only_parts_in_the_inventory(snap):
    """The whole product promise, as an assertion. Colour may be substituted; a part may not."""
    pooled: dict[str, int] = {}
    for item in snap["inventory"]["items"]:
        if item.get("status") == "unknown":              # Contract 1: not offered to the solver
            continue
        pooled[str(item["part"])] = pooled.get(str(item["part"]), 0) + int(item.get("qty", 1))

    used: dict[str, int] = {}
    for p in snap["build"]["parts"]:
        used[str(p["part"])] = used.get(str(p["part"]), 0) + 1

    for part, n in used.items():
        assert pooled.get(part, 0) >= n, \
            f"the build places {n}x {part} and the bin has {pooled.get(part, 0)}"


def test_snapshot_holds_invariant_1(snap):
    for p in snap["build"]["parts"]:
        assert all(isinstance(v, int) and not isinstance(v, bool) for v in p["pos"])
        assert p["rot"] in (0, 90, 180, 270)


def test_tape_is_contract_4_shaped():
    """The tape is the demo's best artifact; a malformed event is a blank panel on stage."""
    events = [json.loads(x) for x in (CANNED / "tape.jsonl").read_text().splitlines()
              if x.strip()]
    assert events, "empty tape"
    for e in events:
        assert isinstance(e["t"], int)
        assert e["actor"] in {"designer", "inspector", "repair", "scribe", "cataloguer"}
        assert e["status"] in {"ok", "fail", "warn", "running"}
        assert isinstance(e["text"], str) and e["text"]
    assert any(e["actor"] == "inspector" for e in events)


def test_ldr_matches_the_build(snap):
    ldr = (CANNED / "model.ldr").read_text()
    assert sum(1 for line in ldr.splitlines() if line.startswith("1 ")) == \
        len(snap["build"]["parts"])


def test_the_checker_rejects_a_broken_snapshot(tmp_path, snap):
    """A checker that cannot fail is decoration. Break the snapshot and watch it notice."""
    broken = tmp_path / "canned"
    broken.mkdir()
    for p in CANNED.iterdir():
        if p.is_file():
            (broken / p.name).write_bytes(p.read_bytes())
    steps = json.loads((broken / "steps.json").read_text())
    steps["steps"][0]["parts"][0]["id"] = "p_does_not_exist"
    (broken / "steps.json").write_text(json.dumps(steps))

    r = check_snapshot(broken, expect_render=False)
    assert not r.ok
    assert any("not in the build" in e for e in r.errors)


def test_snapshot_meta_records_what_a_presenter_needs():
    meta = json.loads((CANNED / "meta.json").read_text())
    for key in ("prompt", "seed", "inventory_source", "generated", "counts", "check"):
        assert key in meta, f"meta.json has no {key}"
    assert meta["counts"]["parts"] > 0


# ---------------------------------------------------------------- determinism


def test_the_same_bin_and_seed_snapshot_identically(monkeypatch):
    """Invariant 6. If this fails, every canned artifact is a coin flip and undo is a lie."""
    monkeypatch.setenv("DEMO_SAFE", "0")
    monkeypatch.delenv("BRICOLAGE_NO_LLM", raising=False)
    items = json.loads((CANNED / "inventory.json").read_text())["items"]

    a = run_once(items, "build me a rover", 41)
    b = run_once(items, "build me a rover", 41)

    assert a.build == b.build
    assert a.steps == b.steps
    assert a.ldr == b.ldr
    assert a.report == b.report
    # Timings are wall clock and are the one thing allowed to differ between two runs.
    assert [(e["actor"], e["kind"], e["text"]) for e in a.tape] == \
           [(e["actor"], e["kind"], e["text"]) for e in b.tape]


# ---------------------------------------------------------------- the offline guard


@pytest.fixture
def guard():
    netguard.install()
    try:
        yield netguard
    finally:
        netguard.uninstall()


def test_netguard_blocks_the_internet(guard):
    s = socket.socket()
    s.settimeout(1.0)
    with pytest.raises(netguard.OfflineError):
        s.connect(("1.1.1.1", 80))
    assert s.connect_ex(("1.1.1.1", 80)) != 0
    s.close()


def test_netguard_leaves_loopback_alone(guard):
    """The presenter's browser and demo/verify both talk over loopback; blocking it is useless."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    client = socket.socket()
    client.settimeout(2.0)
    try:
        client.connect(("127.0.0.1", port))          # must not raise
    finally:
        client.close()
        server.close()


def test_netguard_uninstalls_cleanly():
    netguard.install()
    netguard.uninstall()
    assert not netguard.installed()
    assert netguard.is_local(("127.0.0.1", 8000)) and not netguard.is_local(("8.8.8.8", 53))


# ---------------------------------------------------------------- the one command


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.mark.skipif(not SCRIPT.exists(), reason="scripts/demo_safe.sh missing")
def test_demo_safe_sh_passes_end_to_end():
    """Starts a real uvicorn with the network guard on, scores every endpoint, exits 0."""
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(pathlib.Path.home()),
           "PORT": str(free_port()), "BRICOLAGE_NETGUARD": "1"}
    proc = subprocess.run(["bash", str(SCRIPT), "--check"], cwd=str(ROOT), env=env,
                          capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "0 failed" in proc.stdout
    # The checklist is the deliverable, not a side effect: if these lines stop printing, the
    # presenter is reading a blank terminal three minutes before going on.
    for beat in ("0:15", "0:50", "1:40", "2:15", "2:40"):
        assert beat in proc.stdout
