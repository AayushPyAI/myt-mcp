#!/bin/bash
# Start everything for testing on this Mac, in order:
#   1. the automation Chrome (port 9333), used for SATA, Viator and Aspire
#   2. a Cloudflare quick tunnel (a new public URL every time)
#   3. the MCP server, with the tunnel's host allowed in .env
# Then it prints the connector URL to paste into Claude. Run it again to restart; stop with scripts/stop_all.sh.
set -euo pipefail
cd "$(dirname "$0")/.."

LOGS=/tmp/myt-mcp
mkdir -p "$LOGS"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

wait_for() {  # wait_for <seconds> <command...>
  local seconds=$1; shift
  for _ in $(seq "$seconds"); do "$@" >/dev/null 2>&1 && return 0; sleep 1; done
  return 1
}

# 1. Automation Chrome (separate profile; Viator is already set to EUR there)
if curl -s -m 2 http://127.0.0.1:9333/json/version >/dev/null; then
  echo "1/3 Automation Chrome: already running"
else
  "$CHROME" --user-data-dir="$HOME/myt-ofran-chrome" --remote-debugging-port=9333 \
    --remote-debugging-address=127.0.0.1 --no-first-run about:blank >"$LOGS/chrome.log" 2>&1 &
  wait_for 20 curl -s -m 2 http://127.0.0.1:9333/json/version || { echo "Automation Chrome did not start (see $LOGS/chrome.log)"; exit 1; }
  echo "1/3 Automation Chrome: started"
fi

# 2. Cloudflare quick tunnel
pkill -f "cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8000" 2>/dev/null || true
: >"$LOGS/tunnel.log"
cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8000 >"$LOGS/tunnel.log" 2>&1 &
echo $! >"$LOGS/tunnel.pid"
wait_for 30 grep -aqo 'https://[a-z0-9-]*\.trycloudflare\.com' "$LOGS/tunnel.log" || { echo "Tunnel did not start (see $LOGS/tunnel.log)"; exit 1; }
TUNNEL_URL=$(grep -ao 'https://[a-z0-9-]*\.trycloudflare\.com' "$LOGS/tunnel.log" | head -1)
echo "2/3 Tunnel: $TUNNEL_URL"

# 3. MCP server, allowing the new tunnel host
sed -i '' "s|^ALLOWED_HOSTS=.*|ALLOWED_HOSTS=127.0.0.1:*,localhost:*,${TUNNEL_URL#https://}|" .env
# the Chrome scripts post their answers to this address (myt_mcp/ingest.py): the tunnel
grep -q "^PUBLIC_BASE_URL=" .env && sed -i '' "s|^PUBLIC_BASE_URL=.*|PUBLIC_BASE_URL=${TUNNEL_URL}|" .env || echo "PUBLIC_BASE_URL=${TUNNEL_URL}" >> .env
if [ -f "$LOGS/server.pid" ]; then kill "$(cat "$LOGS/server.pid")" 2>/dev/null || true; fi
# whatever still listens on 8000 is an old server with the old tunnel host in its allow-list (it answers 421), so stop it too
lsof -tiTCP:8000 -sTCP:LISTEN | xargs kill 2>/dev/null || true; sleep 2
.venv/bin/python server.py >"$LOGS/server.log" 2>&1 &
echo $! >"$LOGS/server.pid"
wait_for 20 curl -s -m 2 http://127.0.0.1:8000/health || { echo "Server did not start (see $LOGS/server.log)"; exit 1; }
wait_for 30 curl -s -m 5 "$TUNNEL_URL/health" || echo "Note: the tunnel URL is not answering yet; give it a minute."
echo "3/3 Server: running"

SECRET=$(grep '^MCP_SECRET=' .env | cut -d= -f2)
echo
echo "Connector URL for Claude (Settings -> Connectors), keep it private:"
echo "  $TUNNEL_URL/mcp/$SECRET"
echo
echo "Logs: $LOGS   Check every source: .venv/bin/python scripts/live_check.py   Stop: scripts/stop_all.sh"
