"""Regression test for get_db() thread-safety under concurrent load.

FastAPI's TestClient runs requests in threads. Without check_same_thread=False
on the sqlite3 connection, concurrent mutations raise:
    ProgrammingError: SQLite objects created in a thread can only be used in
    that same thread.

This test fires 5 concurrent POST /api/issues mutations and asserts no 500s.
"""
from __future__ import annotations

import concurrent.futures



def _create_issue(client, n: int) -> int:
    """Fire a single POST /api/issues and return the HTTP status code."""
    r = client.post(
        "/api/issues",
        json={"title": f"concurrent-{n}", "project": "SYS"},
    )
    return r.status_code


def test_concurrent_mutations_no_500(client):
    """5 concurrent issue-creation requests must all succeed (201).

    Prior to the fix, the SQLite connection opened in one thread was handed to
    another thread by FastAPI's request machinery, raising ProgrammingError and
    surfacing as HTTP 500.
    """
    n_requests = 5
    with concurrent.futures.ThreadPoolExecutor(max_workers=n_requests) as pool:
        futs = [pool.submit(_create_issue, client, i) for i in range(n_requests)]
        statuses = [f.result() for f in concurrent.futures.as_completed(futs)]

    assert all(s == 201 for s in statuses), (
        f"Expected all 201, got: {statuses} — possible threading 500s"
    )


def test_concurrent_reads_no_500(client):
    """5 concurrent GET /api/issues reads must all succeed (200)."""
    n_requests = 5
    with concurrent.futures.ThreadPoolExecutor(max_workers=n_requests) as pool:
        futs = [
            pool.submit(lambda: client.get("/api/issues").status_code)
            for _ in range(n_requests)
        ]
        statuses = [f.result() for f in concurrent.futures.as_completed(futs)]

    assert all(s == 200 for s in statuses), (
        f"Expected all 200, got: {statuses}"
    )


def test_mixed_read_write_no_500(client):
    """Interleaved reads and writes — the scenario that triggered the original bug
    (SSE listener alive while mutation lands).
    """
    def do_write(n: int) -> int:
        return client.post(
            "/api/issues",
            json={"title": f"mixed-{n}", "project": "SYS"},
        ).status_code

    def do_read() -> int:
        return client.get("/api/issues").status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futs = (
            [pool.submit(do_write, i) for i in range(3)]
            + [pool.submit(do_read) for _ in range(3)]
        )
        statuses = [f.result() for f in concurrent.futures.as_completed(futs)]

    assert all(s in (200, 201) for s in statuses), (
        f"Unexpected status codes in mixed load: {statuses}"
    )
