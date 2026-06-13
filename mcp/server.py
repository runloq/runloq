"""runloq MCP server — programmatic access to the issue tracker.

Exposes the full runloq tracker API as MCP tools so any MCP-capable agent
(Claude Code, Cursor, Codex) can create, list, update, close, comment on,
and search issues without touching the CLI or UI.

All tools return plain dicts / lists (JSON-serialisable).  Validation errors
are returned as ``{"error": "<message>"}`` dicts rather than raised exceptions
so agents get a machine-readable signal instead of a transport-level error.

Entry point: ``runloq-mcp`` → ``main()`` → stdio transport.
"""
from __future__ import annotations

import json as _json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional

# Import the MCP SDK BEFORE putting the repo root on sys.path. The repo root
# contains a local ``mcp/`` package (this one), which would otherwise shadow
# the installed ``mcp`` SDK once the root is on the path.
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Path bootstrapping
# ---------------------------------------------------------------------------
# mcp/server.py is at <repo_root>/mcp/server.py. The repo root contains
# config.py, core.py, prism.py — append it to sys.path so bare ``import core``
# and ``import config`` (used inside prism.py / core.py) resolve, without
# shadowing the ``mcp`` SDK imported above.
_MCP_DIR = os.path.dirname(os.path.abspath(__file__))          # <repo_root>/mcp/
_REPO_ROOT = os.path.dirname(_MCP_DIR)                          # <repo root>

if _REPO_ROOT not in sys.path:
    sys.path.append(_REPO_ROOT)

# ---------------------------------------------------------------------------
# Lazy DB / core imports (deferred until first call so tests can patch env)
# ---------------------------------------------------------------------------

def _get_db() -> sqlite3.Connection:
    """Open a connection to the runloq DB, initialised and migrated if fresh."""
    import importlib.util as _ilu

    # Load config from the repo root.
    try:
        from config import load_config  # type: ignore[import]
    except ModuleNotFoundError:
        raise RuntimeError(
            "config.py not found on sys.path — make sure the repo root is on sys.path"
        )

    cfg = load_config()
    db_path = cfg.db

    # Honour test override (TRACKER_DB wins unconditionally).
    db_path = os.environ.get("TRACKER_DB", db_path)

    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

    db = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=30000")

    # Bootstrap schema on first use (idempotent — CREATE TABLE IF NOT EXISTS).
    _prism_py = os.path.join(_REPO_ROOT, "prism.py")
    _spec = _ilu.spec_from_file_location("_prism_cli_mcp", _prism_py)
    _cli = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_cli)
    _cli.init_db(db)
    _cli.migrate_db(db)

    return db


def _core():
    """Return the core module (lazy import so tests can patch DB_PATH first)."""
    import importlib
    try:
        return importlib.import_module("core")
    except ModuleNotFoundError:
        raise RuntimeError(
            "core.py not found on sys.path — make sure the repo root is on sys.path"
        )


def _cfg():
    from config import load_config  # type: ignore[import]
    return load_config()


