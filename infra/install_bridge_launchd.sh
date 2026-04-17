#!/usr/bin/env bash
# Install the claude-bridge as a launchd LaunchAgent so it starts on
# every login and auto-restarts if it crashes. macOS only.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_SRC="$HERE/com.vre.claude-bridge.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.vre.claude-bridge.plist"

if [ ! -f "$PLIST_SRC" ]; then
  echo "missing $PLIST_SRC" >&2
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"

# Unload any previous version
if launchctl list | grep -q com.vre.claude-bridge; then
  echo "unloading previous version"
  launchctl unload "$PLIST_DST" 2>/dev/null || true
fi

cp "$PLIST_SRC" "$PLIST_DST"
launchctl load "$PLIST_DST"

sleep 1
if curl -sS -m 3 http://127.0.0.1:7777/health >/dev/null 2>&1; then
  echo "✓ claude-bridge installed and running via launchd"
  echo "  plist: $PLIST_DST"
  echo "  logs:  /tmp/vre_claude_bridge.log"
  echo
  echo "To stop:   launchctl unload $PLIST_DST"
  echo "To remove: launchctl unload $PLIST_DST && rm $PLIST_DST"
else
  echo "✗ launchd loaded the job but health check failed"
  echo "  see /tmp/vre_claude_bridge.log"
  tail -20 /tmp/vre_claude_bridge.log
  exit 1
fi
