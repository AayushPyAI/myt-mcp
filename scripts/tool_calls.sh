#!/bin/bash
# Show which MCP tools Claude called (one line per call: time, tool, outcome, seconds; never the arguments).
# Use it after a test chat: if nothing is listed, the chat did NOT use our MCP.   Live view: scripts/tool_calls.sh -f
LOG=/tmp/myt-mcp/server.log
if [ "${1:-}" = "-f" ]; then tail -n 0 -f "$LOG" | grep --line-buffered -a "TOOL "; exit; fi
echo "Connector contacts (handshakes from claude.ai): $(grep -a -c 'POST /mcp/' "$LOG")   Tool calls: $(grep -a -c 'INFO myt_mcp: TOOL' "$LOG")"
grep -a "INFO myt_mcp: TOOL" "$LOG" | sed 's/ INFO myt_mcp: TOOL / /' | tail -${1:-40}
