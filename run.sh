#!/usr/bin/env bash
# Launch BrickedUp: the Lane B API (with pipeline C as the designer) + the web app.
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
command -v uv >/dev/null || { echo "needs uv: https://docs.astral.sh/uv/"; exit 1; }

# --- web app (first run installs; rebuilds whenever the source changed) --------
if [ ! -d web/node_modules ]; then echo "▶ installing web deps (first run)…"; ( cd web && npm install --no-audit --no-fund && npx playwright install chromium ); fi
if [ ! -f web/.next/BUILD_ID ] || [ -n "$(find web/src web/public -newer web/.next/BUILD_ID -print -quit)" ]; then
  echo "▶ building web…"; ( cd web && npm run build )
fi
echo "▶ frontend  http://localhost:$PORT_WEB"
( cd web && BRICOLAGE_URL="http://127.0.0.1:$PORT_API" PORT="$PORT_WEB" exec npm start ) &
WEB_PID=$!

# --- backend (Lane B), in brickify's Python env (numpy/scipy for C and physics)
echo "▶ backend   PROVIDER=$PROVIDER ENGINE=${ENGINE:-c}   http://localhost:$PORT_API"
( cd bricolage && PROVIDER="$PROVIDER" PORT="$PORT_API" BRICKIFY_WEB="http://localhost:$PORT_WEB" \
    exec uv run --project ../brickify python server.py ) &
API_PID=$!

# --- stop both together -------------------------------------------------------
trap 'echo; echo "stopping…"; kill "$API_PID" "$WEB_PID" 2>/dev/null || true; exit 0' INT TERM
echo
echo "  ✓  open  http://localhost:$PORT_WEB     (Ctrl+C to stop)"
echo
wait
