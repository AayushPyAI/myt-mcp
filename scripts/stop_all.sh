#!/bin/bash
# Stop the MCP server and the Cloudflare tunnel started by scripts/start_all.sh. The automation Chrome stays open.
LOGS=/tmp/myt-mcp
for name in server tunnel; do
  if [ -f "$LOGS/$name.pid" ]; then
    kill "$(cat "$LOGS/$name.pid")" 2>/dev/null && echo "Stopped $name" || echo "$name was not running"
    rm -f "$LOGS/$name.pid"
  fi
done
