"""End-to-end tests for /api/issues/* — exercises core through the HTTP layer."""
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from prism import core

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
_OSS_CONFIG_PATH = str(_FIXTURES_DIR / "oss_default.config.toml")


def _clear_config_cache():
    for mod_name in ("config", "prism.config"):
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "load_config"):
            try:
                mod.load_config.cache_clear()
            except Exception:
                pass


@pytest.fixture
def client_oss(tmp_db):
    """TestClient bound to the OSS-default prism config (TASK project, me/claude assignees)."""
    old_value = os.environ.get("PRISM_CONFIG")
    os.environ["PRISM_CONFIG"] = _OSS_CONFIG_PATH
    _clear_config_cache()
    try:
        from prism.dashboard.api.main import create_app
        app = create_app()
        with TestClient(app) as c:
            yield c
    finally:
        if old_value is None:
            os.environ.pop("PRISM_CONFIG", None)
        else:
            os.environ["PRISM_CONFIG"] = old_value
        _clear_config_cache()


def test_list_empty(client):
    r = client.get("/api/issues")
    assert r.status_code == 200
    assert r.json() == []


def test_create_minimal(client):
    r = client.post("/api/issues", json={"title": "from api", "project": "SYS"})
    assert r.status_code == 201
    body = r.json()
    assert body["id"].startswith("SYS-")
    assert body["title"] == "from api"
    assert body["status"] == "todo"
    assert body["priority"] == "P1"
    assert body["assignee"] == "claude"


def test_create_validates_project(client):
    r = client.post("/api/issues", json={"title": "x", "project": "ZZZ"})
    assert r.status_code == 422


def test_create_with_status_in_progress(client):
    r = client.post("/api/issues", json={
        "title": "active", "project": "SYS", "status": "in_progress"
    })
    assert r.status_code == 201
    assert r.json()["status"] == "in_progress"


def test_create_scheduled_flips_status(client):
    r = client.post("/api/issues", json={
        "title": "later", "project": "SYS", "scheduled_at": "2026-12-01"
    })
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "scheduled"
    assert body["scheduled_at"].startswith("2026-12-01")


