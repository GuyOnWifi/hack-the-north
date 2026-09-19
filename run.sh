#!/usr/bin/env bash
# Launch Bricolage — the Lane B API + the Brickbook web app, together.
#
#   ./run.sh                 real LLM + vision loop (slower, recognizable shapes)
#   PROVIDER=mock ./run.sh   deterministic + instant (offline, blocky shapes)
#
# Open http://localhost:3000  ·  Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")"

PROVIDER="${PROVIDER:-claude_cli}"   # claude_cli = real designer + vision; mock = fast/offline
PORT_API="${PORT_API:-8017}"
PORT_WEB="${PORT_WEB:-3000}"

# --- backend (Lane B) ---------------------------------------------------------
echo "▶ backend   PROVIDER=$PROVIDER   http://localhost:$PORT_API"
( cd bricolage && PROVIDER="$PROVIDER" PORT="$PORT_API" exec python server.py ) &
API_PID=$!

# --- web app (first run installs + builds) ------------------------------------
if [ ! -d web/node_modules ]; then echo "▶ installing web deps (first run)…"; ( cd web && npm install --no-audit --no-fund ); fi
if [ ! -d web/.next ];        then echo "▶ building web (first run)…";        ( cd web && npm run build ); fi

echo "▶ frontend  http://localhost:$PORT_WEB"
( cd web && BRICOLAGE_URL="http://127.0.0.1:$PORT_API" PORT="$PORT_WEB" exec npm start ) &
WEB_PID=$!

# --- stop both together -------------------------------------------------------
trap 'echo; echo "stopping…"; kill "$API_PID" "$WEB_PID" 2>/dev/null || true; exit 0' INT TERM
echo
echo "  ✓  open  http://localhost:$PORT_WEB     (Ctrl+C to stop)"
echo
wait
