# runloq — Claude Code Integration Kit

This kit wires runloq into a Claude Code agent so it **automatically** reads your
backlog, proposes tickets to work on, and closes them with a full audit trail —
no manual prompting required.

Once installed, the autonomous loop looks like this:

```
Session starts
  → Hook fires: runloq context
  → Agent sees open tickets, in-progress work, due-soon items
  → Agent proposes highest-priority unblocked ticket

User says "what's next?" / "what can I work on?"
  → Hook fires: runloq list + runloq context
  → Agent proposes the top candidate, explains why

Agent picks up TASK-N
  → runloq show TASK-N   (check blockers, agent, model fields)
  → runloq update TASK-N --status in_progress
  → [does the work, commits with ticket reference]
  → runloq close TASK-N "What changed and why." --files ...

Session ends
  → runloq snapshot       (optional: preserves context for next session)
```

---

## What's in the kit

```
integrations/claude-code/
├── README.md                    ← you are here
├── install.sh                   ← one-command installer
├── settings.example.json        ← hook registration snippet
├── rules/
│   └── runloq.md                 ← agent rules: always-on behaviors, pickup protocol
├── skills/
│   ├── issue/SKILL.md           ← CRUD skill (create/list/show/update/close/search)
│   └── work/SKILL.md            ← pickup skill (read → verify → dispatch → close)
├── hooks/
│   ├── session-start.sh         ← injects runloq context at session boot
│   └── user-prompt-submit.sh    ← detects "what's next?" and surfaces candidates
└── agents/
    └── engineer.md              ← example agent definition (edit or replace)
```

---

## Install

### Prerequisites

1. runloq installed and initialized in your repo:

   ```bash
   pipx install prism
   cd /path/to/your/repo
   runloq init
   ```

2. Claude Code installed and working in the same repo.

### One-command install

From the runloq repo root:

```bash
bash integrations/claude-code/install.sh /path/to/your/repo
```

Or from inside your target repo:

```bash
bash /path/to/prism/integrations/claude-code/install.sh .
```

The installer:
- Creates `.claude/rules/`, `.claude/skills/`, `.claude/hooks/`, `.claude/agents/`
- Copies kit files into those directories
- **Never overwrites existing files** (safe to re-run)
- Makes hooks executable
- Prints the `settings.json` snippet you need to add

### Register the hooks

After running the installer, add the hook registrations to your repo's
`.claude/settings.json` (create it if it doesn't exist):

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/session-start.sh"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/user-prompt-submit.sh"
          }
        ]
      }
    ]
  }
}
```

If you already have a `settings.json`, merge the `hooks` block in — don't
replace the whole file.

### Verify the installation

```bash
# Check hooks are executable
ls -l .claude/hooks/

# Dry-run the session-start hook (no Claude session needed)
echo '{"source":"startup"}' | bash .claude/hooks/session-start.sh

