#!/usr/bin/env bash
# install.sh — Copy the runloq Claude Code integration kit into a target repo.
#
# Usage:
#   bash install.sh [TARGET_REPO_DIR]
#
#   TARGET_REPO_DIR  Path to the repo you want to instrument.
#                    Defaults to the current directory.
#
# What it does:
#   1. Creates .claude/{rules,skills,hooks,agents}/ in the target repo.
#   2. Copies rules/runloq.md, skills/issue/, skills/work/, hooks/*.sh,
#      agents/engineer.md (example only) into those directories.
#   3. Makes the hook scripts executable.
#   4. Prints the settings.json snippet you need to add.
#
# Idempotency: existing files are NEVER overwritten. If a destination file
# already exists the script prints a warning and skips it. Run again safely.
#
# Requirements:
#   - bash 3.2+
#   - `runloq` on PATH (install: pipx install runloq)
#   - The target repo must exist (it does not need to be a git repo).

set -euo pipefail

# --- Resolve paths ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:-$(pwd)}"
TARGET="$(cd "$TARGET" && pwd)"
CLAUDE_DIR="$TARGET/.claude"

echo "runloq Claude Code integration kit installer"
echo "==========================================="
echo "Kit source : $SCRIPT_DIR"
echo "Target repo: $TARGET"
echo "Destination: $CLAUDE_DIR"
echo ""

# --- Sanity checks ---
if [[ ! -d "$TARGET" ]]; then
  echo "ERROR: Target directory does not exist: $TARGET" >&2
  exit 1
fi

if ! command -v runloq &>/dev/null; then
  echo "WARNING: 'runloq' not found on PATH."
  echo "  Install it first: pipx install runloq"
  echo "  The kit files will still be copied, but the hooks won't work until"
  echo "  runloq is installed."
  echo ""
fi

# --- Helper: safe copy (never clobber) ---
safe_copy() {
  local src="$1"
  local dst="$2"
  if [[ -e "$dst" ]]; then
    echo "  SKIP (already exists): $dst"
  else
    mkdir -p "$(dirname "$dst")"
    cp "$src" "$dst"
    echo "  COPY: $dst"
  fi
}

# --- Helper: safe copy a whole directory tree ---
safe_copy_dir() {
  local src_dir="$1"
  local dst_dir="$2"
  find "$src_dir" -type f | while read -r src_file; do
    rel="${src_file#$src_dir/}"
    safe_copy "$src_file" "$dst_dir/$rel"
  done
}

echo "Copying files..."
echo ""

# 1. Rules
safe_copy "$SCRIPT_DIR/rules/runloq.md" "$CLAUDE_DIR/rules/runloq.md"

# 2. Skills
safe_copy_dir "$SCRIPT_DIR/skills/issue" "$CLAUDE_DIR/skills/issue"
safe_copy_dir "$SCRIPT_DIR/skills/work"  "$CLAUDE_DIR/skills/work"

# 3. Hooks
safe_copy "$SCRIPT_DIR/hooks/session-start.sh"       "$CLAUDE_DIR/hooks/session-start.sh"
safe_copy "$SCRIPT_DIR/hooks/user-prompt-submit.sh"  "$CLAUDE_DIR/hooks/user-prompt-submit.sh"

# 4. Make hooks executable (only if we just created them)
for hook in "$CLAUDE_DIR/hooks/session-start.sh" "$CLAUDE_DIR/hooks/user-prompt-submit.sh"; do
  if [[ -f "$hook" ]]; then
    chmod +x "$hook"
    echo "  CHMOD +x: $hook"
  fi
done

# 5. Example agent (with clear "example only" labeling)
AGENT_DST="$CLAUDE_DIR/agents/engineer.md"
if [[ ! -e "$AGENT_DST" ]]; then
  safe_copy "$SCRIPT_DIR/agents/engineer.md" "$AGENT_DST"
  echo ""
  echo "NOTE: agents/engineer.md is an EXAMPLE. Edit it or add your own agents"
  echo "      in $CLAUDE_DIR/agents/ — see the file's trailing note."
fi

echo ""
echo "Done. Add the following to your repo's .claude/settings.json"
echo "(merge with any existing hooks you already have):"
echo ""
echo "--------------------------------------------------------"
cat "$SCRIPT_DIR/settings.example.json"
echo "--------------------------------------------------------"
echo ""

# Warn if .claude/settings.json already exists — we never modify it automatically.
SETTINGS_FILE="$CLAUDE_DIR/settings.json"
if [[ -f "$SETTINGS_FILE" ]]; then
  echo "NOTE: $SETTINGS_FILE already exists."
  echo "  Manually merge the hook registrations above into it."
  echo "  We never overwrite your existing settings."
else
  echo "TIP: Copy the snippet above into a new file at:"
  echo "  $SETTINGS_FILE"
fi

echo ""
echo "Optional — register the runloq-mcp MCP server for richer tool-call access:"
echo "  See: $SCRIPT_DIR/README.md → 'Optional: MCP server'"
echo ""
echo "All done. Run 'runloq init' in your repo if you haven't already."
