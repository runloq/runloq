# runloq

**The backlog your AI coding agent reads, picks up, and closes itself.**

runloq is a local-first issue tracker built *for* AI coding agents (Claude Code,
Cursor, Codex). It's a real backlog your agent can drive end to end: read what's
open, pick up a ticket, route it to the right model, execute, and close it with a
full audit trail — no PM tool to live in, no UI to babysit.

> Not "a local Linear." **Linear for your agents.**

Everything is local: one SQLite file, a fast web dashboard, and a CLI. Private,
offline, instant.

---

## Quickstart

```bash
pipx install runloq      # CLI + dashboard + MCP server, all bundled (no Node needed)
runloq init              # scaffold runloq.config.toml + an empty DB in ./state/
runloq serve             # open the dashboard at http://127.0.0.1:3002
```

That's it — `runloq serve` runs the API and serves the dashboard from one command;
the web UI is bundled in the install, so there's nothing to build.

Want to see it full first? `runloq init --demo` spins up a self-contained instance
pre-loaded with a fictional company's backlog so you can explore the board, search,
and ticket detail without typing anything.

From the CLI: `runloq create "Fix the flaky test" --priority P1`, `runloq board`,
`runloq list`, `runloq close TASK-1 "fixed"`. Run `runloq` with no arguments for the
full reference.

## What's in the box

- **SQLite tracker + CLI** (`runloq`) — full CRUD, a kanban `board`, FTS5 search,
  epics, blockers, links, scheduled + recurring tickets (auto-spawn the next
  iteration on close), point-in-time snapshots, an append-only event/audit log, and
  time tracking.
- **Agent-native model** — every ticket carries an `agent` (which specialist picks
  it up) and a `model` (which LLM tier runs it), so the backlog encodes *how* the
  work gets done, not just what.
- **Dashboard** — a FastAPI API + React 19 SPA: kanban board, drag-and-drop, inline
  edit, bulk actions, saved views, command palette, live SSE sync across tabs.
- **MCP server** (`runloq-mcp`) — drives runloq from any MCP-capable agent as
  structured tools, no UI needed.
- **Agent integration kit** — `integrations/claude-code/` ships rules + skills +
  hooks (plus a one-command installer) so the agent *automatically* acts on the
  backlog ("what's next today?" → it fetches and proposes tickets).

## How your agent uses runloq

Your agent talks to runloq two ways — use either or both:

- **CLI — the baseline, works with any agent that can run a shell.** The agent runs
  `runloq` commands directly (`runloq context`, `runloq list`, `runloq create`,
  `runloq close`). **No MCP needed.** The
  [agent integration kit](./integrations/claude-code/) wires this into Claude Code:
  SessionStart / UserPromptSubmit hooks call `runloq context` and inject the current
  backlog automatically, and the rules teach the agent the pick-up-and-close protocol.
- **MCP server — for MCP-capable agents.** `runloq-mcp` exposes every operation as a
  structured, typed tool instead of a shell command.

Both interfaces are thin wrappers over the same core, so they do the exact same
operations — your agent just picks whichever it prefers. The MCP server is included in
the default install; nothing to enable.

## Why not GitHub Issues? Why not Linear?

**vs. GitHub Issues** — excellent for human team collaboration; runloq isn't trying to
be. GitHub Issues has no `agent` field (which AI specialist picks this up?) and no
`model` field (which LLM tier runs it?), so the backlog doesn't encode *how* work gets
done, just *what* exists. It also has no MCP server, no local-first offline SQLite, and
no scheduled/recurring tickets that auto-spawn the next iteration. If you need a backlog
that's *readable and executable* by an agent, runloq is the right tool.

**vs. Linear** — a gorgeous UI for teams and PMs. runloq has a dashboard, but it's
secondary; the primary interface is the CLI and the MCP server, so agents drive the
backlog without touching a UI. Linear is cloud, per-seat, and built for synchronous
team workflows. runloq is local-first, free, and lets an agent operate the whole
backlog independently.

