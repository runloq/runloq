"""Server-Sent Events: push `db-changed` to all connected dashboards
when prism/state/runloq.db's mtime changes.

Architecture:
- One asyncio Broker holds a list of subscriber queues
- One watchdog Observer watches the DB file's parent directory
- On mtime change, the Observer thread schedules broker.publish on the loop
- Each /sse request opens an EventSourceResponse that consumes from a queue

Why SSE not WebSocket: one-direction push (server → client), HTTP-friendly,
auto-reconnect built into EventSource — no extra plumbing. WS is overkill.
"""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import Request
from sse_starlette.sse import EventSourceResponse
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class Broker:
    """Fan-out broker for SSE messages."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue] = []
        self._lock = asyncio.Lock()

    async def publish(self, payload: dict) -> None:
        async with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                # Drop the message for slow consumers; better than blocking
                # the publisher (the watchdog thread).
                pass

    async def stream(
        self, *, timeout: Optional[float] = None
    ) -> AsyncIterator[dict]:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        async with self._lock:
            self._subscribers.append(q)
        try:
            while True:
                if timeout is None:
                    yield await q.get()
                else:
                    yield await asyncio.wait_for(q.get(), timeout=timeout)
        finally:
            async with self._lock:
                if q in self._subscribers:
                    self._subscribers.remove(q)


broker = Broker()


class _DBChangeHandler(FileSystemEventHandler):
    """Watchdog handler — schedules broker.publish on the asyncio loop
    whenever the watched DB file is modified."""

    def __init__(
        self, db_path: Path, loop: asyncio.AbstractEventLoop
    ) -> None:
        self.db_path = db_path.resolve()
        self.loop = loop

    def on_modified(self, event):  # type: ignore[no-untyped-def]
        if event.is_directory:
            return
        if Path(event.src_path).resolve() == self.db_path:
            asyncio.run_coroutine_threadsafe(
                broker.publish({"type": "db-changed"}), self.loop
            )


def start_watcher(
    db_path: Path, loop: asyncio.AbstractEventLoop
) -> Observer:
    """Start a watchdog Observer on db_path's parent directory.

    Returns the running observer so the app can stop+join it on shutdown.
    """
    observer = Observer()
    observer.schedule(
        _DBChangeHandler(db_path, loop),
        str(db_path.parent),
        recursive=False,
    )
    observer.start()
    return observer


async def sse_endpoint(request: Request) -> EventSourceResponse:
    """The /sse route handler — yields broker messages as SSE events
    until the client disconnects."""
    async def event_gen():
        async for payload in broker.stream():
            if await request.is_disconnected():
                break
            yield {"event": "message", "data": json.dumps(payload)}
    return EventSourceResponse(event_gen())
