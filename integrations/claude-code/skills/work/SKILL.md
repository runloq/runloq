---
name: work
description: >
  Pick up a runloq ticket by ID — verify it's startable, mark it in_progress,
  route it to the right agent/model, execute, and close with a summary.
  Use when someone says "/work TASK-N", "pick up ticket N", "start working on
  TASK-N", or references a ticket ID and wants to begin executing it.
---

# Work — Pick Up and Execute a Ticket

This skill covers the full ticket lifecycle from "I want to work on TASK-N"
to "TASK-N is closed with evidence." Run it for any ticket ID.

---

## Arguments

- `ID` (required) — the ticket identifier, e.g. `TASK-42`.

---

## Execution steps

### Step 1 — Read the ticket

```bash
runloq show ID
```

Capture: `status`, `priority`, `assignee`, `agent`, `model`, `blocked_by`,
description, and event history.

### Step 2 — Refuse if terminal

If `status` is `done` or `cancelled`, stop immediately:

> **ID is already {status}.** Use `runloq update ID --status todo` to reopen
> if you meant to revisit it.

Do not proceed.

### Step 3 — Check blockers

If `blocked_by` contains any ticket IDs:

```bash
runloq show BLOCKER-ID   # for each blocker
```

- If any blocker is still open, do NOT start this ticket. Inform the user
  which blocker must close first, or offer to work the blocker instead.
- If all blockers are already `done`/`cancelled`, proceed (the cascade will
  have cleared them, but `runloq show` may still list them).

### Step 4 — Honor agent + model routing

If the ticket has an `agent` field set, that names the specialist persona that
should execute it. If the ticket has a `model` field (`opus`, `sonnet`,
`haiku`), use the appropriate model tier.

**If the current session's model differs from the ticket's `model`:** dispatch
to a subagent with the correct model. Never run a `haiku`-tagged ticket on an
`opus` session — it wastes budget.

Dispatch example (Claude Code Agent tool):
```
subagent_type: <agent-slug>
model: <ticket.model>
prompt: "Pick up TASK-N: <description>. Mark in_progress, do the work, run
verification, close with summary/files/refs, and report back."
```

If the ticket has no `agent` / `model` fields, the current session handles it.

### Step 5 — Mark in progress

```bash
runloq update ID --status in_progress
```

### Step 6 — Execute

Do the work described in the ticket. Log meaningful progress:

```bash
runloq comment ID "Discovered root cause: …"
runloq comment ID "Tests passing, deploying to staging."
```

Reference the ticket ID in every relevant commit:
```bash
git commit -m "fix: <what> (TASK-N)"
```

### Step 7 — Verify

Before claiming done: run the relevant checks (tests, type-check, lint, build).
Never close a ticket with "it should work" — close it with evidence.

### Step 8 — Close

```bash
runloq close ID "One-paragraph summary of what was done and why." \
  --files path/to/changed/file1,path/to/file2 \
  --refs docs/design.md,path/to/adr
```

If the work was not completed (out of scope, superseded, wrong approach):
```bash
runloq close ID --status cancelled "Reason it's not happening."
```

---

## Failure modes

| Situation | Response |
|-----------|----------|
| Ticket not found | Report the ID doesn't exist. Offer `runloq search "…"` to locate it. |
| Ticket is done/cancelled | Report terminal state; offer to reopen if appropriate. |
| Blocked by open tickets | List the blockers; do not start. Offer to work a blocker instead. |
| Wrong model for task | Dispatch to a subagent with the correct model, then wait for the result. |
| Can't converge | Comment current state, list what's known and unknown, close as cancelled with a diagnostic note. Do not loop indefinitely. |

---

## Quick close (trivial tickets)

For one-liner tasks (< 5 min, no dispatch overhead needed):

```bash
runloq update ID --status in_progress
# do the work
runloq close ID "Done: <what changed>." --files <file>
```

No subagent dispatch needed when the work is faster than dispatch latency.
