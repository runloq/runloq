#!/usr/bin/env bash
# Stop + remove the tracker dashboard launchd agent.
# Leaves Python deps, node_modules, and dist/ in place — only touches launchctl.
set -euo pipefail

PLIST_LABEL="dev.prism.api"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"

if [[ ! -f "$PLIST_DST" ]]; then
    echo "Nothing to uninstall — $PLIST_DST not found."
    exit 0
fi

launchctl unload "$PLIST_DST" 2>/dev/null || true
rm -f "$PLIST_DST"
echo "✓ Unloaded + removed $PLIST_LABEL"
