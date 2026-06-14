---
name: issue
description: >
  Manage the runloq issue tracker — create, list, update, close, search, and
  view the board. Use when someone says "add issue", "create a ticket",
  "what's open", "show board", "close X", "search issues", or when tracking
  work in progress. Works via the `runloq` CLI or `runloq-mcp` MCP server.
---

# Issue — runloq Tracker CRUD

runloq stores issues in a local SQLite database. The `runloq` command is the
primary interface; the `runloq-mcp` MCP server exposes the same operations
programmatically if registered.

---

## Commands

### Create a ticket

```bash
runloq create "Short title" \
  --description "What needs to happen and why." \
  --priority P1 \
  --assignee claude \
  --agent engineer \
  --model sonnet
```

Required: `title` and `--description`.  
Supported priorities: `P0` (now) / `P1` / `P2` / `P3` (someday).  
Assignees are defined in your `runloq.config.toml`.

### List tickets

```bash
runloq list                              # all non-done
runloq list --status todo                # only unstarted
runloq list --status in_progress         # only in-flight
runloq list --assignee claude            # agent's queue
runloq list --priority P0,P1             # high-priority only
runloq list --project TASK               # one project prefix
```

### View a ticket

```bash
runloq show TASK-N                       # full detail + event history
runloq context                           # session-start summary (in-progress + due-soon)
runloq board                             # kanban view (grouped by status)
```

### Update a ticket

```bash
runloq update TASK-N --status in_progress
runloq update TASK-N --priority P0
runloq update TASK-N --assignee me
runloq update TASK-N --blocked-by TASK-M
runloq update TASK-N --scheduled-at 2024-12-01T09:00
```

### Close a ticket

```bash
runloq close TASK-N "What was done and why."
runloq close TASK-N "Resolved." --files src/foo.py --refs docs/design.md
runloq close TASK-N --status cancelled "Out of scope."
```

### Comment / log progress

```bash
runloq comment TASK-N "Deployed to staging — watching metrics."
runloq comment TASK-N "Blocked on API rate limit." --type blocker
```

### Search

```bash
runloq search "query"                    # FTS5 full-text search
```

### Scheduled / recurring tickets

```bash
# One-off deferred
runloq create "Review logs" --scheduled-at 2024-12-01T09:00

# Recurring (auto-spawns next on close)
runloq create "Weekly sync notes" \
  --scheduled-at 2024-12-02T10:00 \
  --recurrence weekly
```

---

## Decision rules

1. **Before creating** — search first (`runloq search "…"`). Avoid duplicates.
2. **Before starting** — `runloq show TASK-N`. If `blocked_by` is non-empty,
   stop and resolve or surface the blocker.
3. **Always include a description** — the title is just a label; the description
   is the brief a subagent reads cold. Make it self-contained.
4. **Close with evidence** — pass `--files` and `--refs` so the audit trail is
   useful. The resolution message should answer "what changed and why."
5. **Human actions = human tickets** — when progress requires a human, create a
   ticket for them and wire your ticket as `--blocked-by` that ID.

---

## MCP equivalent (when runloq-mcp is registered)

| CLI | MCP tool |
|-----|----------|
| `runloq create …` | `create_issue` |
| `runloq list …` | `list_issues` |
| `runloq show ID` | `get_issue` |
| `runloq update ID …` | `update_issue` |
| `runloq close ID …` | `close_issue` |
| `runloq comment ID …` | `comment_issue` |
| `runloq board` | `board` |
| `runloq context` | `context` |
| `runloq search …` | `search` |
