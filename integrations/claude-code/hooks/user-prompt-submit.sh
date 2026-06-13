#!/usr/bin/env bash
# user-prompt-submit.sh — runloq UserPromptSubmit hook for Claude Code
#
# Detects intent-to-work prompts ("what's next?", "what can I work on?",
# "what should I do today?") and injects the current runloq pickup candidates
# into the context before the model sees the message.
#
# Registered in .claude/settings.json as a UserPromptSubmit hook:
#   { "event": "UserPromptSubmit", "command": ".claude/hooks/user-prompt-submit.sh" }
#
# Claude Code pipes a JSON payload to stdin:
#   { "prompt": "<the user's message>", ... }
# The hook emits JSON to stdout:
#   { "additionalContext": "<text>" }   — injected before the prompt
# or exits 0 with no output to pass through unchanged.
#
# Kill switches:
#   RUNLOQ_HOOKS_DISABLED=1              — disable all runloq hooks
#   RUNLOQ_SKIP_USER_PROMPT_SUBMIT=1     — disable only this hook
#
# Requirements: `runloq` on PATH.

set -euo pipefail

# --- Kill switches ---
[[ "${RUNLOQ_HOOKS_DISABLED:-0}"              == "1" ]] && exit 0
[[ "${RUNLOQ_SKIP_USER_PROMPT_SUBMIT:-0}"     == "1" ]] && exit 0

# --- Verify runloq is available ---
if ! command -v runloq &>/dev/null; then
  exit 0
fi

# --- Read stdin ---
PAYLOAD="$(cat)"

# --- Extract the user's prompt text ---
# Use python3 for safe JSON parsing (avoids jq dependency).
PROMPT_TEXT="$(python3 -c "
import json, sys
try:
    data = json.loads(sys.stdin.read())
    print(data.get('prompt', ''))
except Exception:
    print('')
" <<< "$PAYLOAD")"

# --- Intent detection: does this look like a "what's next?" prompt? ---
LOWER_PROMPT="$(echo "$PROMPT_TEXT" | tr '[:upper:]' '[:lower:]')"

INTENT_KEYWORDS=(
  "what's next"
  "whats next"
  "what can i work on"
  "what should i do"
  "what should i work on"
  "show me my tickets"
  "show tickets"
  "pickup"
  "pick up"
  "any tickets"
  "next ticket"
  "open tickets"
  "what to work on"
  "suggest a ticket"
  "what do i have"
  "what tasks"
  "backlog"
  "runloq context"
)

MATCHED=0
for kw in "${INTENT_KEYWORDS[@]}"; do
  if [[ "$LOWER_PROMPT" == *"$kw"* ]]; then
    MATCHED=1
    break
  fi
done

# --- If no match, pass through unchanged ---
[[ "$MATCHED" == "0" ]] && exit 0

# --- Fetch runloq context ---
CONTEXT="$(runloq context 2>/dev/null || true)"
OPEN="$(runloq list --status todo --assignee claude 2>/dev/null | head -20 || true)"

INJECTION="[runloq context — injected by user-prompt-submit hook]

${CONTEXT}"

if [[ -n "$OPEN" ]]; then
  INJECTION="${INJECTION}

Open tickets assigned to agent:
${OPEN}"
fi

INJECTION="${INJECTION}

→ Propose the highest-priority unblocked ticket from the above list."

# --- Emit JSON ---
python3 -c "
import json, sys
print(json.dumps({'additionalContext': sys.stdin.read()}))
" <<< "${INJECTION}"
