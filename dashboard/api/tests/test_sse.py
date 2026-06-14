"""Broker-level test for the SSE pubsub. We don't open a real EventSource
in the test (would block); the broker's publish/stream contract is the
unit under test, and the integration with watchdog is exercised by the
healthz + create flow under uvicorn (manual smoke).

The integration tests below validate the full HTTP-mutation → SSE-event path:
a subscriber registers on the broker, a mutation runs via TestClient, and the
subscriber asserts it received an `issue-changed` event with the correct
{id, action} payload.
"""
import asyncio
import pytest

from prism.dashboard.api.sse import broker


@pytest.mark.asyncio
async def test_broker_publish_reaches_subscriber():
    received = []

    async def consume():
        async for msg in broker.stream(timeout=2.0):
            received.append(msg)
            break

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)  # let consume() register its queue
    await broker.publish({"type": "db-changed"})
    await asyncio.wait_for(task, timeout=2.0)
    assert received == [{"type": "db-changed"}]


@pytest.mark.asyncio
async def test_broker_fans_out_to_all_subscribers():
    received_a, received_b = [], []

    async def consume(bucket):
        async for msg in broker.stream(timeout=2.0):
            bucket.append(msg)
            break

    a_task = asyncio.create_task(consume(received_a))
    b_task = asyncio.create_task(consume(received_b))
    await asyncio.sleep(0.05)
    await broker.publish({"type": "db-changed", "n": 1})
    await asyncio.wait_for(asyncio.gather(a_task, b_task), timeout=2.0)
    assert received_a == [{"type": "db-changed", "n": 1}]
    assert received_b == [{"type": "db-changed", "n": 1}]


# ---------------------------------------------------------------------------
# Integration: HTTP mutation routes publish issue-changed to the broker
#
# The watchdog observer (started by the TestClient lifespan) may also publish
# a `db-changed` event when the DB file's mtime changes. Tests therefore
# collect ALL messages in a short window and assert that an `issue-changed`
# event with the expected payload is present among them.
# ---------------------------------------------------------------------------

async def _collect_for(seconds: float) -> list[dict]:
    """Subscribe to the broker and drain all messages for `seconds`."""
    received: list[dict] = []

    async def consume():
        try:
            async for msg in broker.stream(timeout=seconds):
                received.append(msg)
        except (asyncio.TimeoutError, TimeoutError):
            pass

    await asyncio.wait_for(consume(), timeout=seconds + 1.0)
    return received


@pytest.mark.asyncio
async def test_create_issue_publishes_issue_changed(client):
    """POST /api/issues → broker emits {type: issue-changed, id, action: create}."""
    # Subscribe before the mutation so we don't miss the event.
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    async with broker._lock:
        broker._subscribers.append(q)

    try:
        r = client.post("/api/issues", json={"title": "sse test", "project": "SYS"})
        assert r.status_code == 201
        issue_id = r.json()["id"]

        # Drain queue for up to 1s; the issue-changed arrives synchronously
        # after the route completes; the watchdog may also fire db-changed.
        await asyncio.sleep(0.2)
        received = []
        while not q.empty():
            received.append(q.get_nowait())
    finally:
        async with broker._lock:
            if q in broker._subscribers:
                broker._subscribers.remove(q)

    issue_changed = [m for m in received if m.get("type") == "issue-changed"]
    assert len(issue_changed) == 1, f"Expected one issue-changed, got: {received}"
    assert issue_changed[0]["id"] == issue_id
    assert issue_changed[0]["action"] == "create"


@pytest.mark.asyncio
async def test_update_issue_publishes_issue_changed(client):
    """PATCH /api/issues/{id} → broker emits {type: issue-changed, id, action: update}."""
    created = client.post("/api/issues", json={"title": "update-sse", "project": "SYS"}).json()
    issue_id = created["id"]

    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    async with broker._lock:
        broker._subscribers.append(q)

    try:
        r = client.patch(f"/api/issues/{issue_id}", json={"status": "in_progress"})
        assert r.status_code == 200
        await asyncio.sleep(0.2)
        received = []
        while not q.empty():
            received.append(q.get_nowait())
    finally:
        async with broker._lock:
            if q in broker._subscribers:
                broker._subscribers.remove(q)

    issue_changed = [m for m in received if m.get("type") == "issue-changed"]
    assert len(issue_changed) == 1, f"Expected one issue-changed, got: {received}"
    assert issue_changed[0] == {"type": "issue-changed", "id": issue_id, "action": "update"}


@pytest.mark.asyncio
async def test_close_issue_publishes_issue_changed(client):
    """POST /api/issues/{id}/close → broker emits {type: issue-changed, id, action: close}."""
    created = client.post("/api/issues", json={"title": "close-sse", "project": "SYS"}).json()
    issue_id = created["id"]

    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    async with broker._lock:
        broker._subscribers.append(q)

    try:
        r = client.post(f"/api/issues/{issue_id}/close", json={"status": "done", "resolution": "shipped"})
        assert r.status_code == 200
        await asyncio.sleep(0.2)
        received = []
        while not q.empty():
            received.append(q.get_nowait())
    finally:
        async with broker._lock:
            if q in broker._subscribers:
                broker._subscribers.remove(q)

    issue_changed = [m for m in received if m.get("type") == "issue-changed"]
    assert len(issue_changed) == 1, f"Expected one issue-changed, got: {received}"
    assert issue_changed[0] == {"type": "issue-changed", "id": issue_id, "action": "close"}


@pytest.mark.asyncio
async def test_comment_publishes_issue_changed(client):
    """POST /api/issues/{id}/comment → broker emits {type: issue-changed, id, action: comment}."""
    created = client.post("/api/issues", json={"title": "comment-sse", "project": "SYS"}).json()
    issue_id = created["id"]

    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    async with broker._lock:
        broker._subscribers.append(q)

    try:
        r = client.post(f"/api/issues/{issue_id}/comment", json={"message": "done!"})
        assert r.status_code == 200
        await asyncio.sleep(0.2)
        received = []
        while not q.empty():
            received.append(q.get_nowait())
    finally:
        async with broker._lock:
            if q in broker._subscribers:
                broker._subscribers.remove(q)

    issue_changed = [m for m in received if m.get("type") == "issue-changed"]
    assert len(issue_changed) == 1, f"Expected one issue-changed, got: {received}"
    assert issue_changed[0] == {"type": "issue-changed", "id": issue_id, "action": "comment"}


@pytest.mark.asyncio
async def test_failed_mutation_does_not_publish_issue_changed(client):
    """A 404 mutation must not publish an `issue-changed` SSE event.

    Note: a `db-changed` from the watchdog may still arrive if the DB file
    was touched; we only assert that no `issue-changed` event is emitted.
    """
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    async with broker._lock:
        broker._subscribers.append(q)

    try:
        # 404 — non-existent issue
        r = client.patch("/api/issues/TASK-9999999", json={"status": "done"})
        assert r.status_code == 404
        await asyncio.sleep(0.2)
        received = []
        while not q.empty():
            received.append(q.get_nowait())
    finally:
        async with broker._lock:
            if q in broker._subscribers:
                broker._subscribers.remove(q)

    issue_changed = [m for m in received if m.get("type") == "issue-changed"]
    assert issue_changed == [], f"No issue-changed should be published on mutation failure; got: {received}"