**vs. Beads (bd)** — a git-native tracker where issues are plain-text files in your
repo. runloq takes a different bet: SQLite + a live dashboard. Tickets are rows —
queryable, filterable, sortable at zero latency, with kanban drag-and-drop, FTS5
search, and live sync. If you want issues in git history, use Beads; if you want a
queryable backlog with a shared live dashboard, use runloq.

> runloq is local-first by design — one SQLite file, a CLI, a dashboard, and an MCP
> server. A hosted/multi-tenant edition is not part of this project.

## Configuration

`runloq init` scaffolds `runloq.config.toml`. Key sections:

```toml
[projects]
TASK = "Tasks"           # prefix → display name; add as many as you need

[assignees]
list = ["agent", "me"]

[models]
list = ["opus", "sonnet", "haiku"]

[agents]
# dir = ".claude/agents"  # optional: where agent .md definitions live

[paths]
state_dir = "state"      # where the SQLite DB lives

[dashboard]
host = "127.0.0.1"
port = 3002
```

runloq resolves config from `$RUNLOQ_CONFIG`, then `./runloq.config.toml`, then
next to the installed package. Your database (`state/`) and `runloq.config.toml` are
**gitignored** — your tickets never get committed. `RUNLOQ_STATE_DIR` / `RUNLOQ_DB`
override the config file.

## Security

**For local use only by default.** Every transport binds to `127.0.0.1`
(loopback-only): `runloq serve` and the Docker Compose mapping both stay on localhost.
Data never leaves your machine.

**Don't expose runloq on a public interface without protection.** On Linux, Docker's
iptables rules bypass host firewalls, so binding `0.0.0.0:3002` on a VPS exposes every
write endpoint to the internet.

For remote/API-only use, runloq ships an opt-in bearer-token middleware (off by
default):

```bash
export RUNLOQ_API_TOKEN="$(openssl rand -hex 32)"
runloq serve
# every request then needs:  Authorization: Bearer <token>
```

`GET /api/healthz` stays public; everything else (SSE + all writes) requires the token.
For production, front it with a reverse proxy (nginx/Caddy) or a VPN (WireGuard,
Tailscale) rather than a static browser token. Full detail: [SECURITY.md](./SECURITY.md).

## Run with Docker

SQLite is embedded, so it's a single service with state persisted on the host:

```bash
docker compose up -d
open http://localhost:3002
```

`./state/runloq.db` is your data — back it up like any file.

## License

[AGPL-3.0](./LICENSE). Free to use, modify, and self-host. If you run a modified
version as a network service, you must share your changes.

---

# Development

Everything below is for working **on** runloq (building from source, the dashboard
SPA, releases, contributing). If you just want to *use* runloq, the Quickstart above
is all you need.

## Install from source

Building from source is the only path that needs **Node 18+** (to compile the
dashboard SPA — the published wheel ships it pre-built):

```bash
git clone https://github.com/runloq/runloq.git
cd runloq
cd dashboard/web && npm install && npm run build && cd ../..   # build the SPA
pipx install .          # runloq + runloq-serve + runloq-mcp into a managed venv
```

> `dashboard/web/dist/` must exist before install/build so the wheel can bundle it.
> Skip the `npm run build` and `runloq serve` still starts, but the dashboard root
> returns 404 (the `/api/*` routes keep working).

## Dashboard development

Run the API and a Vite dev server side by side:

```bash
runloq serve                                   # shell 1 — API on :3002
cd dashboard/web && npm run dev                # shell 2 — web dev server, proxies /api
```

## Tests

```bash
python -m pytest tests/ dashboard/api/tests/
```

## Releasing

Releases ship to PyPI via OIDC **Trusted Publishing** (no stored tokens) on a
`v*.*.*` tag push. One-time setup + the release steps: [RELEASING.md](./RELEASING.md).

## Contributing

Contributions welcome — setup, conventions, and the PR checklist are in
[CONTRIBUTING.md](./CONTRIBUTING.md). Report security issues via
[GitHub Security Advisories](https://github.com/runloq/runloq/security/advisories/new)
(see [SECURITY.md](./SECURITY.md)); changes are logged in [CHANGELOG.md](./CHANGELOG.md).
