#!/usr/bin/env bash
# Install/refresh the tracker dashboard:
#   1. Verify Python 3.12 + pnpm are present
#   2. Install Python deps (FastAPI, uvicorn, watchdog, sse-starlette, pydantic)
#   3. Install + build the Vite SPA into web/dist/
#   4. Render the launchd plist with absolute paths and (re)load the agent
#   5. Wait for /api/healthz then exit
#
# Idempotent — safe to re-run after edits or on a fresh machine.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST_LABEL="dev.prism.api"
PLIST_SRC="$(dirname "$0")/$PLIST_LABEL.plist.template"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_LABEL.plist"
LOG_DIR="$HOME/Library/Logs"

# 1. Toolchain — Python 3.12+ is required for pydantic-core wheels.
PYTHON="${TRACKER_PYTHON:-$(command -v python3.12 || true)}"
if [[ -z "$PYTHON" ]]; then
    echo "✗ python3.12 not found on PATH and TRACKER_PYTHON not set." >&2
    echo "  brew install python@3.12  # then re-run" >&2
    exit 1
fi
echo "✓ Python:   $PYTHON ($("$PYTHON" --version))"

if ! command -v pnpm >/dev/null 2>&1; then
    echo "✗ pnpm not found on PATH." >&2
    echo "  brew install pnpm  # then re-run" >&2
    exit 1
fi
echo "✓ pnpm:     $(pnpm --version)"

# 2. Python deps — installed to user-site so we don't touch system packages.
echo "→ Installing Python deps…"
"$PYTHON" -m pip install --user --quiet --upgrade --break-system-packages \
    'fastapi>=0.115' 'uvicorn[standard]>=0.32' 'pydantic>=2.9' \
    'watchdog>=5.0' 'sse-starlette>=2.1'
echo "✓ Python deps installed"

# 3. SPA build
echo "→ Installing JS deps…"
( cd "$REPO_ROOT/dashboard/web" && pnpm install --silent )
echo "→ Building SPA…"
( cd "$REPO_ROOT/dashboard/web" && pnpm build > /dev/null )
echo "✓ SPA built → dashboard/web/dist/"

# 4. Render + install plist
mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"
sed \
    -e "s|__PYTHON__|$PYTHON|g" \
    -e "s|__REPO_ROOT__|$REPO_ROOT|g" \
    -e "s|__HOME__|$HOME|g" \
    "$PLIST_SRC" > "$PLIST_DST"
echo "✓ Plist:    $PLIST_DST"

# (Re)load. unload may fail if not loaded — fine.
launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load "$PLIST_DST"
echo "✓ launchctl load $PLIST_LABEL"

# 5. Wait for healthz
echo -n "→ Waiting for /api/healthz "
for i in {1..15}; do
    if curl -fsS http://127.0.0.1:3002/api/healthz > /dev/null 2>&1; then
        echo " ✓"
        echo
        echo "Dashboard is up: http://127.0.0.1:3002"
        echo "Logs: $LOG_DIR/prism-api.{out,err}.log"
        echo
        exit 0
    fi
    echo -n "."
    sleep 1
done

echo " ✗"
echo
echo "✗ prism-api didn't come up in 15s — check the err log:" >&2
echo "    tail -40 $LOG_DIR/prism-api.err.log" >&2
exit 1
