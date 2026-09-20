#!/usr/bin/env bash
# Launch Bricked: the Lane B API (with pipeline C as the designer) + the web app.
#
#   ./run.sh                 pipeline C: concept image -> brief -> real LEGO parts
#                            (needs `claude` and `codex login`; ~6-10 min a model)
#   ENGINE=a ./run.sh        the archived layer-by-layer builder (A)
#   PROVIDER=mock ./run.sh   deterministic + instant (offline, blocky shapes)
#
# Open http://localhost:3000  ·  Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")"

PROVIDER="${PROVIDER:-claude_cli}"   # claude_cli = real models; mock = fast/offline
PORT_API="${PORT_API:-8017}"
PORT_WEB="${PORT_WEB:-3000}"

# --- how to run the backend's Python ------------------------------------------
# uv is the team's default, but not every machine has it. Order: an explicit
# PYTHON, then uv, then a sibling checkout's venv, then whatever python3 has
# numpy — and if none of those can import numpy, say so instead of half-starting.
# bricolage puts ../brickify on sys.path itself, so only the deps matter here.
# Absolute, because the backend is launched from inside bricolage/.
ROOT="$PWD"
has_deps() { [ -x "$1" ] && "$1" -c "import numpy, scipy" >/dev/null 2>&1; }
PY_RUN=(uv run --project ../brickify python)   # the team default
if [ -n "${PYTHON:-}" ]; then
  has_deps "$PYTHON" || { echo "PYTHON=$PYTHON can't import numpy/scipy"; exit 1; }
  PY_RUN=("$PYTHON")
elif ! command -v uv >/dev/null; then
  PY_FOUND=""
  for cand in "$ROOT/../hack-the-north/.venv/bin/python" "$ROOT/.venv/bin/python" \
              "$ROOT/brickify/.venv/bin/python" "$(command -v python3 || true)"; do
    if has_deps "$cand"; then PY_FOUND="$cand"; break; fi
  done
  [ -n "$PY_FOUND" ] || {
    echo "needs uv (https://docs.astral.sh/uv/) or a python with numpy+scipy."
    echo "  point at one:  PYTHON=/path/to/python ./run.sh"
    exit 1
  }
  PY_RUN=("$PY_FOUND")
  echo "▶ no uv — using $PY_FOUND"
fi

# --- web app (first run installs; rebuilds whenever the source changed) --------
if [ ! -d web/node_modules ]; then echo "▶ installing web deps (first run)…"; ( cd web && npm install --no-audit --no-fund && npx playwright install chromium ); fi
if [ ! -f web/.next/BUILD_ID ] || [ -n "$(find web/src web/public -newer web/.next/BUILD_ID -print -quit)" ]; then
  # BRICOLAGE_URL at BUILD time too: next.config.ts bakes the API's port into
  # the bundle for the SSE stream, which bypasses the proxy.
  echo "▶ building web…"; ( cd web && BRICOLAGE_URL="http://127.0.0.1:$PORT_API" npm run build )
fi
echo "▶ frontend  http://localhost:$PORT_WEB"
( cd web && BRICOLAGE_URL="http://127.0.0.1:$PORT_API" PORT="$PORT_WEB" exec npm start ) &
WEB_PID=$!

# --- backend (Lane B), in brickify's Python env (numpy/scipy for C and physics)
echo "▶ backend   PROVIDER=$PROVIDER ENGINE=${ENGINE:-c}   http://localhost:$PORT_API"
( cd bricolage && PROVIDER="$PROVIDER" PORT="$PORT_API" BRICKIFY_WEB="http://localhost:$PORT_WEB" \
    exec "${PY_RUN[@]}" server.py ) &
API_PID=$!

# --- stop both together -------------------------------------------------------
trap 'echo; echo "stopping…"; kill "$API_PID" "$WEB_PID" 2>/dev/null || true; exit 0' INT TERM
echo
echo "  ✓  open  http://localhost:$PORT_WEB     (Ctrl+C to stop)"
echo
wait
