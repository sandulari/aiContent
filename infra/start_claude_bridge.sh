#!/usr/bin/env bash
# Start the claude-bridge daemon on the host.
#
# Writes PID + logs to /tmp/vre_claude_bridge.* so you can kill/restart.
# Uses nohup so it survives shell exits.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$HERE/claude_bridge.py"
PID_FILE="/tmp/vre_claude_bridge.pid"
LOG_FILE="/tmp/vre_claude_bridge.log"

if [ ! -f "$PY" ]; then
  echo "missing $PY" >&2
  exit 1
fi

# Kill any previous instance cleanly
if [ -f "$PID_FILE" ]; then
  OLD=$(cat "$PID_FILE" 2>/dev/null || true)
  if [ -n "$OLD" ] && kill -0 "$OLD" 2>/dev/null; then
    echo "stopping existing bridge pid $OLD"
    kill "$OLD" || true
    sleep 1
  fi
  rm -f "$PID_FILE"
fi

# Start fresh
nohup python3 "$PY" >> "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
sleep 1

# Health check
if curl -sS -m 3 http://127.0.0.1:7777/health >/dev/null 2>&1; then
  echo "claude-bridge running on 127.0.0.1:7777 (pid $(cat $PID_FILE))"
  echo "log: $LOG_FILE"
else
  echo "FAILED to start; see $LOG_FILE"
  tail -20 "$LOG_FILE"
  exit 1
fi