def test_get_returns_full_row(client):
    created = client.post("/api/issues", json={
        "title": "to fetch", "project": "SYS", "description": "brief"
    }).json()
    r = client.get(f"/api/issues/{created['id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == created["id"]
    assert body["description"] == "brief"
    assert isinstance(body["blocked_by"], list)


def test_get_404(client):
    r = client.get("/api/issues/TST-9999999")
    assert r.status_code == 404


def test_list_filter_status(client, core_db):
    a = core.create_issue(core_db, title="a", project="SYS")
    b = core.create_issue(core_db, title="b", project="SYS")
    core.update_issue(core_db, b["id"], status="in_progress")
    core_db.close()

    r = client.get("/api/issues?status=in_progress")
    assert r.status_code == 200
    ids = [i["id"] for i in r.json()]
    assert b["id"] in ids
    assert a["id"] not in ids


def test_list_filter_blocked_only(client, core_db):
    blocker = core.create_issue(core_db, title="b", project="SYS")
    waiter = core.create_issue(
        core_db, title="w", project="SYS", blocked_by=[blocker["id"]]
    )
    core_db.close()

    r = client.get("/api/issues?blocked_only=true")
    assert r.status_code == 200
    ids = [i["id"] for i in r.json()]
    assert waiter["id"] in ids
    assert blocker["id"] not in ids


def test_patch_status(client):
    a = client.post("/api/issues", json={"title": "t", "project": "SYS"}).json()
    r = client.patch(f"/api/issues/{a['id']}", json={"status": "in_progress"})
    assert r.status_code == 200
    body = r.json()
    assert body["issue"]["status"] == "in_progress"
    assert any("status" in c for c in body["changes"])


def test_patch_404(client):
    r = client.patch("/api/issues/TST-9999999", json={"status": "done"})
    assert r.status_code == 404


def test_patch_invalid_status(client):
    a = client.post("/api/issues", json={"title": "t", "project": "SYS"}).json()
    r = client.patch(f"/api/issues/{a['id']}", json={"status": "bogus"})
    assert r.status_code == 422


def test_close_done(client):
    a = client.post("/api/issues", json={"title": "t", "project": "SYS"}).json()
    r = client.post(f"/api/issues/{a['id']}/close",
                    json={"status": "done", "resolution": "shipped"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "done"
    assert body["resolution"] == "shipped"
    assert body["closed_at"] is not None


def test_close_cascades_blocked_by(client, core_db):
    blocker = core.create_issue(core_db, title="b", project="SYS")
    waiter = core.create_issue(
        core_db, title="w", project="SYS", blocked_by=[blocker["id"]]
    )
    core_db.close()

    client.post(f"/api/issues/{blocker['id']}/close",
                json={"status": "done"})
    waiter_after = client.get(f"/api/issues/{waiter['id']}").json()
    assert blocker["id"] not in waiter_after["blocked_by"]


def test_close_recurring_spawns_next(client):
    created = client.post("/api/issues", json={
        "title": "weekly", "project": "SYS",
        "scheduled_at": "2026-05-03T09:00", "recurrence": "weekly"
    }).json()
    r = client.post(f"/api/issues/{created['id']}/close",
                    json={"status": "done"})
    assert r.status_code == 200
    body = r.json()
    # CloseIssueResponse has next_issue_id alias for _next_issue_id
    assert body.get("next_issue_id") or body.get("_next_issue_id")
    next_id = body.get("next_issue_id") or body.get("_next_issue_id")
    spawned = client.get(f"/api/issues/{next_id}").json()
    assert spawned["status"] == "scheduled"
    assert spawned["recurrence"] == "weekly"
    assert created["id"] in spawned["linked_to"]


def test_comment_appended(client):
    a = client.post("/api/issues", json={"title": "t", "project": "SYS"}).json()
    r = client.post(f"/api/issues/{a['id']}/comment",
                    json={"message": "halfway"})
    assert r.status_code == 200
    events = client.get(f"/api/issues/{a['id']}/events").json()
    comments = [e for e in events if e["type"] == "comment"]
    assert len(comments) == 1
    assert comments[0]["message"] == "halfway"


def test_comment_with_status_done(client):
    a = client.post("/api/issues", json={"title": "t", "project": "SYS"}).json()
    r = client.post(f"/api/issues/{a['id']}/comment",
                    json={"message": "ship", "status": "done"})
    assert r.status_code == 200
    assert r.json()["status"] == "done"


# ---------------------------------------------------------------------------
# Config-driven validation
# ---------------------------------------------------------------------------

def test_oss_create_with_task_project_and_me_assignee(client_oss):
    """Fresh-install default config: project='TASK', assignee='me' must return 201."""
    r = client_oss.post("/api/issues", json={
        "title": "first issue", "project": "TASK", "assignee": "me"
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"].startswith("TASK-")
    assert body["assignee"] == "me"


def test_oss_default_project_used_when_omitted(client_oss):
    """When project is omitted, the first configured project prefix is used."""
    r = client_oss.post("/api/issues", json={"title": "no project field"})
    assert r.status_code == 201, r.text
    body = r.json()
    # OSS default config has TASK as the only project
    assert body["id"].startswith("TASK-")


def test_oss_bogus_project_returns_422(client_oss):
    """A project prefix not in config must be rejected with 422."""
    r = client_oss.post("/api/issues", json={
        "title": "bad project", "project": "ZZZ"
    })
    assert r.status_code == 422, r.text


def test_oss_bogus_assignee_returns_422(client_oss):
    """An assignee not in config must be rejected with 422."""
    r = client_oss.post("/api/issues", json={
        "title": "bad assignee", "project": "TASK", "assignee": "unknown_person"
    })
    assert r.status_code == 422, r.text


def test_oss_patch_assignee_valid(client_oss):
    """PATCH with a valid config assignee must succeed."""
    created = client_oss.post("/api/issues", json={
        "title": "to patch", "project": "TASK", "assignee": "claude"
    }).json()
    r = client_oss.patch(f"/api/issues/{created['id']}", json={"assignee": "me"})
    assert r.status_code == 200, r.text
    assert r.json()["issue"]["assignee"] == "me"


def test_oss_patch_assignee_invalid_returns_422(client_oss):
    """PATCH with an assignee not in config must be rejected with 422."""
    created = client_oss.post("/api/issues", json={
        "title": "to patch", "project": "TASK", "assignee": "claude"
    }).json()
    r = client_oss.patch(f"/api/issues/{created['id']}", json={"assignee": "alice"})
    assert r.status_code == 422, r.text
