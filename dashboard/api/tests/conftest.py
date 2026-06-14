"""Test fixtures for the dashboard API.

Each test gets a fresh empty DB at a tmp path, with tracker.DB_PATH and
STATE_DIR monkey-patched to point at it. The TestClient is bound to a
freshly-created FastAPI app that uses those env-resolved paths.

Config isolation (mirrors test isolation pattern from tests/test_mcp.py):
The Prism config is pinned to a test fixture file so that /api/meta and
project-validated endpoints return a known, stable set of projects/assignees/
models regardless of any ambient prism.config.toml in the developer's checkout
or CI environment.  ``load_config`` is ``@lru_cache``; the cache is cleared
before and after each test that touches config-dependent endpoints.
"""
from __future__ import annotations
import os
import sys
import sqlite3
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

# Make `prism.prism` (the CLI module) importable regardless of layout.
#
# Three scenarios:
#   1. Installed via pip  → `from prism import prism` just works.
#   2. Source checkout where the repo dir is named "prism" → adding the repo's
#      parent to sys.path makes `from prism import prism` resolve to prism/prism.py.
#   3. Source checkout where the repo dir has any other name (worktrees, etc.) →
#      fall back to importlib to load prism.py directly by file path.
_REPO_ROOT = Path(__file__).resolve().parents[3]  # repo root (contains prism.py)

try:
    from prism import prism as T  # scenario 1 or 2 (if parent already on path)
except (ImportError, AttributeError):
    # Scenario 3: load prism.py by file path and register it as prism.prism
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("prism.prism", str(_REPO_ROOT / "prism.py"))
    T = _ilu.module_from_spec(_spec)  # type: ignore[assignment]
    sys.modules["prism.prism"] = T  # type: ignore[assignment]
    # Ensure bare `import core` / `import config` resolve from the repo root
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    _spec.loader.exec_module(T)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Config isolation — pin PRISM_CONFIG to the test fixture for all API tests
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
_TEST_CONFIG_PATH = str(_FIXTURES_DIR / "test_prism.config.toml")


def _clear_config_cache() -> None:
    """Clear the load_config lru_cache regardless of which import path was used."""
    # The meta route imports via 'from config import load_config' or
    # 'from prism.config import load_config'.  Both resolve to the same
    # underlying function object, but sys.modules may hold it under either
    # name.  Clear both to be safe.
    for mod_name in ("config", "prism.config"):
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "load_config"):
            try:
                mod.load_config.cache_clear()
            except Exception:
                pass


@pytest.fixture(autouse=True)
def _pin_test_config():
    """Pin PRISM_CONFIG to the test fixture and clear the lru_cache around each test.

    This fixture is autouse so every test in this package runs with the
    deterministic project set defined in fixtures/prism.config.toml, without
    the caller needing to request it explicitly.

    The env var is set BEFORE the test body runs (and before create_app() /
    TestClient is constructed by the dependent `client` fixture) so that the
    first call to load_config() inside any route handler sees the fixture path.
    """
    old_value = os.environ.get("PRISM_CONFIG")
    os.environ["PRISM_CONFIG"] = _TEST_CONFIG_PATH
    _clear_config_cache()
    try:
        yield
    finally:
        if old_value is None:
            os.environ.pop("PRISM_CONFIG", None)
        else:
            os.environ["PRISM_CONFIG"] = old_value
        _clear_config_cache()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _init_test_db(tmp_dir: Path) -> Path:
    state_dir = tmp_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    db_path = state_dir / "prism.db"

    # Patch the module-level paths the production code reads.
    T.DB_PATH = str(db_path)
    T.STATE_DIR = str(state_dir)

    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    T.init_db(db)
    T.migrate_db(db)
    db.close()
    return db_path


@pytest.fixture
def tmp_db(tmp_path: Path) -> Iterator[Path]:
    db_path = _init_test_db(tmp_path)
    yield db_path
    # tmp_path auto-cleaned by pytest; T.DB_PATH stays set to a stale path
    # but each test re-initializes via this fixture.


@pytest.fixture
def client(tmp_db: Path) -> Iterator[TestClient]:
    from prism.dashboard.api.main import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def core_db(tmp_db: Path) -> Iterator[sqlite3.Connection]:
    """Direct DB connection for seeding without going through the HTTP layer."""
    db = T.get_db()
    yield db
    db.close()