# ---------------------------------------------------------------------------
# FastMCP app
# ---------------------------------------------------------------------------
mcp = FastMCP(
    name="runloq",
    instructions=(
        "runloq issue tracker. "
        "Tools: create_issue, list_issues, get_issue, update_issue, "
        "close_issue, comment_issue, board, search, context. "
        "All tracker IDs follow the pattern <PROJECT>-<NNN> (e.g. TASK-001, TASK-042)."
    ),
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe(fn, *args, **kwargs) -> Any:
    """Call fn; return {\"error\": str} on KeyError / ValueError / sqlite3.Error."""
    try:
        return fn(*args, **kwargs)
    except KeyError as exc:
        return {"error": f"Not found: {exc}"}
    except ValueError as exc:
        return {"error": str(exc)}
    except sqlite3.Error as exc:
        return {"error": f"Database error: {exc}"}


def _board_data(db: sqlite3.Connection) -> Dict[str, Any]:
    """Return the board state as a structured dict (no print statements)."""

    def _rows(status: str) -> List[dict]:
        rows = db.execute(
            """SELECT * FROM issues
               WHERE status=? AND issue_type='issue'
               ORDER BY
                 CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1
                               WHEN 'P2' THEN 2 ELSE 3 END""",
            (status,),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["blocked_by"] = _json.loads(d["blocked_by"]) if d.get("blocked_by") else []
            d["linked_to"] = _json.loads(d["linked_to"]) if d.get("linked_to") else []
            result.append(d)
        return result

    # Epics
    epics_raw = db.execute(
        """SELECT id, title, priority, status FROM issues
           WHERE issue_type='epic' AND status NOT IN ('done','cancelled')
           ORDER BY CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1
                                  WHEN 'P2' THEN 2 ELSE 3 END"""
    ).fetchall()
    epics = []
    for e in epics_raw:
        child_count = db.execute(
            "SELECT COUNT(*) FROM issues WHERE parent_id=? AND status NOT IN ('done','cancelled')",
            (e["id"],),
        ).fetchone()[0]
        epics.append({**dict(e), "open_children": child_count})

    # Scheduled this week (next 7 days, including overdue)
    cutoff_week = (datetime.now() + timedelta(days=7)).isoformat()
    sched_rows = db.execute(
        """SELECT * FROM issues
           WHERE status='scheduled' AND issue_type='issue'
             AND scheduled_at IS NOT NULL AND scheduled_at <= ?
           ORDER BY scheduled_at ASC""",
        (cutoff_week,),
    ).fetchall()
    scheduled = []
    for r in sched_rows:
        d = dict(r)
        d["blocked_by"] = _json.loads(d["blocked_by"]) if d.get("blocked_by") else []
        d["linked_to"] = _json.loads(d["linked_to"]) if d.get("linked_to") else []
        scheduled.append(d)

    return {
        "epics": epics,
        "scheduled_this_week": scheduled,
        "in_progress": _rows("in_progress"),
        "todo": _rows("todo"),
    }


def _context_data(db: sqlite3.Connection) -> Dict[str, Any]:
    """Return global context as a structured dict."""

    # In-progress + todo-with-blockers
    active_raw = db.execute(
        """SELECT * FROM issues
           WHERE status='in_progress'
              OR (status='todo' AND blocked_by NOT IN ('[]',''))
           ORDER BY
             CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1
                           WHEN 'P2' THEN 2 ELSE 3 END""",
    ).fetchall()
    active = []
    for r in active_raw:
        d = dict(r)
        d["blocked_by"] = _json.loads(d["blocked_by"]) if d.get("blocked_by") else []
        d["linked_to"] = _json.loads(d["linked_to"]) if d.get("linked_to") else []
        active.append(d)

    # Due or within 24 hours
    cutoff_soon = (datetime.now() + timedelta(hours=24)).isoformat()
    due_soon_raw = db.execute(
        """SELECT * FROM issues
           WHERE status='scheduled' AND issue_type='issue'
             AND scheduled_at IS NOT NULL AND scheduled_at <= ?
           ORDER BY scheduled_at ASC""",
        (cutoff_soon,),
    ).fetchall()
    due_soon = [dict(r) for r in due_soon_raw]

    # Upcoming this week (excluding due-soon)
    due_soon_ids = {r["id"] for r in due_soon}
    cutoff_week = (datetime.now() + timedelta(days=7)).isoformat()
    upcoming_raw = db.execute(
        """SELECT * FROM issues
           WHERE status='scheduled' AND issue_type='issue'
             AND scheduled_at IS NOT NULL AND scheduled_at <= ?
           ORDER BY scheduled_at ASC""",
        (cutoff_week,),
    ).fetchall()
    upcoming = [dict(r) for r in upcoming_raw if r["id"] not in due_soon_ids]

    # Recent activity (last 10 events)
    recent_raw = db.execute(
        "SELECT * FROM events ORDER BY created_at DESC LIMIT 10"
    ).fetchall()
    recent = [dict(r) for r in recent_raw]

    return {
        "active": active,
        "due_soon": due_soon,
        "upcoming_this_week": upcoming,
        "recent_activity": recent,
    }


def _split_csv(val: Optional[str]) -> Optional[List[str]]:
    """Split a comma-separated string into a list, or return None."""
    if not val:
        return None
    return [v.strip() for v in val.split(",") if v.strip()]


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def create_issue(
    title: str,
    description: str = "",
    project: str = "TASK",
    priority: str = "P1",
    assignee: str = "claude",
    agent: Optional[str] = None,
    model: Optional[str] = None,
    scheduled_at: Optional[str] = None,
    recurrence: Optional[str] = None,
    type: Literal["issue", "epic"] = "issue",
) -> dict:
    """Create a new issue in the runloq tracker.

    Args:
        title: Short, imperative title (required).
        description: Full brief — the standing context an agent reads cold.
        project: Project prefix (e.g. TASK, SYS, VER). Defaults to TASK.
        priority: P0 (critical) · P1 (high) · P2 (medium) · P3 (low).
        assignee: Who owns it — bare name without '@' (e.g. claude, me).
        agent: Agent slug for claude-assigned tasks (e.g. frontend-dev, backend-dev).
        model: LLM tier for claude tasks — opus · sonnet · haiku.
        scheduled_at: ISO date or datetime (YYYY-MM-DD or YYYY-MM-DDTHH:MM).
                      Auto-sets status to 'scheduled'.
        recurrence: daily · weekly · biweekly · monthly — auto-spawns next iteration on close.
        type: issue (default) or epic (container grouping).

    Returns the created issue as a dict with all fields.
    """
    db = _get_db()
    core = _core()
    return _safe(
        core.create_issue,
        db,
        title=title,
        description=description,
        project=project,
        priority=priority,
        assignee=assignee,
        agent=agent,
        model=model,
        scheduled_at=scheduled_at,
        recurrence=recurrence,
        type=type,
    )


@mcp.tool()
def list_issues(
    status: Optional[str] = None,
    project: Optional[str] = None,
    priority: Optional[str] = None,
    assignee: Optional[str] = None,
    type: Optional[str] = None,
    include_epics: bool = False,
) -> list:
    """List issues with optional filters.

    By default, excludes done/cancelled issues and epics.

    Args:
        status: Comma-separated statuses to include
                (todo, in_progress, scheduled, done, cancelled).
                Omit to get all active (non-terminal) issues.
        project: Comma-separated project prefixes to filter (e.g. TASK,SYS).
        priority: Comma-separated priorities to filter (e.g. P0,P1).
        assignee: Comma-separated assignees to filter (e.g. claude,me).
        type: Filter by issue_type — 'issue' or 'epic'.
        include_epics: Include epics in results (default False).

    Returns a list of issue dicts ordered by priority then last-updated.
    """
    db = _get_db()
    core = _core()
    return _safe(
        core.list_issues,
        db,
        status=_split_csv(status),
        project=_split_csv(project),
        priority=_split_csv(priority),
        assignee=_split_csv(assignee),
        type=_split_csv(type),
        include_epics=include_epics,
    )


@mcp.tool()
def get_issue(id: str) -> dict:
    """Get the full details of a single issue by ID.

    Args:
        id: Issue ID (e.g. TASK-001, TASK-042).

    Returns the issue as a dict.  Returns {\"error\": ...} if not found.
    """
    db = _get_db()
    core = _core()
    return _safe(core.get_issue, db, id)


@mcp.tool()
def update_issue(
    id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    assignee: Optional[str] = None,
    agent: Optional[str] = None,
    model: Optional[str] = None,
    blocked_by: Optional[str] = None,
    linked_to: Optional[str] = None,
    parent_id: Optional[str] = None,
    scheduled_at: Optional[str] = None,
    recurrence: Optional[str] = None,
    clear_agent: bool = False,
    clear_model: bool = False,
    clear_scheduled_at: bool = False,
    clear_recurrence: bool = False,
) -> dict:
    """Update one or more fields of an existing issue.

    Only pass the fields you want to change — unset args are left unchanged.

    Args:
        id: Issue ID to update (required).
        title: New title.
        description: New description (replaces existing).
        status: New status — todo · in_progress · scheduled · done · cancelled.
        priority: New priority — P0 · P1 · P2 · P3.
        assignee: New assignee (bare name, e.g. claude, me).
        agent: Agent slug (only for claude-assigned issues).
        model: LLM tier — opus · sonnet · haiku (only for claude-assigned issues).
        blocked_by: Comma-separated list of blocking issue IDs (replaces existing list).
        linked_to: Comma-separated list of related issue IDs (replaces existing list).
        parent_id: Parent epic ID.
        scheduled_at: New scheduled datetime (YYYY-MM-DD or YYYY-MM-DDTHH:MM).
        recurrence: daily · weekly · biweekly · monthly.
        clear_agent: Remove the agent field.
        clear_model: Remove the model field.
        clear_scheduled_at: Remove the scheduled_at field.
        clear_recurrence: Remove the recurrence field.

    Returns {\"issue\": ..., \"changes\": [...]} on success, {\"error\": ...} on failure.
    """
    db = _get_db()
    core = _core()

    result = _safe(
        core.update_issue,
        db,
        id,
        title=title,
        description=description,
        status=status,
        priority=priority,
        assignee=assignee,
        agent=agent,
        model=model,
        blocked_by=_split_csv(blocked_by),
        linked_to=_split_csv(linked_to),
        parent_id=parent_id,
        scheduled_at=scheduled_at,
        recurrence=recurrence,
        clear_agent=clear_agent,
        clear_model=clear_model,
        clear_scheduled_at=clear_scheduled_at,
        clear_recurrence=clear_recurrence,
    )
    if isinstance(result, dict) and "error" in result:
        return result
    updated_row, changes = result
    return {"issue": updated_row, "changes": changes}


@mcp.tool()
def close_issue(
    id: str,
    resolution: str = "Completed",
    status: str = "done",
    files: Optional[str] = None,
    refs: Optional[str] = None,
) -> dict:
    """Close an issue as done or cancelled.

    Args:
        id: Issue ID to close (required).
        resolution: Human-readable reason / summary of what was done.
        status: Terminal status — 'done' (default) or 'cancelled'.
        files: Comma-separated file paths modified (recorded in the closing event).
        refs: Comma-separated doc/spec references (recorded in the closing event).

    Returns the closed issue dict.  If the issue has a recurrence, also
    returns _next_issue_id and _next_scheduled_at for the auto-spawned ticket.
    """
    db = _get_db()
    core = _core()
    return _safe(
        core.close_issue,
        db,
        id,
        resolution=resolution,
        status=status,
        files=_split_csv(files),
        refs=_split_csv(refs),
    )


@mcp.tool()
def comment_issue(
    id: str,
    message: str,
    status: Optional[str] = None,
    files: Optional[str] = None,
    refs: Optional[str] = None,
) -> dict:
    """Append a comment to an issue, optionally changing its status.

    Args:
        id: Issue ID (required).
        message: Comment text (required).
        status: If set, transition the issue to this status after commenting.
                Useful for progress updates ('in_progress') or closing notes ('done').
        files: Comma-separated file paths to record in the comment event.
        refs: Comma-separated doc references to record in the comment event.

    Returns the updated issue dict.
    """
    db = _get_db()
    core = _core()
    return _safe(
        core.add_comment,
        db,
        id,
        message,
        status=status,
        files=_split_csv(files),
        refs=_split_csv(refs),
    )


@mcp.tool()
def board() -> dict:
    """Return the full board state as structured data.

    Mirrors the CLI 'board' command but returns machine-readable dicts
    instead of printed text.

    Returns a dict with keys:
    - epics: List of open epics with open_children count.
    - scheduled_this_week: Issues scheduled within the next 7 days (or overdue).
    - in_progress: Issues currently being worked on.
    - todo: Issues waiting to be started.
    """
    db = _get_db()
    return _board_data(db)


@mcp.tool()
def search(query: str) -> list:
    """Full-text search across issue titles and descriptions.

    Uses FTS5 when available, falls back to LIKE search.

    Args:
        query: Search string. Supports FTS5 syntax (e.g. 'auth OR login').

    Returns up to 20 matching issues as dicts.
    """
    db = _get_db()
    core = _core()
    return _safe(core.search_issues, db, query)


@mcp.tool()
def context() -> dict:
    """Return the current session context — active work + what's due soon.

    Mirrors the CLI 'context' command but as structured data.

    Returns a dict with keys:
    - active: Issues that are in_progress OR todo-with-blockers (highest priority first).
    - due_soon: Scheduled issues past due or within the next 24 hours.
    - upcoming_this_week: Scheduled issues coming up later this week.
    - recent_activity: Last 10 events across all issues (most recent first).

    Use this at the start of a session to decide what to work on next.
    """
    db = _get_db()
    return _context_data(db)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the runloq MCP server over stdio (default transport)."""
    mcp.run()


if __name__ == "__main__":
    main()
