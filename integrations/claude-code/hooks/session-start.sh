#!/usr/bin/env bash
# session-start.sh — runloq SessionStart hook for Claude Code
#
# Injects the runloq context (in-progress tickets, due-soon scheduled items,
# recent activity) into the agent's session at boot. Ends with a one-line
# nudge to propose a ticket pickup.
#
# Registered in .claude/settings.json as a SessionStart hook:
#   { "event": "SessionStart", "command": ".claude/hooks/session-start.sh" }
#
# Claude Code pipes a JSON payload to stdin; this script emits a JSON object
# to stdout with an "additionalContext" key that gets injected into the prompt.
#
# Kill switches (set in environment to skip):
#   RUNLOQ_HOOKS_DISABLED=1          — disable all runloq hooks
#   RUNLOQ_SKIP_SESSION_START=1      — disable only this hook
#
# Requirements: `runloq` must be on PATH (install with `pipx install runloq`).

set -euo pipefail

# --- Kill switches ---
[[ "${RUNLOQ_HOOKS_DISABLED:-0}"     == "1" ]] && exit 0
[[ "${RUNLOQ_SKIP_SESSION_START:-0}" == "1" ]] && exit 0

# --- Verify runloq is available ---
if ! command -v runloq &>/dev/null; then
  # Graceful degradation: no runloq = no context injected, session still starts.
  exit 0
fi

# --- Read stdin (harness JSON payload, e.g. { "source": "startup" | "compact" }) ---
PAYLOAD="$(cat)"

# On /compact resume, skip the full context dump to avoid re-flooding the window.
if echo "$PAYLOAD" | grep -q '"source"[[:space:]]*:[[:space:]]*"compact"' 2>/dev/null; then
  CONTEXT="$(runloq context 2>/dev/null || true)"
  COMPACT_NOTE="[Resumed from compact. runloq context refreshed.]"
  OUTPUT="${COMPACT_NOTE}

${CONTEXT}"
else
  CONTEXT="$(runloq context 2>/dev/null || true)"
  OUTPUT="${CONTEXT}"
fi

# --- Append the pickup nudge ---
NUDGE="
→ Review the above and propose the highest-priority open ticket to work on next, or confirm what's already in progress."

FULL_OUTPUT="${OUTPUT}${NUDGE}"

# --- Emit JSON for the harness ---
# Use python3 for safe JSON encoding (avoids jq dependency).
python3 -c "
import json, sys
print(json.dumps({'additionalContext': sys.stdin.read()}))
" <<< "${FULL_OUTPUT}"
