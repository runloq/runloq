"""Pure-function API for the tracker engine — shared by CLI (prism.py) and FastAPI dashboard (prism/dashboard).

These functions take a sqlite3.Connection (caller-managed) plus keyword args and
return dicts. They contain ALL business rules (cascades, recurrence spawning,
field invariants). The CLI cmd_* shims and the FastAPI routes both call these.

No argparse, no print statements, no input() — pure logic only.
"""
from __future__ import annotations

import difflib
import importlib.util
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import List, Optional

# Load prism/prism.py (the CLI script) as a module under a unique name so the
# import doesn't resolve to the surrounding 'prism' package. The package
# (`prism/__init__.py`) is empty; the actual VALID_* constants, _normalize_*
# helpers, init_db, etc. all live in prism/prism.py. Using importlib avoids
# the sys.modules cache collision that would leave T._normalize_project missing.
_prism_path = os.path.join(os.path.dirname(__file__), "prism.py")
_spec = importlib.util.spec_from_file_location("prism_cli", _prism_path)
T = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(T)


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a sqlite3.Row to a dict, parsing JSON-stored list fields."""
    d = dict(row)
    for key in ("blocked_by", "linked_to"):
        if key in d:
            try:
                d[key] = json.loads(d[key]) if d[key] else []
            except (json.JSONDecodeError, TypeError):
                d[key] = []
    return d


def _checkpoint(db: sqlite3.Connection) -> None:
    """Truncate the WAL after a write so the .db-wal file stays at zero bytes.

    Keeps the autosave Stop hook clean — it commits runloq.db only and
    doesn't need to chase the WAL sidecar files. Cheap on a small DB
    (<10MB) and runs at most once per business operation.
    """
    try:
        db.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    except sqlite3.OperationalError:
        # Best-effort; if the DB isn't in WAL mode (e.g. test injection),
        # this PRAGMA is a no-op error.
        pass


# Agents directory — resolved from config so `runloq.config.toml` can override it.
# Returns None when no [agents] dir is configured (validation then emits a
# helpful error rather than silently skipping).
def _get_agents_dir() -> Optional[str]:
    """Return the agents directory from config, or None if not configured."""
    try:
        try:
            from config import load_config
        except ModuleNotFoundError:  # package context (dashboard via PYTHONPATH)
            from prism.config import load_config
        cfg = load_config()
        return cfg.agents_dir  # May be None when [agents] dir is absent
    except Exception:
        return None


_AGENTS_DIR = _get_agents_dir()


def _validate_agent_slug(slug: str, agents_dir: Optional[str] = None) -> None:
    """Raise ValueError if `slug` has no matching file in the agents directory.

    Skipped when TRACKER_SKIP_AGENT_VALIDATION=1 is set in the environment.
    On miss, suggests the closest known slug via difflib.get_close_matches.

    When `agents_dir` is not provided, reads the module-level `_AGENTS_DIR`
    attribute (tests patch this to point at a temp dir with known slugs).
    """
    if agents_dir is None:
        # Read the module-level attribute — tests patch core._AGENTS_DIR directly.
        import core as _self
        agents_dir = _self._AGENTS_DIR
    if os.environ.get("TRACKER_SKIP_AGENT_VALIDATION") == "1":
        return
    if agents_dir is None or not os.path.isdir(agents_dir):
        # agents_dir is None → not configured at all.  Emit a helpful error
        # so users know what config key to set, rather than silently skipping.
        if agents_dir is None:
            raise ValueError(
                f"Agent slug '{slug}' was specified but no agents directory is "
                f"configured.  Add an [agents] dir = \"<path>\" entry to your "
                f"runloq.config.toml (or set TRACKER_SKIP_AGENT_VALIDATION=1 to "
                f"skip this check)."
            )
        # Directory path is configured but doesn't exist on disk — skip validation
        # (e.g. CI environment, fresh clone, test isolation).
        return
    agent_file = os.path.join(agents_dir, f"{slug}.md")
    if os.path.isfile(agent_file):
        return
    # Build the known-slug list and suggest close matches.
    known = [
        os.path.splitext(f)[0]
        for f in os.listdir(agents_dir)
        if f.endswith(".md")
    ]
    suggestions = difflib.get_close_matches(slug, known, n=3, cutoff=0.5)
    hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
    raise ValueError(
        f"Unknown agent slug '{slug}' — no file at .claude/agents/{slug}.md.{hint}"
    )


def create_issue(
    db: sqlite3.Connection,
    *,
    title: str,
    project: str = "SYS",
    type: str = "issue",
    priority: str = "P1",
    assignee: str = "claude",
    agent: Optional[str] = None,
    model: Optional[str] = None,
    description: Optional[str] = None,
    blocked_by: Optional[List[str]] = None,
    linked_to: Optional[List[str]] = None,
    parent_id: Optional[str] = None,
    scheduled_at: Optional[str] = None,
    recurrence: Optional[str] = None,
    status: Optional[str] = None,
) -> dict:
    """Create a new issue. Mirrors cmd_create's behavior including:

    - ID generation via T.next_id (collision-safe retry loop)
    - scheduled_at flipping status to 'scheduled'
    - T._normalize_claude_fields enforcing agent/model only when assignee=claude
    - default model='opus' for claude tasks
    - emitting a 'created' event

    Returns the inserted row as a dict with blocked_by and linked_to as lists.

    NOTE: Description enforcement (mandatory for tasks) is a CLI-level concern;
    this function accepts an empty/None description so the FastAPI layer can
    apply its own validation rules.
    """
    now = datetime.now(timezone.utc).isoformat()

    # Validate agent slug early (before any DB work) so typos are caught at the
    # boundary. Only meaningful for claude tasks; non-claude assignees have their
    # agent cleared by _normalize_claude_fields anyway.
    if agent and assignee == "claude":
        _validate_agent_slug(agent)

    # Normalize project prefix.
    prefix = T._normalize_project(project)

    # Resolve issue_type.
    issue_type = type  # kwarg name is 'type' to match the plan signature
    if issue_type not in ("issue", "epic"):
        raise ValueError(f"issue_type must be 'issue' or 'epic' (got {issue_type!r})")

    # Determine raw_model default: epics never have a model; tasks default to 'opus'.
    raw_model = model if model is not None else (None if issue_type == "epic" else "opus")

    # Enforce agent/model only for claude tasks.
    norm_agent, norm_model = T._normalize_claude_fields(
        assignee, agent, raw_model, issue_type
    )

    # Serialize linked_to.
    if linked_to:
        linked_to_json = json.dumps([s for s in linked_to if s])
    else:
        linked_to_json = "[]"

    # Serialize blocked_by.
    if blocked_by:
        blocked_by_json = json.dumps([s for s in blocked_by if s])
    else:
        blocked_by_json = "[]"

    # Parse and validate scheduled_at.
    parsed_scheduled_at = None
    if scheduled_at:
        parsed_scheduled_at = T._parse_scheduled_at(scheduled_at)

    # Determine status: explicit kwarg wins, otherwise scheduled_at flips it,
    # otherwise default 'todo'. Mirrors original cmd_create behavior.
    if status is None:
        status = "scheduled" if parsed_scheduled_at else "todo"

    # Collision-safe ID assignment.
    max_attempts = 100
    issue_id = None
    desc_value = (description or "").strip()
    for attempt in range(max_attempts):
        candidate = T.next_id(db, prefix)
        existing = db.execute("SELECT 1 FROM issues WHERE id=?", (candidate,)).fetchone()
        if existing is not None:
            T._log_counter_event(
                db, "counter_bump",
                f"Collision on {candidate} — counter advanced, retrying (attempt {attempt + 1})",
                {"prefix": prefix, "collided_id": candidate, "attempt": attempt + 1},
            )
            continue
        try:
            db.execute(
                """INSERT INTO issues (id, title, description, status, priority,
                      assignee, agent, model, linked_to, blocked_by, parent_id,
                      issue_type, scheduled_at, recurrence, created_at, updated_at)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    candidate,
                    title,
                    desc_value,
                    status,
                    priority,
                    assignee,
                    norm_agent,
                    norm_model,
                    linked_to_json,
                    blocked_by_json,
                    parent_id,
                    issue_type,
                    parsed_scheduled_at,
                    recurrence,
                    now,
                    now,
                ),
            )
            issue_id = candidate
            break
        except sqlite3.IntegrityError:
            # Another process inserted the same PK in the window between our
            # SELECT and INSERT.  Advance the counter and retry.
            T._log_counter_event(
                db, "counter_bump",
                f"IntegrityError on {candidate} — retrying (attempt {attempt + 1})",
                {"prefix": prefix, "collided_id": candidate, "attempt": attempt + 1},
            )
    else:
        raise RuntimeError(
            f"Could not find a free ID for prefix {prefix} after {max_attempts} attempts"
        )

    create_msg = f"Created: {title}"
    if status == "scheduled" and parsed_scheduled_at:
        create_msg += f" (scheduled for {parsed_scheduled_at[:16].replace('T', ' ')}"
        if recurrence:
            create_msg += f", recurs {recurrence}"
        create_msg += ")"

    db.execute(
        "INSERT INTO events (issue_id, type, message, created_at) VALUES (?,?,?,?)",
        (issue_id, "created", create_msg, now),
    )
    db.commit()
    _checkpoint(db)

    # Regenerate board HTML silently (same as cmd_create).

    # Return the full row as a dict.
    row = db.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
    return _row_to_dict(row)


