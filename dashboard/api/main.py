"""FastAPI entry point for the tracker dashboard.

`create_app()` is the factory used by tests; `python3 -m prism.dashboard.api.main`
runs uvicorn against it on 127.0.0.1:3002 (the launchd-managed production mode).
"""
from __future__ import annotations
import asyncio
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles

from prism import prism as T

from .routes import events, health, issues, meta, search
from .sse import sse_endpoint, start_watcher


WEB_DIST = Path(__file__).resolve().parents[1] / "web" / "dist"
# ^^ Works both in development (source checkout) and post-install (hatchling
# bundles dashboard/web/dist → prism/dashboard/web/dist inside the wheel, so
# __file__ resolves to site-packages/prism/dashboard/api/main.py and
# parents[1]/web/dist points at the bundled dist). No path adjustment needed.


def _resolve_db_path() -> Path:
    """Same resolution rules as prism/prism.py — env vars override
    the on-disk default.

    The default state dir is prism/state/ (one level up from the dashboard
    package, not 'tracker/state' which was a path-construction bug).
    prism/prism.py uses os.path.dirname(__file__) → prism/ → prism/state/;
    main.py is at prism/dashboard/api/main.py so parents[2] == prism/ and
    the state dir is parents[2] / 'state', not parents[2] / 'tracker/state'.
    """
    state_dir = os.environ.get(
        "TRACKER_STATE_DIR",
        str(Path(__file__).resolve().parents[2] / "state"),
    )
    return Path(os.environ.get("TRACKER_DB", os.path.join(state_dir, "runloq.db")))


def _ensure_schema(db_path: Path) -> None:
    """Initialize the tracker schema if the DB is missing or empty.

    The CLI calls init_db/migrate_db in main(); the API server has its own
    entry point so it must do the same. Idempotent — safe to call on every
    startup.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(db_path), timeout=30)
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=30000")
        T.init_db(db)
        T.migrate_db(db)
        db.commit()
    finally:
        db.close()


def _make_bearer_middleware(token: str):
    """Return a Starlette middleware callable that enforces Bearer token auth.

    - Skips /healthz (liveness probe must never require auth).
    - Covers all other routes including /sse (SSE push).
    - Returns a plain 401 JSON body; never leaks the expected token.

    This is intentionally *off by default* — the middleware is only installed
    when ``RUNLOQ_API_TOKEN`` (or ``[dashboard] token`` in runloq.config.toml)
    is non-empty, so the localhost UX is completely unchanged.
    """
    from starlette.middleware.base import BaseHTTPMiddleware

    class BearerMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            # /healthz is always public — liveness probes must not require auth.
            if request.url.path == "/api/healthz":
                return await call_next(request)
            # Require Authorization: Bearer <token>
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                return Response(
                    content='{"detail":"Unauthorized"}',
                    status_code=401,
                    media_type="application/json",
                )
            supplied = auth[len("Bearer "):]
            if supplied != token:
                return Response(
                    content='{"detail":"Unauthorized"}',
                    status_code=401,
                    media_type="application/json",
                )
            return await call_next(request)

    return BearerMiddleware


@asynccontextmanager
async def _lifespan(app: FastAPI):
    db_path = _resolve_db_path()
    _ensure_schema(db_path)
    loop = asyncio.get_running_loop()
    observer = start_watcher(db_path, loop)
    app.state.watcher = observer
    yield
    observer.stop()
    observer.join(timeout=5)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Tracker Dashboard API",
        version="0.1.0",
        lifespan=_lifespan,
    )

    # --- Optional bearer-token middleware (opt-in, off by default) ---
    # Import load_config lazily so test harnesses can pin RUNLOQ_CONFIG before
    # create_app() is called (the same pattern used by routes/meta.py).
    try:
        from config import load_config as _load_config
    except ModuleNotFoundError:
        from prism.config import load_config as _load_config

    _cfg = _load_config()
    if _cfg.api_token:
        app.add_middleware(_make_bearer_middleware(_cfg.api_token))

    # API routes under /api
    app.include_router(health.router, prefix="/api")
    app.include_router(issues.router, prefix="/api")
    app.include_router(events.router, prefix="/api")
    app.include_router(search.router, prefix="/api")
    app.include_router(meta.router, prefix="/api")

    @app.get("/sse")
    async def sse(request: Request):
        return await sse_endpoint(request)

    # Serve the built SPA at / if it exists. In dev (Vite on :5180), this
    # path is empty and Vite's proxy handles routing.
    if WEB_DIST.exists():
        app.mount(
            "/", StaticFiles(directory=str(WEB_DIST), html=True), name="web"
        )
    else:
        import sys
        _path_str = str(WEB_DIST)
        print(
            "\n"
            "┌──────────────────────────────────────────────────────────────┐\n"
            "│  WARNING: Dashboard SPA not found — / will return 404        │\n"
            "│                                                               │\n"
            f"│  Missing: {_path_str}\n"
            "│                                                               │\n"
            "│  Build the SPA first:                                         │\n"
            "│    cd dashboard/web && npm install && npm run build           │\n"
            "│                                                               │\n"
            "│  The API routes (/api/*) still work normally.                 │\n"
            "└──────────────────────────────────────────────────────────────┘\n",
            file=sys.stderr,
        )

    return app


app = create_app()


def run() -> None:
    """Console-script entry point for `prism-serve` and `prism serve`.

    Host/port come from the [dashboard] section of runloq.config.toml; the
    RUNLOQ_HOST / RUNLOQ_PORT env vars override them (handy for containers) without
    editing the config file.

    Prints the dashboard URL so the caller knows where to open it.
    """
    import uvicorn

    try:
        from config import load_config as _load_config
    except ModuleNotFoundError:
        from prism.config import load_config as _load_config
    cfg = _load_config()
    host = os.environ.get("RUNLOQ_HOST", cfg.dashboard_host)
    port = int(os.environ.get("RUNLOQ_PORT", cfg.dashboard_port))
    url = f"http://{host}:{port}"
    print(f"runloq dashboard → {url}")
    uvicorn.run(
        "prism.dashboard.api.main:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    run()
