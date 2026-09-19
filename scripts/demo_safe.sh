#!/usr/bin/env bash
#
# The panic button. One command, wifi off, judges watching.
#
#   scripts/demo_safe.sh                    serve demo/canned and keep serving
#   scripts/demo_safe.sh --check            start, verify, stop, exit 0   (what CI runs)
#   scripts/demo_safe.sh demo/canned-rich   serve a different snapshot
#   PORT=8010 scripts/demo_safe.sh          somebody already has 8000
#
# It does four things in this order, and stops at the first one that fails:
#   1. checks the snapshot on disk is internally consistent        (no server, no network)
#   2. starts the API with DEMO_SAFE=1 pointed at that snapshot    (loopback only)
#   3. asks every endpoint a question and scores the answers
#   4. prints what the presenter should see, in demo order
#
# The server process installs demo/netguard, which makes a non-loopback connect raise. So
# "works offline" is enforced by the program rather than promised by a human who once tried it
# with the wifi off.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${ROOT}/.venv/bin/python"
PORT="${PORT:-8000}"
CANNED="${ROOT}/demo/canned"
CHECK_ONLY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --check)  CHECK_ONLY=1 ;;
    --port)   PORT="$2"; shift ;;
    -h|--help) sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)        CANNED="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")" ;;
  esac
  shift
done

if [ ! -x "${PY}" ]; then
  echo "FAIL  no interpreter at ${PY} -- this project runs on its own .venv" >&2
  exit 1
fi

export DEMO_SAFE=1
export DEMO_CANNED="${CANNED}"
export BRICOLAGE_NO_LLM=1
export BRICOLAGE_NETGUARD="${BRICOLAGE_NETGUARD:-1}"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

echo "================================================================"
echo " BRICOLAGE -- DEMO SAFE"
echo " snapshot : ${CANNED}"
echo " port     : ${PORT}     (127.0.0.1 only, network guard on)"
echo "================================================================"
echo
echo "[1/4] snapshot on disk"
if ! "${PY}" -m demo.check "${CANNED}"; then
  echo
  echo "FAIL  that snapshot is not usable. Regenerate it:"
  echo "        ${PY} -m demo.snapshot --out ${CANNED}"
  exit 1
fi

echo
echo "[2/4] starting the API (DEMO_SAFE=1, no LLM, no network)"
# Somebody else's server on this port is the nastiest failure this script can have: uvicorn
# fails to bind, the health check passes against the stranger, and every later check disagrees
# with the snapshot for reasons that look like our bug. Refuse up front instead.
if "${PY}" -c "
import socket, sys
s = socket.socket()
s.settimeout(0.5)
sys.exit(0 if s.connect_ex(('127.0.0.1', ${PORT})) == 0 else 1)
" 2>/dev/null; then
  echo "FAIL  something is already listening on 127.0.0.1:${PORT}." >&2
  echo "      Stop it, or re-run as:  PORT=8010 ${BASH_SOURCE[0]}" >&2
  exit 1
fi

LOG="$(mktemp -t bricolage_demo_safe)"
"${PY}" -m uvicorn demo.serve:app --host 127.0.0.1 --port "${PORT}" \
        --log-level warning >"${LOG}" 2>&1 &
SERVER_PID=$!

cleanup() {
  if kill -0 "${SERVER_PID}" 2>/dev/null; then
    kill "${SERVER_PID}" 2>/dev/null || true
    wait "${SERVER_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# Give it a moment to bind, and say something useful if it died instead.
for _ in $(seq 1 100); do
  if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
    echo "FAIL  the server exited. Its output:" >&2
    cat "${LOG}" >&2
    exit 1
  fi
  if "${PY}" -c "
import sys, urllib.request
try:
    urllib.request.urlopen('http://127.0.0.1:${PORT}/health', timeout=1).read()
except Exception:
    sys.exit(1)
" 2>/dev/null; then
    break
  fi
  sleep 0.2
done
echo "      up on http://127.0.0.1:${PORT}  (pid ${SERVER_PID})"

echo
echo "[3/4] every endpoint answers"
if ! "${PY}" -m demo.verify --port "${PORT}" --canned "${CANNED}"; then
  echo
  echo "FAIL  the server is up but something it serves is wrong. Server log:" >&2
  cat "${LOG}" >&2
  exit 1
fi

echo
echo "[4/4] what the presenter should see"
"${PY}" - "${CANNED}" "${PORT}" <<'PYCODE'
import json, pathlib, sys

canned, port = pathlib.Path(sys.argv[1]), sys.argv[2]
meta = json.loads((canned / "meta.json").read_text())
counts, check = meta.get("counts", {}), meta.get("check", {})
base = f"http://127.0.0.1:{port}"

print(f"""
  0:00  the bin in your hand           {counts.get('inventory_rows','?')} rows from {meta.get('inventory_source')}
  0:15  the inventory fills            {base}/inventory
        click an amber row             needs_review rows carry a crop box + alternatives
  0:50  the agent tape streams         {base}/builds/<id>/events   ({counts.get('tape_events','?')} events)
        designer -> INSPECTOR -> repair   the inspector is code, not a model
  1:40  the manual                     {base}/demo/manual/manual.html   ({counts.get('steps','?')} steps)
        the printed PDF                {base}/demo/manual/manual.pdf
  2:15  the edit                       POST {base}/builds/<id>/edit  "make the chassis longer"
  2:40  the model you built            on the table, next to the laptop

  model    {counts.get('parts','?')} parts, {counts.get('steps','?')} steps, validated clean
  ask      {meta.get('prompt')!r}  seed={meta.get('seed')}  git={meta.get('git')}
  frozen   {meta.get('generated')}""")

for w in check.get("warnings", []):
    print(f"  WARN     {w}")
print()
PYCODE

if [ "${CHECK_ONLY}" = "1" ]; then
  echo "--check: everything passed. Stopping the server."
  exit 0
fi

echo "Serving. Ctrl-C to stop."
echo "  API    http://127.0.0.1:${PORT}/docs"
echo "  manual http://127.0.0.1:${PORT}/demo/manual/manual.html"
wait "${SERVER_PID}"
