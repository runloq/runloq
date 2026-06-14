# Tracker Dashboard

Local FastAPI + Vite SPA on `http://127.0.0.1:3002` for the issue tracker.
Replaces the old static `docs/claude/board.html` with a real
CRUD dashboard — create, edit, comment, navigate linked tickets, search,
filter, all in sync with the CLI via SSE-on-DB-mtime.

## Architecture

```
Browser SPA  ──HTTP──▶  FastAPI (uvicorn, :3002)  ──module──▶  prism.core
   ▲                         │                                       │
   └──────SSE────────────────┤                                       ▼
                             ▲                              prism/state/
                             │                                  runloq.db
                       watchdog (mtime)
```

Same write logic as the `prism.py` CLI — both call into
`prism.core` (the pure-functions module extracted in Phase A).
Whichever path writes, the other side sees it within ~200ms via SSE.

## Layout

```
prism/dashboard/
├── api/                    # FastAPI app
│   ├── main.py             # create_app() + uvicorn entry
│   ├── deps.py             # DB connection dependency
│   ├── schemas.py          # pydantic v2 request/response models
│   ├── sse.py              # async fan-out broker + watchdog observer
│   ├── routes/             # 7 endpoint files (one concern each)
│   └── tests/              # pytest, 24 tests, hits real test DB
├── web/                    # Vite SPA
│   ├── src/
│   │   ├── main.tsx        # TanStack Router + Query + Toaster
│   │   ├── routes/         # file-based: __root.tsx + index.tsx
│   │   ├── components/     # Card, Column, Board, TicketModal, …
│   │   ├── hooks/          # useIssues, useSSE, useMutations, …
│   │   ├── lib/            # api client, zod schemas, modal stack store
│   │   └── styles/         # design tokens (oklch) + Tailwind v4
│   └── tests/              # vitest, 4 tests for the api client
├── dev.prism.api.plist.template            # placeholder tokens; install.sh renders → ~/Library/LaunchAgents/
├── install.sh              # idempotent install + launchd load
└── uninstall.sh            # unload + remove plist
```

## Install

```bash
./install.sh
```

What it does:

1. Verifies Python 3.12+ and pnpm are on PATH.
2. `pip install --user --break-system-packages` the API deps.
3. `pnpm install && pnpm build` the SPA into `web/dist/`.
4. Renders `dev.prism.api.plist.template` into `~/Library/LaunchAgents/dev.prism.api.plist` with absolute paths.
5. `launchctl load` the agent.
6. Polls `/api/healthz` for up to 15s then prints success.

After install:
- Dashboard at <http://127.0.0.1:3002>.
- Logs at `~/Library/Logs/prism-api.{out,err}.log`.
- Service auto-restarts on crash and on login (RunAtLoad + KeepAlive).

## Uninstall

```bash
./uninstall.sh
```

Stops the service and removes the plist. Leaves Python deps,
`node_modules/`, and `web/dist/` in place for fast re-install.

## Develop

Two terminals — keep the launchd-managed prod API on `:3002` and run Vite
on `:5180` with proxy:

```bash
# Terminal 1 — Vite dev (HMR)
cd web && pnpm dev

# Terminal 2 — tail launchd logs
tail -f ~/Library/Logs/prism-api.err.log
```

Open <http://127.0.0.1:5180> for live-reloading dev. `/api` and `/sse`
proxy through to `:3002` automatically.

To run the API in-foreground (skipping launchd) for debugging:

```bash
# From the repo root (where pyproject.toml lives)
pip install -e .
python -m uvicorn prism.dashboard.api.main:app \
  --host 127.0.0.1 --port 3002 --reload
# or, if the runloq-serve entry-point is installed:
# runloq-serve
```

## Test

```bash
# API (requires Python 3.12+ for pydantic-core wheels)
python -m pytest dashboard/api/tests/ -v

# SPA
cd dashboard/web && pnpm test

# Full E2E happy-path (Phase F)
cd dashboard/e2e && pnpm test
```

## Keyboard

- `/` — open search palette
- `c` — new ticket
- `Esc` — close modal (or pop one level if linked-ticket stack is deep)
- click any ID badge inside a modal — opens that ticket on top, with a
  back arrow to return

## Why FastAPI + the same `core.py` as the CLI?

So the autosave Stop hook, the SwiftBar status check, `/work`, `/start`,
the dashboard SPA, and any future tool all see exactly the same state
with exactly the same business rules. Cascade-on-close, recurrence
auto-spawn, agent/model invariant, scheduled_at status coupling — all
live in `prism/core.py`, and the API just wraps them in HTTP +
pydantic validation. Adding a new field is one DB migration and one
schema update; the dashboard picks it up automatically.

WAL mode is on, with a `wal_checkpoint(TRUNCATE)` after every write so
the autosave hook never has dirty WAL sidecars to chase.
