# Changelog

Kept current at every milestone; newest first.

---
## 0.1.0 — Initial public release

First public release of runloq. Local-first issue tracker built for AI coding agents (Claude Code, Cursor, Codex). Includes:

- **SQLite tracker** with full CRUD, kanban board, FTS5 search, scheduled + recurring tickets
- **CLI** (`runloq` command) with 12+ subcommands
- **Dashboard** — FastAPI API + React SPA with live SSE sync, kanban board, drag-and-drop, inline edit
- **Agent-native model** — every ticket carries an `agent` (which specialist) and `model` (which LLM tier)
- **MCP server** — drive runloq from Claude Code or any MCP-capable agent
- **Claude Code integration kit** — rules, skills, hooks to wire runloq into an agent automatically

See [CONTRIBUTING.md](./CONTRIBUTING.md) and [SECURITY.md](./SECURITY.md) for setup and vulnerability reporting.

---


## 2026-06-10 — Claude Code integration kit

- **`integrations/claude-code/`**: everything needed to wire runloq into a Claude Code agent so it automatically reads, picks up, and closes tickets.
  - `rules/prism.md`: session-start behavior, pickup protocol, model-routing heuristic, tickets-as-source-of-truth framing.
  - `skills/issue/SKILL.md`: full CRUD skill (create / list / show / update / close / comment / search) with CLI and MCP equivalents.
  - `skills/work/SKILL.md`: end-to-end pickup skill (read → check blockers → honor agent+model routing → mark in_progress → execute → verify → close).
  - `hooks/session-start.sh`: SessionStart hook injecting runloq context (in-progress, due-soon, recent activity) at boot with a pickup nudge.
  - `hooks/user-prompt-submit.sh`: UserPromptSubmit hook detecting "what's next?" intent via keyword match (zero latency) and surfacing candidates.
  - `install.sh`: idempotent one-command installer — copies rules/skills/hooks/agents into the target repo's `.claude/`; never clobbers existing files.
  - `agents/engineer.md`: minimal example agent showing the `agent` field format.
- **Fix**: relocated `prism/mcp` → `mcp/` to match the package-dir mapping and resolve a stdio-transport import error (`19bb339`).

---

## 2026-06-09 — MCP server

- **`mcp/server.py`**: FastMCP server exposing the full tracker API over stdio. 9 tools: `create_issue`, `list_issues`, `get_issue`, `update_issue`, `close_issue`, `comment_issue`, `board`, `search`, `context`.
- All tools delegate to `core.py` / `config.py` with no business-logic duplication. Validation errors returned as `{"error": "..."}` dicts — agents receive a machine-readable signal instead of a transport crash.
- `prism/__init__.py` added so the `prism/` package takes precedence over `prism.py` on `sys.path` (Python 3.3+ package-over-module rule).
- Entry point `runloq-mcp = "prism.mcp.server:main"` registered in `pyproject.toml`.
- **Tests**: 32 tests in `tests/test_mcp.py` covering create→list→show→update→close round-trips, recurrence spawning, `blocked_by` CSV, not-found errors, board/search/context shapes.

---

## 2026-06-09 — pip packaging (`prism` + `runloq-serve` console commands)

- **`pyproject.toml`**: setuptools backend, Python ≥ 3.11. Three console entry points: `prism`, `runloq-serve`, `runloq-mcp`.
- Dashboard web build (`dashboard/web/dist`) bundled as package data for post-install `StaticFiles` serving.
- `runloq serve` subcommand added to the CLI; `RUNLOQ_HOST` / `RUNLOQ_PORT` env vars respected.
- Compatibility shim in `prism.py` registers `core` / `config` on `sys.path` when running as an installed package.
- Root `conftest.py` registers the repo root as the `prism` package for tests regardless of worktree directory name.
- Quickstart in README updated to `pipx install` / `runloq init` / `runloq serve`.

---

## 2026-06-09 — Dashboard standalone build + router simplification

- **Vendor UI primitives**: replaced `@strata/ui` re-exports (Command, Input, Textarea) with full local shadcn/Radix implementations so `npm run build` succeeds without the monorepo. `@strata/ui` alias removed from `vite.config.ts`.
- **Remove TanStack Router**: the single-route SPA had no navigation needs. Replaced `RouterProvider` with a plain React root; folded `__root.tsx` + `routes/index.tsx` into `src/App.tsx`. Drops `@tanstack/react-router` and `@tanstack/router-plugin` from the dependency tree.
- **Fix**: robust config import in package context; `runloq init` scaffolds `runloq.config.toml` and is now registered in the CLI dispatch table (`7777939`).

---

## 2026-06-09 — Config-drive + Docker Compose

- **`config.py`**: TOML-based loader with 5-level resolution order: `$RUNLOQ_CONFIG` > `cwd/runloq.config.toml` > `pkg/runloq.config.toml` > `pkg/.runloq/config.toml` > built-in defaults. Sections: `[projects]`, `[assignees]`, `[models]`, `[agents]`, `[paths]`, `[dashboard]`.
- `TRACKER_DB` / `TRACKER_STATE_DIR` env vars override the config file (env wins). `lru_cache(maxsize=1)` per process; `cache_clear()` in tests for isolation.
- `prism.py` replaces hard-coded `VALID_PROJECTS` / `VALID_ASSIGNEES` / `VALID_MODELS` with config-derived getters.
- **`docker-compose.yml`** + **`Dockerfile`**: single-container setup mounting `./state` for persistence; `RUNLOQ_CONFIG` env var wired through.

---

## 2026-06-09 — Initial public extraction

- **First commit**: runloq extracted from a private monorepo as a standalone OSS project (AGPL-3.0). Private tracker state excluded.
- Core: `core.py` (788 lines) — SQLite schema with FTS5, issue lifecycle, events append-log, recurrence spawning, snapshot/recover, timer, `blocked_by` cascade on close.
- CLI: `prism.py` — `create`, `list`, `show`, `update`, `close`, `comment`, `search`, `board`, `context`, `snapshot`, `recover`, `timer` subcommands.
- Dashboard: FastAPI backend (`dashboard/api/`) with SSE live-sync; React + TanStack Query + shadcn frontend (`dashboard/web/`).
- Includes `check_new.py` helper for detecting new issues since last seen.
- README, LICENSE (AGPL-3.0), `.gitignore`.