VALID_STATUSES = ("todo", "in_progress", "scheduled", "done", "cancelled")
TERMINAL_STATUSES = ("done", "cancelled")
VALID_RECURRENCE = ("daily", "weekly", "biweekly", "monthly")


def update_issue(
    db: sqlite3.Connection,
    issue_id: str,
    *,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    assignee: Optional[str] = None,
    agent: Optional[str] = None,
    model: Optional[str] = None,
    type: Optional[str] = None,  # 'issue' or 'epic' — issue_type alias
    blocked_by: Optional[List[str]] = None,
    linked_to: Optional[List[str]] = None,
    parent_id: Optional[str] = None,
    scheduled_at: Optional[str] = None,
    recurrence: Optional[str] = None,
    resolution: Optional[str] = None,
    closed_at: Optional[str] = None,
    clear_agent: bool = False,
    clear_model: bool = False,
    clear_scheduled_at: bool = False,
    clear_recurrence: bool = False,
) -> tuple[dict, List[str]]:
    """Update an issue with full invariant enforcement.

    Returns (updated_row_dict, changes_list). `changes` is empty if nothing
    changed (caller can treat as a no-op).

    Raises:
        KeyError: issue_id not found
        ValueError: validation failure (bad status/recurrence, invariant violation, etc.)

    Mirrors cmd_update's behavior verbatim:
    - status/scheduled_at coupling: scheduled_at without status implies status=scheduled;
      moving status off scheduled clears scheduled_at; status=scheduled requires a datetime
    - agent/model invariant: cleared on non-claude assignee or epic; rejected if explicitly set
    - terminal status stamps closed_at (and resolution=None when leaving terminal)
    - recurrence requires scheduled_at; cleared silently if scheduled_at is dropped
    - cascade_blocked_by on status='done'
    """
    row = db.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
    if row is None:
        raise KeyError(issue_id)

    updates: List[str] = []
    params: List = []
    changes: List[str] = []
    now = datetime.now(timezone.utc).isoformat()

    if status is not None and status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {', '.join(VALID_STATUSES)}")

    # Normalize scheduled_at first so downstream status logic can see it.
    new_scheduled_at = None
    scheduled_changed = False
    if scheduled_at:
        new_scheduled_at = T._parse_scheduled_at(scheduled_at)
        scheduled_changed = (new_scheduled_at != row["scheduled_at"])
    elif clear_scheduled_at:
        new_scheduled_at = None
        scheduled_changed = (row["scheduled_at"] is not None)

    # Implicit status flip when scheduled_at is being set on a non-scheduled,
    # non-terminal ticket and caller didn't pass status.
    if (scheduled_changed and new_scheduled_at and status is None
            and row["status"] not in ("scheduled",) + TERMINAL_STATUSES):
        status = "scheduled"

    # Conversely: moving status out of scheduled clears scheduled_at if the
    # caller didn't explicitly touch it.
    if (status is not None and status != "scheduled"
            and row["status"] == "scheduled"
            and not scheduled_at and not clear_scheduled_at
            and row["scheduled_at"]):
        new_scheduled_at = None
        scheduled_changed = True

    if status == "scheduled":
        effective = new_scheduled_at if scheduled_changed else row["scheduled_at"]
        if not effective:
            raise ValueError("status='scheduled' requires --scheduled-at")

    # Validate agent slug before any DB work. The effective assignee after this
    # update determines whether agent is even applicable — skip when the result
    # would clear agent anyway (non-claude assignee or epic).
    if agent:
        effective_assignee = assignee if assignee is not None else row["assignee"]
        effective_type = type if type is not None else row["issue_type"]
        if effective_assignee == "claude" and effective_type != "epic":
            _validate_agent_slug(agent)

    # Plain-field updates (status/priority/title/description/assignee/agent/model).
    field_kwargs = {
        "status": status, "priority": priority, "title": title,
        "description": description, "assignee": assignee, "agent": agent,
        "model": model,
    }
    for field, value in field_kwargs.items():
        if value is not None and value != row[field]:
            updates.append(f"{field}=?"); params.append(value)
            changes.append(f"{field}: {row[field]} → {value}")

    # Enforce agent/model invariant on assignee/type changes.
    new_assignee = assignee if assignee is not None else row["assignee"]
    new_type = type if type is not None else row["issue_type"]
    if new_assignee != "claude" or new_type == "epic":
        if row["agent"] is not None and agent is None:
            updates.append("agent=?"); params.append(None)
            changes.append(f"agent: {row['agent']} → (cleared, assignee={new_assignee})")
        if row["model"] is not None and model is None:
            updates.append("model=?"); params.append(None)
            changes.append(f"model: {row['model']} → (cleared, assignee={new_assignee})")
        if agent:
            raise ValueError(f"agent is only valid when assignee=claude (got {new_assignee})")
        if model:
            raise ValueError(f"model is only valid when assignee=claude (got {new_assignee})")

    # type alias for issue_type.
    if type is not None and type != row["issue_type"]:
        if type not in ("issue", "epic"):
            raise ValueError("issue_type must be 'issue' or 'epic'")
        updates.append("issue_type=?"); params.append(type)
        changes.append(f"issue_type: {row['issue_type']} → {type}")

    # Explicit clears.
    already = {u.split("=", 1)[0] for u in updates}
    if clear_agent and "agent" not in already and row["agent"] is not None:
        updates.append("agent=?"); params.append(None)
        changes.append(f"agent: {row['agent']} → (cleared)")
    if clear_model and "model" not in already and row["model"] is not None:
        updates.append("model=?"); params.append(None)
        changes.append(f"model: {row['model']} → (cleared)")

    # List-typed fields (caller passes lists; we serialize to JSON).
    if blocked_by is not None:
        updates.append("blocked_by=?"); params.append(json.dumps(blocked_by))
        changes.append(f"blocked_by: {','.join(blocked_by) if blocked_by else '[]'}")
    if linked_to is not None:
        updates.append("linked_to=?"); params.append(json.dumps(linked_to))
        changes.append(f"linked_to: {','.join(linked_to) if linked_to else '[]'}")
    if parent_id is not None:
        updates.append("parent_id=?"); params.append(parent_id)
        changes.append(f"parent: {parent_id}")
    if resolution is not None:
        updates.append("resolution=?"); params.append(resolution)
        changes.append(f"resolution: {resolution}")

    # Terminal-state lifecycle: stamp/clear closed_at + resolution.
    transitioning_to_terminal = (
        status in TERMINAL_STATUSES and row["status"] not in TERMINAL_STATUSES
    )
    transitioning_out_of_terminal = (
        status is not None and status not in TERMINAL_STATUSES
        and row["status"] in TERMINAL_STATUSES
    )
    if transitioning_to_terminal and not closed_at:
        updates.append("closed_at=?"); params.append(now)
        changes.append("closed_at: (stamped)")
    elif closed_at:
        updates.append("closed_at=?"); params.append(closed_at)
        changes.append(f"closed_at: {closed_at}")
    if transitioning_out_of_terminal:
        updates.append("closed_at=?"); params.append(None)
        changes.append("closed_at: (cleared)")
        if resolution is None and row["resolution"]:
            updates.append("resolution=?"); params.append(None)
            changes.append("resolution: (cleared)")

    # scheduled_at change.
    if scheduled_changed:
        updates.append("scheduled_at=?"); params.append(new_scheduled_at)
        old_disp = row["scheduled_at"][:16].replace("T", " ") if row["scheduled_at"] else "(none)"
        new_disp = new_scheduled_at[:16].replace("T", " ") if new_scheduled_at else "(cleared)"
        changes.append(f"scheduled_at: {old_disp} → {new_disp}")

    # Recurrence is the ticket's identity as a recurring job — it must survive
    # the scheduled -> in_progress pickup (which clears scheduled_at) so that
    # close_issue can spawn the next iteration. We only block an *explicit*
    # attempt to set recurrence on a ticket that has no scheduling anchor; an
    # existing recurrence is preserved even after scheduled_at is dropped.
    new_recurrence = row["recurrence"]
    recurrence_changed = False
    if recurrence is not None:
        if recurrence not in VALID_RECURRENCE:
            raise ValueError(
                f"recurrence must be one of {', '.join(VALID_RECURRENCE)} (got {recurrence!r})"
            )
        new_recurrence = recurrence
        recurrence_changed = (recurrence != row["recurrence"])
    elif clear_recurrence:
        new_recurrence = None
        recurrence_changed = (row["recurrence"] is not None)
    effective_scheduled_at = new_scheduled_at if scheduled_changed else row["scheduled_at"]
    if new_recurrence and not effective_scheduled_at and recurrence_changed:
        raise ValueError(
            "recurrence requires scheduled_at (recurrence is only meaningful on scheduled tickets)"
        )
    if recurrence_changed:
        updates.append("recurrence=?"); params.append(new_recurrence)
        old_disp = row["recurrence"] or "(none)"
        new_disp = new_recurrence or "(cleared)"
        changes.append(f"recurrence: {old_disp} → {new_disp}")

    if not updates:
        return _row_to_dict(row), []

    updates.append("updated_at=?"); params.append(now)
    params.append(issue_id)
    db.execute(f"UPDATE issues SET {', '.join(updates)} WHERE id=?", params)
    db.execute(
        "INSERT INTO events (issue_id, type, message, created_at) VALUES (?,?,?,?)",
        (issue_id, "updated", "; ".join(changes), now),
    )
    db.commit()

    if status == "done":
        T.cascade_blocked_by(db, issue_id)

    _checkpoint(db)

    new_row = db.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
    return _row_to_dict(new_row), changes


