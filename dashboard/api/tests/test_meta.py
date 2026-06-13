def test_meta_returns_enums(client):
    r = client.get("/api/meta")
    assert r.status_code == 200
    body = r.json()
    assert "SYS" in body["projects"] and "ARC" in body["projects"]
    assert body["priorities"] == ["P0", "P1", "P2", "P3"]
    assert "todo" in body["statuses"] and "done" in body["statuses"]
    assert "claude" in body["assignees"]
    assert "opus" in body["models"] and "sonnet" in body["models"]
    assert "weekly" in body["recurrences"]
    # Agents list is dynamic from .claude/agents/*.md — just verify shape
    assert isinstance(body["agents"], list)