# Dry-run the user-prompt-submit hook
echo '{"prompt":"what can I work on today?"}' | bash .claude/hooks/user-prompt-submit.sh
```

---

## How the autonomous loop works

### Session start hook

Fires automatically when Claude Code starts a session. Calls `runloq context`,
which returns:

- Tickets currently `in_progress`
- Scheduled tickets due now or within the next 24 hours
- Upcoming scheduled tickets this week
- Recent activity (last 10 events)

The agent sees this as injected context before your first message, so it
immediately knows the state of the board.

**Kill switch:** `RUNLOQ_SKIP_SESSION_START=1` disables this hook for a session.

### User-prompt-submit hook

Fires on every user message. Checks whether the message looks like a
"what's next?" intent (using a keyword list — no LLM call, zero latency).

Matching phrases include: "what's next", "what can I work on", "what should I
do today", "pick up", "suggest a ticket", "open tickets", "backlog", and more.

If matched, injects `runloq context` + `runloq list --status todo --assignee claude`
before the model sees the message. The agent then proposes the top candidate.

**Kill switch:** `RUNLOQ_SKIP_USER_PROMPT_SUBMIT=1` disables this hook.

**Global kill switch:** `RUNLOQ_HOOKS_DISABLED=1` disables all runloq hooks.

### Rules file

`rules/runloq.md` teaches the agent:
- Always read `runloq context` at session start
- Never start a blocked ticket
- Honor `agent` and `model` fields for routing
- Close every ticket with a resolution message, `--files`, and `--refs`
- Reference ticket IDs in commit messages
- Create tickets for human actions (wire as blockers)

Add this to your `.claude/CLAUDE.md` or drop it in `.claude/rules/` (Claude
Code auto-loads all `.md` files from that directory).

### Skills

**`issue` skill** — CRUD against the tracker. Use when you need to create,
list, update, search, or close tickets.

**`work` skill** — Full pickup protocol. Use when an agent starts executing a
ticket: reads it, checks blockers, honors routing, marks in-progress, logs
progress, verifies, closes with evidence.

### Agents

The `agents/engineer.md` file is a **minimal example** showing the `agent`
field format. Replace it or add your own domain-specific agents (frontend,
backend, designer, etc.) in `.claude/agents/`. The `description` field in
the frontmatter is the routing signal Claude Code uses when dispatching.

---

## Optional: MCP server

Instead of (or alongside) the CLI, you can register the `runloq-mcp` MCP server
so the agent drives runloq via tool calls rather than shell commands. This gives
richer structured responses and works in any MCP-capable environment.

See [`mcp/README.md`](../../mcp/README.md) for registration instructions for
Claude Code, Cursor, and any generic stdio MCP client.

The MCP tools mirror the CLI 1:1:

| CLI | MCP tool |
|-----|----------|
| `runloq context` | `context` |
| `runloq board` | `board` |
| `runloq create …` | `create_issue` |
| `runloq list …` | `list_issues` |
| `runloq show ID` | `get_issue` |
| `runloq update ID …` | `update_issue` |
| `runloq close ID …` | `close_issue` |
| `runloq comment ID …` | `comment_issue` |
| `runloq search …` | `search` |

---

## Customization

### Change which phrases trigger the prompt hook

Edit `.claude/hooks/user-prompt-submit.sh` and update the `INTENT_KEYWORDS`
array. The matching is case-insensitive substring matching — fast, no
dependencies.

### Add your own agents

Create `.claude/agents/<slug>.md` with the frontmatter fields `name`,
`description`, and `model`. Set `agent: <slug>` on any ticket to route it
to that specialist. Delete or rename `engineer.md` once you have your own.

### Multiple projects

runloq supports multiple project prefixes (`TASK`, `BUG`, `FEAT`, …) defined in
`runloq.config.toml`. The agent rules work across all prefixes — no changes to
the kit needed.

### Scheduled / recurring tickets

```bash
runloq create "Weekly review" \
  --scheduled-at YYYY-MM-DDTHH:MM \
  --recurrence weekly
```

On close, runloq auto-spawns the next iteration. The session-start hook will
surface it when it's due. This replaces cron for human-actionable recurring work.

---

## Troubleshooting

**Hook doesn't fire**
- Check that `prism` is on PATH: `which prism`
- Check that the hook is executable: `ls -l .claude/hooks/`
- Check that the hook is registered in `.claude/settings.json`
- Test the hook manually: `echo '{"source":"startup"}' | bash .claude/hooks/session-start.sh`

**`runloq context` returns nothing**
- Run `runloq init` in your repo to create the DB and config.
- Create at least one ticket: `runloq create "Test" --description "first ticket"`

**Agent ignores the ticket routing fields**
- Make sure `rules/runloq.md` is in `.claude/rules/` (or inlined in `CLAUDE.md`)
- Check that the ticket actually has `agent` and `model` set: `runloq show TASK-N`