def close_issue(
    db: sqlite3.Connection,
    issue_id: str,
    *,
    status: str = "done",
    resolution: Optional[str] = None,
    files: Optional[List[str]] = None,
    refs: Optional[List[str]] = None,
) -> dict:
    """Close an issue (terminal state). Mirrors cmd_close behavior:

    - status must be 'done' or 'cancelled' (anything else raises ValueError)
    - resolution defaults to 'Completed'
    - files/refs go into the closing event metadata
    - cascades blocked_by removal across linked tickets
    - on `done` close, auto-spawns the next iteration if the closing ticket
      has a recurrence; the next scheduled_at is advanced from the closing
      ticket's scheduled_at when present, else from the close time (the ticket
      was picked up, which clears scheduled_at). The new ticket inherits the
      brief and links back via linked_to=[just-closed-id]

    Returns the closed row as a dict with two extra keys:
    - `_next_issue_id`: id of the auto-spawned ticket, or None
    - `_next_scheduled_at`: scheduled_at of the auto-spawned ticket, or None

    Raises:
        KeyError: issue_id not found
        ValueError: bad terminal status
    """
    if status not in TERMINAL_STATUSES:
        raise ValueError(f"close status must be 'done' or 'cancelled' (got '{status}')")

    closing_row = db.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
    if closing_row is None:
        raise KeyError(issue_id)
    closing_row = dict(closing_row)

    now = datetime.now(timezone.utc).isoformat()
    res = resolution or "Completed"
    metadata = {}
    if files:
        metadata["files"] = list(files)
    if refs:
        metadata["refs"] = list(refs)

    db.execute(
        "UPDATE issues SET status=?, closed_at=?, resolution=?, updated_at=? WHERE id=?",
        (status, now, res, now, issue_id),
    )
    verb = "Closed" if status == "done" else "Cancelled"
    db.execute(
        "INSERT INTO events (issue_id, type, message, metadata, created_at) VALUES (?,?,?,?,?)",
        (issue_id, "closed", f"{verb}: {res}", json.dumps(metadata), now),
    )
    db.commit()

    next_issue_id = None
    next_scheduled_at = None
    if status == "done" and closing_row.get("recurrence"):
        # Advance from the original scheduled_at when it's still present (direct
        # close from `scheduled` — preserves time-of-day). When the ticket was
        # picked up, in_progress cleared scheduled_at, so fall back to the close
        # time and advance one interval out — the chain still survives.
        base = closing_row.get("scheduled_at") or now
        try:
            next_scheduled_at = T._advance_scheduled_at(base, closing_row["recurrence"])
        except ValueError:
            next_scheduled_at = None
        if next_scheduled_at:
            prefix = T._project_of_id(issue_id)
            for _ in range(100):
                candidate = T.next_id(db, prefix)
                if db.execute(
                    "SELECT 1 FROM issues WHERE id=?", (candidate,)
                ).fetchone() is None:
                    next_issue_id = candidate
                    break
            if next_issue_id:
                linked = [issue_id]
                db.execute(
                    """INSERT INTO issues (id, title, description, status, priority,
                          assignee, agent, model, linked_to, issue_type,
                          scheduled_at, recurrence, created_at, updated_at)
                          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (next_issue_id,
                     closing_row["title"],
                     closing_row["description"],
                     "scheduled",
                     closing_row["priority"],
                     closing_row["assignee"],
                     closing_row["agent"],
                     closing_row["model"],
                     json.dumps(linked),
                     closing_row["issue_type"],
                     next_scheduled_at,
                     closing_row["recurrence"],
                     now, now),
                )
                db.execute(
                    "INSERT INTO events (issue_id, type, message, created_at) VALUES (?,?,?,?)",
                    (next_issue_id, "created",
                     f"Auto-spawned from {issue_id} ({closing_row['recurrence']} recurrence) — scheduled for {next_scheduled_at[:16].replace('T', ' ')}",
                     now),
                )
                db.execute(
                    "INSERT INTO events (issue_id, type, message, created_at) VALUES (?,?,?,?)",
                    (issue_id, "spawned_next",
                     f"Spawned {next_issue_id} for next iteration ({closing_row['recurrence']}, scheduled for {next_scheduled_at[:16].replace('T', ' ')})",
                     now),
                )
                db.commit()

    T.cascade_blocked_by(db, issue_id)
    _checkpoint(db)

    closed = db.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
    result = _row_to_dict(closed)
    result["_next_issue_id"] = next_issue_id
    result["_next_scheduled_at"] = next_scheduled_at
    return result


def add_comment(
    db: sqlite3.Connection,
    issue_id: str,
    message: str,
    *,
    status: Optional[str] = None,
    files: Optional[List[str]] = None,
    refs: Optional[List[str]] = None,
) -> dict:
    """Append a comment event to an issue. Optionally transition status.

    Returns the (possibly updated) issue row as a dict.

    Raises:
        KeyError: issue_id not found
        ValueError: invalid status value
    """
    if status is not None and status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {', '.join(VALID_STATUSES)}")

    row = db.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
    if row is None:
        raise KeyError(issue_id)

    now = datetime.now(timezone.utc).isoformat()
    metadata = {}
    if files:
        metadata["files"] = list(files)
    if refs:
        metadata["refs"] = list(refs)

    db.execute(
        "INSERT INTO events (issue_id, type, message, metadata, created_at) VALUES (?,?,?,?,?)",
        (issue_id, "comment", message, json.dumps(metadata), now),
    )
    db.execute("UPDATE issues SET updated_at=? WHERE id=?", (now, issue_id))

    if status and status != row["status"]:
        updates = ["status=?", "updated_at=?"]
        params: List = [status, now]
        if status == "done":
            updates.append("closed_at=?"); params.append(now)
            updates.append("resolution=?"); params.append(message)
        params.append(issue_id)
        db.execute(f"UPDATE issues SET {', '.join(updates)} WHERE id=?", params)
        db.execute(
            "INSERT INTO events (issue_id, type, message, created_at) VALUES (?,?,?,?)",
            (issue_id, "updated", f"status: {row['status']} → {status}", now),
        )

    db.commit()
    _checkpoint(db)

    new_row = db.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
    return _row_to_dict(new_row)


def search_issues(db: sqlite3.Connection, query: str) -> List[dict]:
    """FTS5 search across title + description, falling back to LIKE.

    Returns up to 20 matching issues as dicts (full rows, not just snippets).

    FTS5 MATCH raises sqlite3.OperationalError on inputs containing special
    characters that are invalid FTS5 syntax (e.g. hyphenated ticket IDs like
    hyphenated IDs, apostrophes, bare operators, unclosed quotes).  When that
    happens we fall through immediately to the LIKE branch rather than
    propagating the error to callers.
    """
    rows: list = []
    try:
        rows = db.execute(
            """SELECT i.* FROM issues_fts f JOIN issues i ON f.rowid = i.rowid
               WHERE issues_fts MATCH ? ORDER BY rank LIMIT 20""",
            (query,),
        ).fetchall()
    except sqlite3.OperationalError:
        pass  # Invalid FTS5 syntax — fall through to LIKE fallback below
    if not rows:
        rows = db.execute(
            """SELECT * FROM issues
               WHERE title LIKE ? OR description LIKE ? LIMIT 20""",
            (f"%{query}%", f"%{query}%"),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_events(
    db: sqlite3.Connection,
    issue_id: Optional[str] = None,
    *,
    types: Optional[List[str]] = None,
    limit: int = 100,
) -> List[dict]:
    """Return events for an issue (or all if issue_id is None) ordered ASC by time.

    `types` filters by event type. `limit` caps the result size.
    """
    where, params = [], []
    if issue_id:
        where.append("issue_id=?"); params.append(issue_id)
    if types:
        where.append(f"type IN ({','.join('?' * len(types))})")
        params.extend(types)
    clause = " AND ".join(where) if where else "1=1"
    rows = db.execute(
        f"SELECT * FROM events WHERE {clause} ORDER BY created_at ASC LIMIT ?",
        params + [limit],
    ).fetchall()
    return [dict(r) for r in rows]


def get_issue(db: sqlite3.Connection, issue_id: str) -> dict:
    """Return the full issue row as a dict. Raises KeyError if not found."""
    row = db.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
    if row is None:
        raise KeyError(issue_id)
    return _row_to_dict(row)


def list_issues(
    db: sqlite3.Connection,
    *,
    status: Optional[List[str]] = None,
    project: Optional[List[str]] = None,
    priority: Optional[List[str]] = None,
    assignee: Optional[List[str]] = None,
    agent: Optional[List[str]] = None,
    model: Optional[List[str]] = None,
    type: Optional[List[str]] = None,
    include_epics: bool = False,
    blocked_only: bool = False,
    scheduled_window: Optional[str] = None,
    parent_id: Optional[str] = None,
) -> List[dict]:
    """List issues with optional filters. Returns rows as dicts.

    Default filters (matching cmd_list):
    - excludes done/cancelled unless `status` explicitly includes them
    - excludes epics unless `include_epics=True` or `type` includes 'epic'

    Filter args are lists and behave as OR within a list, AND across lists.
    `scheduled_window`: 'due' (past or within 24h), 'this_week' (within 7d), 'all'.
    `blocked_only`: only rows with non-empty blocked_by list.
    """
    from datetime import timedelta

    where: List[str] = []
    params: List = []

    if status:
        where.append(f"status IN ({','.join('?' * len(status))})")
        params.extend(status)
    else:
        where.append("status NOT IN ('done','cancelled')")

    if priority:
        where.append(f"priority IN ({','.join('?' * len(priority))})")
        params.extend(priority)

    if assignee:
        where.append(f"assignee IN ({','.join('?' * len(assignee))})")
        params.extend(assignee)

    if agent:
        where.append(f"agent IN ({','.join('?' * len(agent))})")
        params.extend(agent)

    if model:
        where.append(f"model IN ({','.join('?' * len(model))})")
        params.extend(model)

    if project:
        prefixes = [T._normalize_project(p) for p in project]
        like_clauses = " OR ".join("id LIKE ?" for _ in prefixes)
        where.append(f"({like_clauses})")
        params.extend(f"{p}-%" for p in prefixes)

    if type:
        where.append(f"issue_type IN ({','.join('?' * len(type))})")
        params.extend(type)
    elif not include_epics:
        where.append("issue_type='issue'")

    if parent_id is not None:
        if parent_id.lower() in ("none", "null", ""):
            where.append("parent_id IS NULL")
        else:
            where.append("parent_id = ?")
            params.append(parent_id)

    if scheduled_window in ("due", "this_week", "all"):
        if scheduled_window == "due":
            cutoff = (datetime.now() + timedelta(hours=24)).isoformat()
            where.append("scheduled_at IS NOT NULL AND scheduled_at <= ?")
            params.append(cutoff)
        elif scheduled_window == "this_week":
            cutoff = (datetime.now() + timedelta(days=7)).isoformat()
            where.append("scheduled_at IS NOT NULL AND scheduled_at <= ?")
            params.append(cutoff)
        elif scheduled_window == "all":
            where.append("scheduled_at IS NOT NULL")

    clause = " AND ".join(where) if where else "1=1"
    rows = db.execute(
        f"""SELECT * FROM issues WHERE {clause}
            ORDER BY
              CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END,
              updated_at DESC""",
        params,
    ).fetchall()

    result = [_row_to_dict(r) for r in rows]

    if blocked_only:
        result = [r for r in result if r.get("blocked_by")]

    return result
