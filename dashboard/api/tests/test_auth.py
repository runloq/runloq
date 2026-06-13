"""Tests for opt-in bearer-token auth middleware.

Three cases:
  1. No token configured (default) → all routes open, no regression.
  2. Token configured via PRISM_API_TOKEN env var:
       a. Missing Authorization header → 401.
       b. Wrong token → 401.
       c. Correct token → 200.
       d. /api/healthz always returns 200 (exempt from auth).
  3. Token configured via [dashboard] token in config file — same assertions.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers shared with conftest.py (keep in sync if conftest changes)
# ---------------------------------------------------------------------------
_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
_TEST_CONFIG_PATH = str(_FIXTURES_DIR / "test_prism.config.toml")
_TOKEN_CONFIG_PATH = str(_FIXTURES_DIR / "test_prism_token.config.toml")

_TEST_TOKEN = "s3cr3t-test-token"


def _clear_config_cache() -> None:
    for mod_name in ("config", "prism.config"):
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "load_config"):
            try:
                mod.load_config.cache_clear()
            except Exception:
                pass


def _make_client_with_env(tmp_db, env_overrides: dict) -> TestClient:
    """Build a TestClient with specific env vars set, cache cleared."""
    saved = {}
    for k, v in env_overrides.items():
        saved[k] = os.environ.get(k)
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    _clear_config_cache()
    try:
        from prism.dashboard.api.main import create_app
        app = create_app()
        client = TestClient(app, raise_server_exceptions=True)
        return client
    finally:
        for k, orig in saved.items():
            if orig is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = orig
        _clear_config_cache()


# ---------------------------------------------------------------------------
# Case 1: No token configured — all routes open
# ---------------------------------------------------------------------------

def test_no_auth_when_token_unset(tmp_db):
    """Without PRISM_API_TOKEN, all routes are reachable unauthenticated."""
    saved = os.environ.pop("PRISM_API_TOKEN", None)
    os.environ["PRISM_CONFIG"] = _TEST_CONFIG_PATH
    _clear_config_cache()
    try:
        from prism.dashboard.api.main import create_app
        app = create_app()
        with TestClient(app) as client:
            r = client.get("/api/healthz")
            assert r.status_code == 200
            r = client.get("/api/issues")
            assert r.status_code == 200
    finally:
        if saved is not None:
            os.environ["PRISM_API_TOKEN"] = saved
        _clear_config_cache()


# ---------------------------------------------------------------------------
# Case 2: Token via PRISM_API_TOKEN env var
# ---------------------------------------------------------------------------

@pytest.fixture
def authed_client(tmp_db):
    """TestClient for an app configured with a bearer token via env var."""
    saved_token = os.environ.get("PRISM_API_TOKEN")
    saved_config = os.environ.get("PRISM_CONFIG")
    os.environ["PRISM_API_TOKEN"] = _TEST_TOKEN
    os.environ["PRISM_CONFIG"] = _TEST_CONFIG_PATH
    _clear_config_cache()
    try:
        from prism.dashboard.api.main import create_app
        app = create_app()
        with TestClient(app, raise_server_exceptions=True) as client:
            yield client
    finally:
        if saved_token is None:
            os.environ.pop("PRISM_API_TOKEN", None)
        else:
            os.environ["PRISM_API_TOKEN"] = saved_token
        if saved_config is None:
            os.environ.pop("PRISM_CONFIG", None)
        else:
            os.environ["PRISM_CONFIG"] = saved_config
        _clear_config_cache()


def test_missing_auth_header_returns_401(authed_client):
    """No Authorization header → 401."""
    r = authed_client.get("/api/issues")
    assert r.status_code == 401


def test_wrong_token_returns_401(authed_client):
    """Wrong token → 401."""
    r = authed_client.get("/api/issues", headers={"Authorization": "Bearer wrong-token"})
    assert r.status_code == 401


def test_correct_token_returns_200(authed_client):
    """Correct bearer token → 200."""
    r = authed_client.get(
        "/api/issues",
        headers={"Authorization": f"Bearer {_TEST_TOKEN}"},
    )
    assert r.status_code == 200


def test_healthz_exempt_from_auth(authed_client):
    """/api/healthz is always public — no token required."""
    r = authed_client.get("/api/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_post_route_requires_auth(authed_client):
    """Write endpoints (POST /api/issues) also require the token."""
    r = authed_client.post(
        "/api/issues",
        json={"title": "test", "description": "test desc"},
    )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Case 3: Token via [dashboard] token in config file
# ---------------------------------------------------------------------------

def test_token_from_config_file(tmp_db):
    """Bearer token from [dashboard] token key in config file is enforced."""
    # Write a temp config with a token embedded
    import tempfile, pathlib
    cfg_text = f"""
