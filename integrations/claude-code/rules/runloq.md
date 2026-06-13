# runloq — Issue Tracker Rules for Claude Code

runloq is your project's backlog. The SQLite database (default: `./state/runloq.db`)
is the **single source of truth** for all work. Use the `runloq` CLI (or the
`runloq-mcp` MCP server) to read, pick up, and close tickets.

> The agent does not ask for permission to read the tracker. It reads it, proposes
> actions, and acts on them.

---

## Always-on behaviors

| Event | Action |
|-------|--------|
| **Session start** | `runloq context` — surfaces in-progress tickets, due-soon scheduled items, and recent activity |
| **Before starting new work** | `runloq list --status todo` + `runloq board` — check what's already queued |
| **Before creating a ticket** | Search first: `runloq search "topic"` — avoid duplicates |
| **New non-trivial work discovered** | `runloq create "title" --description "…"` before writing code |
| **Work in progress** | `runloq update TASK-N --status in_progress` |
| **Milestone reached** | `runloq comment TASK-N "progress note"` |
| **Work complete** | `runloq close TASK-N "resolution summary" --files path1,path2 --refs doc1` |
| **Waiting on a human** | Create a ticket for that person, wire it into `--blocked-by` on your ticket |

---

## Picking up a ticket

1. **Read it:** `runloq show TASK-N` — check `status`, `agent`, `model`, `blocked_by`.
2. **Check blockers:** if `blocked_by` is non-empty, do NOT start. Resolve or surface the blocker first.
3. **Honor `agent` + `model`:** if the ticket specifies an `agent` slug and/or a `model`, dispatch accordingly — the ticket encodes *how* the work should run.
4. **Mark it:** `runloq update TASK-N --status in_progress`.
5. **Do the work**, logging progress with `runloq comment TASK-N "…"`.
6. **Close it:** `runloq close TASK-N "what was done and why" --files path1 --refs ref1`.

---

## Ticket fields that drive routing

| Field | Meaning |
|-------|---------|
| `agent` | Which specialist agent persona should pick this up (e.g. `engineer`, `designer`). Set in your config under `[agents]`. |
| `model` | Which LLM tier: `opus` / `sonnet` / `haiku`. Use cheaper tiers for mechanical work. |
| `assignee` | `claude` = agent-executable; your own username = human-actionable. |
| `priority` | P0 (now) → P3 (eventually). |
| `blocked_by` | List of ticket IDs that must close first. Never start a blocked ticket. |
| `scheduled_at` | ISO datetime for deferred/recurring work. |

---

## Status model

| Status | Meaning |
|--------|---------|
| `todo` | Not started (may have blockers — check `blocked_by`) |
| `in_progress` | Being worked on right now |
| `scheduled` | Deferred to a specific datetime |
| `done` | Resolved |
| `cancelled` | Won't be done |

There is no "blocked" status. Blockers live on the `blocked_by` attribute.

---

## Key CLI reference

```bash
runloq context                        # Smart session start — in-progress + due-soon
runloq board                          # Kanban view
runloq list --status todo             # All open tickets
runloq list --assignee claude         # Your queue
runloq show TASK-N                    # Full detail + history
runloq create "title" --description "…" --priority P1 --assignee claude
runloq update TASK-N --status in_progress
runloq comment TASK-N "note" --type progress
runloq close TASK-N "summary" --files path/to/file --refs doc
runloq search "query"                 # FTS5 full-text search
runloq snapshot                       # Save state before /compact
runloq recover                        # Restore context after compaction
```

---

## Model-routing heuristic

Default to `opus` for strategic/architectural decisions. Use `sonnet` for
debugging, refactoring, and mechanical execution against a clear plan. Use
`haiku` for trivial one-liners (rename, format, bump version). When a ticket's
`model` field differs from the current session model, dispatch via a subagent
with the correct model — never work a cheap-model ticket on an expensive session.

---

## Tickets are the source of truth

- All work (features, bugs, research, ops) gets a ticket before execution.
- Reference ticket IDs in commit messages: `git commit -m "fix login redirect (TASK-42)"`.
- Never leave work "invisible" — if you did something without a ticket, create one
  retroactively and mark it done with a brief note.
- For recurring work: `runloq create "…" --scheduled-at DATE --recurrence weekly`.
  On close, the next iteration auto-spawns. This replaces cron for human-actionable
  recurring tasks.

---

## MCP alternative

If `runloq-mcp` is registered (see `integrations/claude-code/README.md`), all the
above CLI calls can be replaced with MCP tool calls (`create_issue`, `list_issues`,
`get_issue`, `update_issue`, `close_issue`, `comment_issue`, `board`, `context`).
Both surfaces are equivalent — use whichever the agent environment makes available.