[projects]
TASK = "Tasks"
[assignees]
list = ["me", "claude"]
[models]
list = ["opus", "sonnet", "haiku"]
[dashboard]
token = "{_TEST_TOKEN}"
"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".toml", delete=False
    ) as tf:
        tf.write(cfg_text)
        cfg_path = tf.name

    # Make sure env var is unset so the config file is the source
    saved_env = os.environ.pop("PRISM_API_TOKEN", None)
    saved_config = os.environ.get("PRISM_CONFIG")
    os.environ["PRISM_CONFIG"] = cfg_path
    _clear_config_cache()
    try:
        from prism.dashboard.api.main import create_app
        app = create_app()
        with TestClient(app) as client:
            # No token → 401
            r = client.get("/api/issues")
            assert r.status_code == 401
            # Correct token → 200
            r = client.get(
                "/api/issues",
                headers={"Authorization": f"Bearer {_TEST_TOKEN}"},
            )
            assert r.status_code == 200
            # /healthz still exempt
            r = client.get("/api/healthz")
            assert r.status_code == 200
    finally:
        pathlib.Path(cfg_path).unlink(missing_ok=True)
        if saved_env is not None:
            os.environ["PRISM_API_TOKEN"] = saved_env
        if saved_config is None:
            os.environ.pop("PRISM_CONFIG", None)
        else:
            os.environ["PRISM_CONFIG"] = saved_config
        _clear_config_cache()


def test_env_token_overrides_config_file_token(tmp_db):
    """PRISM_API_TOKEN env var takes precedence over config-file token."""
    import tempfile, pathlib
    cfg_text = """
[projects]
TASK = "Tasks"
[assignees]
list = ["me", "claude"]
[models]
list = ["opus", "sonnet", "haiku"]
[dashboard]
token = "config-file-token"
"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".toml", delete=False
    ) as tf:
        tf.write(cfg_text)
        cfg_path = tf.name

    env_token = "env-takes-precedence"
    saved_env = os.environ.get("PRISM_API_TOKEN")
    saved_config = os.environ.get("PRISM_CONFIG")
    os.environ["PRISM_API_TOKEN"] = env_token
    os.environ["PRISM_CONFIG"] = cfg_path
    _clear_config_cache()
    try:
        from prism.dashboard.api.main import create_app
        app = create_app()
        with TestClient(app) as client:
            # Config-file token should NOT work
            r = client.get(
                "/api/issues",
                headers={"Authorization": "Bearer config-file-token"},
            )
            assert r.status_code == 401
            # Env var token should work
            r = client.get(
                "/api/issues",
                headers={"Authorization": f"Bearer {env_token}"},
            )
            assert r.status_code == 200
    finally:
        pathlib.Path(cfg_path).unlink(missing_ok=True)
        if saved_env is None:
            os.environ.pop("PRISM_API_TOKEN", None)
        else:
            os.environ["PRISM_API_TOKEN"] = saved_env
        if saved_config is None:
            os.environ.pop("PRISM_CONFIG", None)
        else:
            os.environ["PRISM_CONFIG"] = saved_config
        _clear_config_cache()
