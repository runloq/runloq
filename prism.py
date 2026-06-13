#!/usr/bin/env python3
"""
runloq — local-first issue tracker + context engine for AI coding agents.

SQLite-backed with FTS5 search, event logging, and context snapshots.
The .db is the single source of truth (no markdown projection).

Status values: todo · in_progress · scheduled · done · cancelled (that's the whole set).
Blockers are captured on the `blocked_by` attribute — there is no `blocked` status.
`scheduled` tickets carry a `scheduled_at` datetime; they sit dormant until that
time arrives, at which point the context command surfaces them as "due now or soon".
A scheduled ticket can also carry a `recurrence` (daily|weekly|biweekly|monthly).
On `close --status done`, runloq auto-spawns the next iteration as a fresh
scheduled ticket with the same brief, advanced by the recurrence interval, and
linked back to the closed one for context. `cancelled` ends the chain.
`agent` and `model` only apply when assignee=claude; they are auto-cleared on
human-assigned tickets.

Usage:
    runloq create "title" [--type issue|epic] [--priority P1] [--project SYS] [--assignee alice] [--agent frontend-dev] [--model sonnet] [--linked_to SYS-001] [--scheduled-at YYYY-MM-DD[THH:MM]] [--recurrence daily|weekly|biweekly|monthly]
    runloq list [--status todo,in_progress,scheduled] [--priority P0,P1] [--assignee alice] [--project SYS] [--type epic|task] [--include-epics]
    runloq update ID [--status done] [--type issue|epic] [--priority P0] [--assignee bob] [--agent cto] [--model haiku] [--clear-agent] [--clear-model] [--blocked_by SYS-001] [--linked_to SYS-002] [--resolution "why closed"] [--closed_at YYYY-MM-DD] [--scheduled-at YYYY-MM-DD[THH:MM]] [--clear-scheduled-at] [--recurrence daily|weekly|biweekly|monthly] [--clear-recurrence]
    runloq close ID [--resolution "why"] [--status done|cancelled] [--files a.ts,b.ts] [--refs doc1]
    runloq show ID
    runloq board
    runloq search "query"
    runloq comment ID "message" [--status done] [--files path1,path2] [--refs doc1,doc2]
    runloq log ID "message"
    runloq events [--issue ID] [--type file_edit,commit] [--last 20]
    runloq snapshot [--reason "pre-compact"]
    runloq recover [--snapshot-id N]
    runloq context [--issue ID]
    runloq stats
    runloq init [--demo]
    runloq seed [--force]
    runloq track file_edit "path/to/file" [--issue ID]
    runloq track commit "hash" "message" [--issue ID]
    runloq track tool_output "tool_name" --size 1234 [--issue ID]
    runloq track session_start
    runloq track session_end
    runloq timer start ID
    runloq timer stop [ID]
    runloq timer status
    runloq dashboard [--output path]
    runloq serve
    runloq purge [--before YYYY-MM-DD] [--status done,cancelled]
    runloq doctor [--fix]
    runloq rename ID "new title"
    runloq reassign-id OLD NEW
"""

import sqlite3
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from config import load_config as _load_config
except ModuleNotFoundError:  # imported as a package (e.g. dashboard via PYTHONPATH)
    from prism.config import load_config as _load_config

# ---------------------------------------------------------------------------
# Package-install compatibility shim
# ---------------------------------------------------------------------------
# When installed via pip (`import prism.prism`), the bare module names `core`
# and `config` are NOT on sys.path — only `prism.core` and `prism.config` are.
# Lazy `import core` statements scattered across this file would fail.
# We register them under their short names in sys.modules so that every
# later `import core` / `from config import …` resolves to the same objects.
# This is equivalent to `sys.path.insert(0, <package_dir>)` but scoped to
# just these two modules, leaving sys.path clean.
if "core" not in sys.modules or "config" not in sys.modules:
    _pkg_parent = os.path.dirname(os.path.abspath(__file__))
    if _pkg_parent not in sys.path:
        # Running as installed package: prism.py is inside site-packages/prism/
        # and core.py / config.py are siblings — adding the dir lets bare imports
        # resolve naturally.  When running from source checkout (already on path),
        # this is a no-op because the dir is already present.
        sys.path.insert(0, _pkg_parent)
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))

# STATE_DIR and DB_PATH are resolved through the config system so that
# env vars (RUNLOQ_STATE_DIR / RUNLOQ_DB, legacy TRACKER_*) and runloq.config.toml all work.
# We expose module-level names for backward compatibility (tests, main.py, etc.).
def _cfg():
    """Return the current PrismConfig (cached per process)."""
    return _load_config()

@property  # type: ignore[misc]  # used on module-level via __getattr__ trick below
def _state_dir_prop():
    return _cfg().state_dir

# Module-level attribute proxies so existing code that reads STATE_DIR / DB_PATH
# still works.  Evaluated lazily via __getattr__ on this module.
STATE_DIR = _cfg().state_dir
DB_PATH = _cfg().db


def get_db():
    # Read the module-level DB_PATH each call (not at function-definition time)
    # so tests that patch T.DB_PATH = "/tmp/x.db" see the patched path.
    # DB_PATH is initialized from config at import time but stays mutable.
    db = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=30000")
    return db

def init_db(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS issues (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'todo'
                CHECK(status IN ('todo','in_progress','scheduled','done','cancelled')),
            priority TEXT NOT NULL DEFAULT 'P1'
                CHECK(priority IN ('P0','P1','P2','P3')),
            blocked_by TEXT DEFAULT '[]',
            parent_id TEXT REFERENCES issues(id),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            closed_at TEXT,
            resolution TEXT,
            time_spent_min INTEGER DEFAULT 0,
            md_hash TEXT,
            assignee TEXT DEFAULT 'claude',
            agent TEXT,
            model TEXT DEFAULT 'opus',
            linked_to TEXT DEFAULT '[]',
            scheduled_at TEXT,
            recurrence TEXT
                CHECK(recurrence IS NULL OR recurrence IN ('daily','weekly','biweekly','monthly'))
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_id TEXT REFERENCES issues(id),
            type TEXT NOT NULL,
            message TEXT NOT NULL,
            metadata TEXT DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reason TEXT NOT NULL,
            active_issues TEXT NOT NULL,
            recent_events TEXT NOT NULL,
            open_files TEXT DEFAULT '[]',
            git_branch TEXT,
            git_dirty_files TEXT DEFAULT '[]',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS timers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issue_id TEXT REFERENCES issues(id),
            started_at TEXT NOT NULL,
            stopped_at TEXT,
            duration_sec INTEGER
        );

        CREATE TABLE IF NOT EXISTS token_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_name TEXT NOT NULL,
            size INTEGER NOT NULL,
            issue_id TEXT REFERENCES issues(id),
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS counters (
            prefix TEXT PRIMARY KEY,
            next_id INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_issues_status ON issues(status);
        CREATE INDEX IF NOT EXISTS idx_issues_priority ON issues(priority);
        CREATE INDEX IF NOT EXISTS idx_events_issue ON events(issue_id);
        CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
        CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
        CREATE INDEX IF NOT EXISTS idx_timers_issue ON timers(issue_id);
        CREATE INDEX IF NOT EXISTS idx_token_stats_tool ON token_stats(tool_name);
    """)

    # FTS5 for full-text search across issues and events
    try:
        db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS issues_fts USING fts5(
                id, title, description,
                content=issues, content_rowid=rowid
            )
        """)
        db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
                message, metadata,
                content=events, content_rowid=rowid
            )
        """)
    except sqlite3.OperationalError:
        pass  # Already exists

    # Triggers to keep FTS in sync
    for tbl, fts, cols in [
        ("issues", "issues_fts", "id, title, description"),
        ("events", "events_fts", "message, metadata"),
    ]:
        for op, body in [
            ("INSERT", f"INSERT INTO {fts}(rowid, {cols}) VALUES (new.rowid, {'new.' + ', new.'.join(cols.split(', '))})"),
            ("DELETE", f"INSERT INTO {fts}({fts}, rowid, {cols}) VALUES('delete', old.rowid, {'old.' + ', old.'.join(cols.split(', '))})"),
            ("UPDATE", f"INSERT INTO {fts}({fts}, rowid, {cols}) VALUES('delete', old.rowid, {'old.' + ', old.'.join(cols.split(', '))}); INSERT INTO {fts}(rowid, {cols}) VALUES (new.rowid, {'new.' + ', new.'.join(cols.split(', '))})"),
        ]:
            try:
                db.execute(f"CREATE TRIGGER IF NOT EXISTS {tbl}_{op.lower()}_fts AFTER {op} ON {tbl} BEGIN {body}; END")
            except sqlite3.OperationalError:
                pass

    # If the issues / events tables already had data when init_db was called
    # (e.g. an old DB that pre-dates FTS, or a test that pre-populates rows
    # before init_db runs), the FTS index is empty but the triggers expect it
    # to mirror the source. The first UPDATE then fires a 'delete' for a
    # rowid FTS doesn't know about, which corrupts the FTS5 segment store
    # ("database disk image is malformed"). Seed FTS from existing data once
    # — `'rebuild'` is idempotent and effectively a no-op when FTS is already
    # in sync, so it's safe to run on every init.
    for fts in ("issues_fts", "events_fts"):
        try:
            db.execute(f"INSERT INTO {fts}({fts}) VALUES('rebuild')")
        except sqlite3.OperationalError:
            pass

    db.commit()


def migrate_db(db):
    """Add new columns if they don't exist (safe to run repeatedly).

    Also migrates away from:
      - retired `in_review` / `blocked` statuses → `todo`
      - retired `company` / `tags` columns (redundant with the ID prefix / unused)

    The CHECK constraint and column drops are applied by rebuilding the table
    if the old definition is still present (SQLite does not support ALTER CHECK
    and DROP COLUMN semantics are limited).
    """
    cursor = db.execute("PRAGMA table_info(issues)")
    existing_cols = {row[1] for row in cursor.fetchall()}

    # Migrate legacy `act_as` column to `agent` — one-time migration using SQLite 3.25+ RENAME COLUMN.
    # If both exist (interrupted migration), prefer `agent` and drop the legacy column.
    if "act_as" in existing_cols and "agent" not in existing_cols:
        db.execute("ALTER TABLE issues RENAME COLUMN act_as TO agent")
        existing_cols = {row[1] for row in db.execute("PRAGMA table_info(issues)").fetchall()}
    elif "act_as" in existing_cols and "agent" in existing_cols:
        db.execute("UPDATE issues SET agent = COALESCE(agent, act_as)")
        db.execute("ALTER TABLE issues DROP COLUMN act_as")
        existing_cols = {row[1] for row in db.execute("PRAGMA table_info(issues)").fetchall()}

    migrations = [
        ("assignee", "TEXT DEFAULT 'claude'"),
        ("agent", "TEXT"),
        ("model", "TEXT DEFAULT 'opus'"),
        ("linked_to", "TEXT DEFAULT '[]'"),
        ("issue_type", "TEXT DEFAULT 'issue'"),
        ("scheduled_at", "TEXT"),
        ("recurrence", "TEXT"),
    ]

    for col_name, col_def in migrations:
        if col_name not in existing_cols:
            db.execute(f"ALTER TABLE issues ADD COLUMN {col_name} {col_def}")

    db.execute("CREATE INDEX IF NOT EXISTS idx_issues_assignee ON issues(assignee)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_issues_type ON issues(issue_type)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_issues_scheduled_at ON issues(scheduled_at)")

    # Rewrite legacy statuses on existing rows.
    legacy = db.execute(
        "SELECT COUNT(*) FROM issues WHERE status IN ('in_review','blocked')"
    ).fetchone()[0]
    if legacy:
        db.execute("UPDATE issues SET status='todo' WHERE status IN ('in_review','blocked')")

    # Rebuild whenever the old CHECK constraint OR a retired column is present.
    # The 'scheduled' status was added later; older databases have a CHECK that
    # rejects it, so we rebuild whenever 'scheduled' is missing from the constraint.
    sql_row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='issues'"
    ).fetchone()
    legacy_check = sql_row and ("'in_review'" in sql_row[0] or "'blocked'" in sql_row[0])
    missing_scheduled_check = sql_row and ("'scheduled'" not in sql_row[0])
    # The recurrence CHECK constraint was added later; rebuild if it's missing
    # so existing DBs reject invalid recurrence values rather than silently storing them.
    missing_recurrence_check = sql_row and ("'biweekly'" not in sql_row[0])
    # The issue_type CHECK constraint was added later; rebuild if it's missing.
    missing_issue_type_check = sql_row and ("issue_type IN ('issue','epic')" not in sql_row[0])
    legacy_columns = any(c in existing_cols for c in ("company", "tags", "owner"))
    if legacy_check or missing_scheduled_check or missing_recurrence_check or missing_issue_type_check or legacy_columns:
        _rebuild_issues_table(db)

    db.commit()


def _rebuild_issues_table(db):
    """Recreate issues with the new schema (no company/tags), preserving data.

    Uses individual db.execute() calls inside an explicit BEGIN IMMEDIATE
    transaction so that any mid-rebuild failure rolls back atomically.
    executescript() is intentionally avoided: it issues an implicit COMMIT
    before running and operates in per-statement autocommit, meaning a
    failure after DROP TABLE issues would leave the data stranded in
    issues_new with no way to recover on the next startup.

    The defensive DROP TABLE IF EXISTS issues_new is kept *outside* the
    transaction so that a stray issues_new from a previous aborted run is
    cleaned up before we start — it would otherwise cause CREATE TABLE to
    fail inside the transaction and trigger an unnecessary rollback.
    """
    # Defensive: drop any stray issues_new from a previous aborted run.
    # Must run outside the transaction so it doesn't interfere with the
    # BEGIN IMMEDIATE below.
    db.execute("PRAGMA foreign_keys=OFF")
    db.execute("DROP TABLE IF EXISTS issues_new")
    # Old DBs may not have scheduled_at / recurrence yet; SELECT them via NULL fallback.
    existing_cols_now = {row[1] for row in db.execute("PRAGMA table_info(issues)").fetchall()}
    scheduled_at_select = "scheduled_at" if "scheduled_at" in existing_cols_now else "NULL"
    recurrence_select = "recurrence" if "recurrence" in existing_cols_now else "NULL"
    try:
        # SAVEPOINT works whether or not the caller already has an open
        # transaction (unlike BEGIN IMMEDIATE, which raises
        # "cannot start a transaction within a transaction" when Python's
        # sqlite3 implicit-transaction machinery is active).  RELEASE commits
        # the savepoint; ROLLBACK TO reverts it without touching the outer tx.
        db.execute("SAVEPOINT rebuild_issues")
        db.execute("""
            CREATE TABLE issues_new (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'todo'
                    CHECK(status IN ('todo','in_progress','scheduled','done','cancelled')),
                priority TEXT NOT NULL DEFAULT 'P1'
                    CHECK(priority IN ('P0','P1','P2','P3')),
                blocked_by TEXT DEFAULT '[]',
                parent_id TEXT REFERENCES issues(id),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                closed_at TEXT,
                resolution TEXT,
                time_spent_min INTEGER DEFAULT 0,
                md_hash TEXT,
                assignee TEXT DEFAULT 'claude',
                agent TEXT,
                model TEXT DEFAULT 'opus',
                linked_to TEXT DEFAULT '[]',
                issue_type TEXT DEFAULT 'issue'
                    CHECK(issue_type IN ('issue','epic')),
                scheduled_at TEXT,
                recurrence TEXT
                    CHECK(recurrence IS NULL OR recurrence IN ('daily','weekly','biweekly','monthly'))
            )
        """)
        db.execute(f"""
            INSERT INTO issues_new SELECT
                id, title, description, status, priority,
                blocked_by, parent_id, created_at, updated_at, closed_at, resolution,
                time_spent_min, md_hash, assignee, agent, model, linked_to,
                CASE WHEN issue_type IN ('issue','epic') THEN issue_type ELSE 'issue' END,
                {scheduled_at_select}, {recurrence_select}
            FROM issues
        """)
        db.execute("DROP TABLE issues")
        db.execute("ALTER TABLE issues_new RENAME TO issues")
        db.execute("CREATE INDEX IF NOT EXISTS idx_issues_status ON issues(status)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_issues_priority ON issues(priority)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_issues_assignee ON issues(assignee)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_issues_type ON issues(issue_type)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_issues_scheduled_at ON issues(scheduled_at)")
        db.execute("RELEASE SAVEPOINT rebuild_issues")
        # Recreate FTS triggers that were attached to the dropped table.
        for op, body in [
            ("INSERT",
             "INSERT INTO issues_fts(rowid, id, title, description) "
             "VALUES (new.rowid, new.id, new.title, new.description)"),
            ("DELETE",
             "INSERT INTO issues_fts(issues_fts, rowid, id, title, description) "
             "VALUES('delete', old.rowid, old.id, old.title, old.description)"),
            ("UPDATE",
             "INSERT INTO issues_fts(issues_fts, rowid, id, title, description) "
             "VALUES('delete', old.rowid, old.id, old.title, old.description); "
             "INSERT INTO issues_fts(rowid, id, title, description) "
             "VALUES (new.rowid, new.id, new.title, new.description)"),
        ]:
            try:
                db.execute(
                    f"CREATE TRIGGER IF NOT EXISTS issues_{op.lower()}_fts "
                    f"AFTER {op} ON issues BEGIN {body}; END"
                )
            except sqlite3.OperationalError:
                pass

        # The FTS virtual table schema includes `tags` if it was created earlier.
        # Drop and recreate it against the new column list, then rebuild the index.
        try:
            db.execute("DROP TABLE IF EXISTS issues_fts")
            db.execute("""
                CREATE VIRTUAL TABLE issues_fts USING fts5(
                    id, title, description,
                    content=issues, content_rowid=rowid
                )
            """)
            db.execute("INSERT INTO issues_fts(issues_fts) VALUES('rebuild')")
        except sqlite3.OperationalError:
            pass
    except Exception:
        # Roll back to the savepoint so the original issues table and all
        # its data remain intact.  The caller's outer transaction (migrate_db)
        # can then propagate the error.  ROLLBACK TO SAVEPOINT undoes only the
        # work done after the SAVEPOINT, leaving any outer transaction intact.
        try:
            db.execute("ROLLBACK TO SAVEPOINT rebuild_issues")
            db.execute("RELEASE SAVEPOINT rebuild_issues")
        except sqlite3.OperationalError:
            pass  # savepoint already gone — nothing to roll back
        raise
    finally:
        db.execute("PRAGMA foreign_keys=ON")


# --- Assignee / agent / model invariants ---

def _get_valid_assignees():
    """Return the current set of valid assignees from config."""
    return _cfg().assignee_set

# Backward-compatible module-level name; code that does `VALID_ASSIGNEES` at
# import time gets the config-derived set.  Code that calls it via the helper
# gets a fresh read (important for tests that clear the config cache).
VALID_ASSIGNEES = _get_valid_assignees()


def _normalize_assignee(value):
    """Strip a leading '@' so CLI input like '@alice' still resolves to 'alice'.

    The '@' is display sugar for screens / CLI; storage uses the bare name.
    Returns None for empty input so callers can fall through to defaults.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s[1:] if s.startswith("@") else s
def _get_valid_models():
    """Return the current set of valid models from config."""
    return _cfg().model_set

VALID_MODELS = _get_valid_models()
VALID_STATUSES = ("todo", "in_progress", "scheduled", "done", "cancelled")
TERMINAL_STATUSES = ("done", "cancelled")
VALID_RECURRENCE = ("daily", "weekly", "biweekly", "monthly")
# Window for "due now or soon" used by /start and the context command.
SCHEDULED_DUE_SOON_HOURS = 24
# Window for the kanban "Scheduled" column — what counts as "this week".
SCHEDULED_THIS_WEEK_DAYS = 7


def _parse_scheduled_at(value):
    """Normalize a --scheduled-at input into an ISO 8601 string.

    Accepts YYYY-MM-DD (treated as 09:00 local-equivalent for that day),
    YYYY-MM-DDTHH:MM, or a full ISO datetime. Returns the ISO string, or
    raises ValueError for unparseable input.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # Date-only → assume 09:00 of that day so "tomorrow" doesn't read as midnight
    if len(s) == 10 and s.count("-") == 2:
        try:
            d = datetime.strptime(s, "%Y-%m-%d")
            return d.replace(hour=9).isoformat()
        except ValueError as e:
            raise ValueError(f"invalid scheduled_at date: {s}") from e
    # ISO datetime — let fromisoformat handle T-separator and trailing Z
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        # Normalize to naive local — convert tz-aware inputs via astimezone() first
        # so a "+00:00" input on a CEST machine doesn't store UTC as if it were local.
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt.isoformat()
    except ValueError as e:
        raise ValueError(f"invalid scheduled_at datetime: {s}") from e


def _advance_scheduled_at(scheduled_at_iso, recurrence):
    """Compute the next scheduled_at given a current ISO string and a recurrence.

    Returns a new ISO string at the same time-of-day. Handles month-end edge cases
    by clamping to the last day of the next month (Jan 31 + 1mo → Feb 28/29).
    Raises ValueError if recurrence is unknown or scheduled_at can't be parsed.
    """
    if recurrence not in VALID_RECURRENCE:
        raise ValueError(f"unknown recurrence: {recurrence!r}")
    dt = _scheduled_at_local_dt(scheduled_at_iso)
    if dt is None:
        raise ValueError(f"unparseable scheduled_at: {scheduled_at_iso!r}")
    if recurrence == "daily":
        nxt = dt + timedelta(days=1)
    elif recurrence == "weekly":
        nxt = dt + timedelta(days=7)
    elif recurrence == "biweekly":
        nxt = dt + timedelta(days=14)
    else:  # monthly
        from calendar import monthrange
        new_month = dt.month + 1
        new_year = dt.year + (new_month - 1) // 12
        new_month = ((new_month - 1) % 12) + 1
        last_day = monthrange(new_year, new_month)[1]
        nxt = dt.replace(year=new_year, month=new_month, day=min(dt.day, last_day))
    return nxt.strftime("%Y-%m-%dT%H:%M")


def _scheduled_at_local_dt(value):
    """Best-effort parse of a stored scheduled_at into a naive local datetime for compare.

    The tracker normalizes everything to ISO strings; we strip tz so comparisons
    against datetime.now() are consistent without dragging tz math through every
    call site.
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        # Convert to local time before stripping tzinfo so tz-aware strings
        # (e.g. +00:00) compare correctly against datetime.now() on machines
        # with a non-UTC offset.
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def _normalize_claude_fields(assignee, agent, model, issue_type="issue"):
    """Enforce the invariant: agent and model only when assignee=claude and task.

    Returns (agent, model). Clears both when the assignee is a human or the
    row is an epic (epics are containers).
    """
    if issue_type == "epic":
        return None, None
    if assignee == "claude":
        return (agent or None), (model or "opus")
    return None, None


def cascade_blocked_by(db, resolved_id):
    """When an issue is resolved, remove it from the blocked_by list of any open ticket.

    `blocked_by` is a pure attribute now — not a status. When the last blocker is
    removed the ticket stays in whatever status it was in (usually todo).
    """
    now = datetime.now(timezone.utc).isoformat()
    rows = db.execute(
        "SELECT id, blocked_by FROM issues WHERE status NOT IN ('done','cancelled')"
    ).fetchall()
    unblocked = []
    for row in rows:
        blocked_list = json.loads(row["blocked_by"]) if row["blocked_by"] else []
        if resolved_id in blocked_list:
            blocked_list.remove(resolved_id)
            db.execute("UPDATE issues SET blocked_by=?, updated_at=? WHERE id=?",
                       (json.dumps(blocked_list), now, row["id"]))
            msg = (f"Unblocker {resolved_id} resolved. "
                   + (f"Still blocked by: {', '.join(blocked_list)}" if blocked_list else "No remaining blockers"))
            db.execute("INSERT INTO events (issue_id, type, message, created_at) VALUES (?,?,?,?)",
                       (row["id"], "updated", msg, now))
            if not blocked_list:
                unblocked.append(row["id"])
    db.commit()
    if unblocked:
        print(f"  Unblocked: {', '.join(unblocked)}")


# --- ID generation ---

def _read_counters(db=None):
    """Return the counters dict from the DB.

    Backward-compat: legacy callers passed no args (when counters lived in
    .counter.json). New callers should pass `db`. If db is None, we open one
    at the default DB_PATH — fine for cmd_doctor / cmd_dashboard that don't
    have a db handle in scope.
    """
    if db is None:
        db = sqlite3.connect(DB_PATH, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
    rows = db.execute("SELECT prefix, next_id FROM counters").fetchall()
    return {r["prefix"]: r["next_id"] for r in rows}


def _write_counters(counters, db=None):
    """Persist the counters dict to the DB (UPSERT each prefix)."""
    if db is None:
        db = sqlite3.connect(DB_PATH, timeout=30)
        db.execute("PRAGMA busy_timeout=30000")
    for prefix, next_id in counters.items():
        db.execute(
            "INSERT INTO counters (prefix, next_id) VALUES (?, ?) "
            "ON CONFLICT(prefix) DO UPDATE SET next_id = excluded.next_id",
            (prefix, next_id)
        )
    db.commit()


def _derive_max_ids_from_db(db):
    """
    Scan the issues table and return a dict {prefix: max_num} for every
    prefix that appears (e.g. {"SYS": 116, "VER": 56}).
    """
    rows = db.execute("SELECT id FROM issues").fetchall()
    maxes = {}
    for row in rows:
        issue_id = row[0]
        parts = issue_id.rsplit("-", 1)
        if len(parts) == 2 and parts[1].isdigit():
            prefix = parts[0]
            num = int(parts[1])
            if num > maxes.get(prefix, 0):
                maxes[prefix] = num
    return maxes


def _log_counter_event(db, event_type, message, metadata=None):
    """
    Append an audit event for a counter mutation.
    issue_id is NULL (the events table allows it); we use a sentinel '_counter'.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        "INSERT INTO events (issue_id, type, message, metadata, created_at) VALUES (?,?,?,?,?)",
        (None, event_type, message, json.dumps(metadata or {}), now)
    )
    db.commit()


def next_id(db, prefix):
    """
    Return the next issue ID for *prefix*, guaranteeing monotonicity.

    Uses ``BEGIN IMMEDIATE`` to acquire a write lock before reading and
    incrementing the counter row.  This prevents two concurrent processes
    from both reading the same ``next_id`` value and producing duplicate IDs.
    Compatible with SQLite ≥ 3.25 (no RETURNING needed).

    The db_floor check (counter must be at least one past the highest existing
    ID) is applied inside the same locked transaction to stay consistent.

    The *db* parameter is required so we can check DB state and log events.
    """
    db_maxes = _derive_max_ids_from_db(db)
    db_floor = db_maxes.get(prefix, 0) + 1

    # Ensure the counter row exists outside the IMMEDIATE transaction (safe:
    # ON CONFLICT makes this idempotent even if two processes race here).
    db.execute(
        "INSERT INTO counters (prefix, next_id) VALUES (?, ?) ON CONFLICT(prefix) DO NOTHING",
        (prefix, db_floor),
    )
    db.commit()

    # BEGIN IMMEDIATE acquires a reserved lock immediately — no other writer
    # can sneak in between our SELECT and UPDATE.
    db.execute("BEGIN IMMEDIATE")
    try:
        row = db.execute(
            "SELECT next_id FROM counters WHERE prefix=?", (prefix,)
        ).fetchone()
        current = row[0] if row else db_floor

        if current < db_floor:
            # Counter is stale/rolled-back — fix it silently.
            _log_counter_event(
                db, "counter_set",
                f"Counter for {prefix} bumped from {current} to {db_floor} (DB floor)",
                {"prefix": prefix, "old": current, "new": db_floor},
            )
            current = db_floor

        db.execute(
            "UPDATE counters SET next_id=? WHERE prefix=?",
            (current + 1, prefix),
        )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise

    issue_id = f"{prefix}-{current:03d}"
    _log_counter_event(
        db, "counter_bump",
        f"Issued {issue_id}",
        {"prefix": prefix, "issued": issue_id, "next": current + 1},
    )
    return issue_id


def _get_valid_projects():
    """Return the current set of valid project prefixes from config."""
    return _cfg().project_prefixes

VALID_PROJECTS = tuple(_get_valid_projects())


def _project_of_id(issue_id):
    """Return the project prefix of an issue ID (e.g. 'ARC' for 'ARC-017')."""
    if not issue_id or "-" not in issue_id:
        return ""
    return issue_id.split("-", 1)[0]


def _default_project():
    """Return the first configured project prefix (alphabetically), or 'TASK'."""
    prefixes = sorted(_get_valid_projects())
    return prefixes[0] if prefixes else "TASK"


def _normalize_project(value):
    """Accept a configured project prefix and return it in uppercase form.

    Raises ValueError when value is non-empty but does not resolve to any
    configured prefix. Empty / None falls through to the default.
    """
    valid = _get_valid_projects()
    if not value:
        return _default_project()
    up = value.upper()
    if up in valid:
        return up
    raise ValueError(
        f"Unknown project prefix {value!r}. "
        f"Configured prefixes: {sorted(valid)}. "
        "Use `runloq init` to add new prefixes to runloq.config.toml."
    )


# --- Commands ---

def cmd_init(db, args):
    """Scaffold config + state dir + DB. Idempotent — never overwrites existing files.

    With ``--demo`` it scaffolds a demo config (fictional company "Northwind")
    and seeds the DB with sample tickets, so the board / dashboard look rich for
    a demo or screenshots. Run it in a fresh, empty directory — it self-isolates
    (writes ./runloq.config.toml + ./state/ there, never touching a real
    instance)::

        mkdir northwind-demo && cd northwind-demo
        runloq init --demo
        runloq serve
    """
    global DB_PATH
    from config import CONFIG_TEMPLATE, _PKG_DIR
    import os as _os

    demo = bool(args.get("demo"))
    if demo:
        from seed import DEMO_CONFIG_TEMPLATE
        template = DEMO_CONFIG_TEMPLATE
    else:
        template = CONFIG_TEMPLATE

    # 1. Config file
    # If RUNLOQ_CONFIG (or legacy PRISM_CONFIG) is set, respect it (the user knows
    # where they want it). Demo with no explicit config env → write to the current
    # directory and point this process at it, so the isolated demo never reads or
    # writes a real package-level config/DB. Plain init with no env → package dir
    # (the canonical "clone → init → run" location).
    env_cfg = _os.environ.get("RUNLOQ_CONFIG") or _os.environ.get("PRISM_CONFIG")
    repointed = False
    if env_cfg:
        cfg_path = Path(env_cfg)
        if cfg_path.exists():
            print(f"Config already exists (skipped): {cfg_path}")
        else:
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            cfg_path.write_text(template, encoding="utf-8")
            print(f"Created config: {cfg_path}")
    elif demo:
        cfg_path = Path("runloq.config.toml").resolve()
        if cfg_path.exists():
            print(f"Config already exists (skipped): {cfg_path}")
        else:
            cfg_path.write_text(template, encoding="utf-8")
            print(f"Created config: {cfg_path}")
        _os.environ["RUNLOQ_CONFIG"] = str(cfg_path)
        repointed = True
    else:
        cfg_path = _PKG_DIR / "runloq.config.toml"
        if not cfg_path.exists():
            cfg_path.write_text(template, encoding="utf-8")
            print(f"Created config: {cfg_path}")
        else:
            print(f"Config already exists (skipped): {cfg_path}")

    # If we repointed RUNLOQ_CONFIG at a freshly-written demo config, refresh the
    # cached config and reopen the DB at the demo location (the `db` main() handed
    # us was opened against the pre-demo config).
    if repointed:
        _load_config.cache_clear()
        Path(_cfg().state_dir).mkdir(parents=True, exist_ok=True)
        DB_PATH = _cfg().db
        db = get_db()
        init_db(db)
        migrate_db(db)  # the demo DB needs the same migrations main() ran on the original

    # 2. State directory
    state_dir = Path(_cfg().state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    # 3. Database schema
    db_path = Path(_cfg().db)
    if not db_path.exists():
        init_db(db)
        print(f"Initialized DB: {db_path}")
    else:
        init_db(db)
        print(f"DB already exists (schema verified): {db_path}")

    # 4. Demo seed
    if demo:
        _load_config.cache_clear()  # pick up the just-written demo projects/assignees
        from seed import seed_demo
        n = seed_demo(db, force=bool(args.get("force")))
        print(f"Seeded {n} demo issues (fictional company 'Northwind').")

    print(f"Total: {db.execute('SELECT COUNT(*) FROM issues').fetchone()[0]} issues")

def cmd_seed(db, args):
    """Seed the current instance with the fictional Northwind demo backlog.

    The active config must already define the demo projects/assignees (run
    `runloq init --demo` for a one-step scaffold). Refuses to run on a non-empty
    DB unless --force is passed.
    """
    from seed import seed_demo
    n = seed_demo(db, force=bool(args.get("force")))
    print(f"Seeded {n} demo issues (fictional company 'Northwind').")

def cmd_create(db, args):
    """CLI shim: validate args then delegate to core.create_issue."""
    import core  # noqa: F401

    if not args.get("title"):
        print("Error: title required"); return
    # A non-empty description is mandatory — the title is a label, not a brief.
    # A subagent dispatched via /work ID reads the description first; without one
    # they have to reconstruct intent from comment fragments. Epics are allowed
    # to skip it (they're containers; their children carry the real briefs).
    issue_type_early = args.get("type") or args.get("issue_type") or "issue"
    desc = (args.get("description") or "").strip()
    if issue_type_early != "epic" and not desc:
        print("Error: --description is required (pass --type epic to skip for epic containers)")
        return
    # Accept --project (canonical), fall back to legacy --company, default first prefix.
    _valid_projects = _get_valid_projects()
    _valid_assignees = _get_valid_assignees()
    _valid_models = _get_valid_models()
    try:
        project = _normalize_project(args.get("project") or args.get("company"))
    except ValueError as exc:
        print(f"Error: {exc}"); return
    issue_type = args.get("type") or args.get("issue_type") or "issue"
    if issue_type not in ("issue", "epic"):
        print(f"Error: issue_type must be 'issue' or 'epic' (got '{issue_type}')"); return
    assignee = _normalize_assignee(args.get("assignee")) or "claude"
    if assignee not in _valid_assignees:
        print(f"Error: assignee must be one of {sorted(_valid_assignees)}"); return
    raw_model = args.get("model") or (None if issue_type == "epic" else "opus")
    if raw_model and raw_model not in _valid_models:
        print(f"Error: model must be one of {sorted(_valid_models)}"); return
    # Validate scheduled_at, explicit status, and recurrence before delegating.
    scheduled_at_raw = args.get("scheduled_at")
    if scheduled_at_raw:
        try:
            _parse_scheduled_at(scheduled_at_raw)
        except ValueError as e:
            print(f"Error: {e}"); return
    explicit_status = args.get("status")
    if explicit_status and explicit_status not in VALID_STATUSES:
        print(f"Error: status must be one of {VALID_STATUSES}"); return
    if explicit_status == "scheduled" and not scheduled_at_raw:
        print("Error: status='scheduled' requires --scheduled-at YYYY-MM-DD[THH:MM]"); return
    if scheduled_at_raw and explicit_status and explicit_status not in ("scheduled", "todo"):
        print(f"Error: --scheduled-at not valid with status={explicit_status}"); return
    recurrence = args.get("recurrence")
    if recurrence is True:
        print("Error: --recurrence requires a value (daily|weekly|biweekly|monthly)"); return
    if recurrence and recurrence not in VALID_RECURRENCE:
        print(f"Error: recurrence must be one of {', '.join(VALID_RECURRENCE)} (got {recurrence!r})"); return
    if recurrence and not scheduled_at_raw:
        print("Error: --recurrence requires --scheduled-at (recurrence is only meaningful on scheduled tickets)"); return

    # Translate comma-separated CLI strings to lists for core.
    blocked_by = [s.strip() for s in (args.get("blocked_by") or "").split(",") if s.strip()]
    linked_to_raw = args.get("linked_to") or ""
    linked_to = [s.strip() for s in linked_to_raw.split(",") if s.strip()]

    issue = core.create_issue(
        db,
        title=args["title"],
        project=project,
        type=issue_type,
        priority=args.get("priority") or "P1",
        assignee=assignee,
        agent=args.get("agent") or None,
        model=raw_model,
        description=desc or None,
        blocked_by=blocked_by or None,
        linked_to=linked_to or None,
        parent_id=args.get("parent") or args.get("parent_id"),
        scheduled_at=scheduled_at_raw,
        recurrence=recurrence,
        status=explicit_status,
    )

    suffix = ""
    if issue.get("scheduled_at"):
        suffix = f" — scheduled for {issue['scheduled_at'][:16].replace('T', ' ')}"
        if issue.get("recurrence"):
            suffix += f" (recurs {issue['recurrence']})"
    print(f"Created {issue['id']}: {issue['title']}{suffix}")

def cmd_list(db, args):
    import core  # noqa: F401
    rows = core.list_issues(
        db,
        status=args["status"].split(",") if args.get("status") else None,
        priority=args["priority"].split(",") if args.get("priority") else None,
        assignee=[_normalize_assignee(args["assignee"])] if args.get("assignee") else None,
        project=[args.get("project") or args.get("company")] if (args.get("project") or args.get("company")) else None,
        type=[args["type"]] if args.get("type") else None,
        include_epics=bool(args.get("all_types") or args.get("include_epics")),
        parent_id=args.get("parent"),
    )
    if not rows:
        print("No issues found."); return
    for r in rows:
        status_icon = {"todo": "○", "in_progress": "◉", "scheduled": "⏰",
                       "done": "✓", "cancelled": "✖"}.get(r["status"], "?")
        type_label = " [EPIC]" if r["issue_type"] == "epic" else ""
        print(f"  {status_icon} [{r['id']}]{type_label} {r['priority']} {r['title']}  ({r['status']}, @{r['assignee']})")

def cmd_update(db, args):
    import core
    issue_id = args.get("id")
    if not issue_id:
        print("Error: issue ID required"); return

    # CLI-level validations that core doesn't enforce (CLI-shaped enums).
    _valid_assignees = _get_valid_assignees()
    _valid_models = _get_valid_models()
    if args.get("assignee"):
        args["assignee"] = _normalize_assignee(args["assignee"])
        if args["assignee"] not in _valid_assignees:
            print(f"Error: assignee must be one of {sorted(_valid_assignees)}"); return
    if args.get("model") and args["model"] not in _valid_models:
        print(f"Error: model must be one of {sorted(_valid_models)}"); return
    recurrence = args.get("recurrence")
    if recurrence is True:
        print("Error: --recurrence requires a value (daily|weekly|biweekly|monthly)"); return

    blocked_by = None
    if args.get("blocked_by") is not None:
        blocked_by = [s.strip() for s in args["blocked_by"].split(",") if s.strip()]
    linked_to = None
    if args.get("linked_to") is not None:
        linked_to = [s.strip() for s in args["linked_to"].split(",") if s.strip()]

    try:
        _row, changes = core.update_issue(
            db, issue_id,
            status=args.get("status"),
            priority=args.get("priority"),
            title=args.get("title"),
            description=args.get("description"),
            assignee=args.get("assignee"),
            agent=args.get("agent"),
            model=args.get("model"),
            type=args.get("type") or args.get("issue_type"),
            blocked_by=blocked_by,
            linked_to=linked_to,
            parent_id=args.get("parent"),
            scheduled_at=args.get("scheduled_at"),
            recurrence=recurrence,
            resolution=args.get("resolution"),
            closed_at=args.get("closed_at"),
            clear_agent=bool(args.get("clear_agent")),
            clear_model=bool(args.get("clear_model")),
            clear_scheduled_at=bool(args.get("clear_scheduled_at")),
            clear_recurrence=bool(args.get("clear_recurrence")),
        )
    except KeyError:
        print(f"Error: {issue_id} not found"); return
    except ValueError as e:
        print(f"Error: {e}"); return

    if not changes:
        print("Nothing to update."); return
    print(f"Updated {issue_id}: {', '.join(changes)}")


def cmd_close(db, args):
    import core
    issue_id = args.get("id")
    if not issue_id:
        print("Error: issue ID required"); return

    resolution = args.get("message") or args.get("resolution", "Completed")
    terminal = args.get("status") or "done"
    files = [f.strip() for f in args["files"].split(",")] if args.get("files") else None
    refs = [r.strip() for r in args["refs"].split(",")] if args.get("refs") else None

    try:
        result = core.close_issue(
            db, issue_id, status=terminal, resolution=resolution,
            files=files, refs=refs,
        )
    except KeyError:
        print(f"Not found: {issue_id}"); return
    except ValueError as e:
        print(f"Error: {e}"); return

    verb = "Closed" if terminal == "done" else "Cancelled"
    print(f"{verb} {issue_id}: {resolution}")
    if files:
        print(f"  Files: {', '.join(files)}")
    if refs:
        print(f"  Refs: {', '.join(refs)}")
    if result.get("_next_issue_id"):
        next_disp = result["_next_scheduled_at"][:16].replace("T", " ")
        print(f"  ↻ Auto-spawned {result['_next_issue_id']} ({result.get('recurrence')}, scheduled {next_disp})")

def cmd_show(db, args):
    import core  # noqa: F401
    issue_id = args.get("id")
    if not issue_id:
        print("Error: issue ID required"); return
    try:
        row = core.get_issue(db, issue_id)
    except KeyError:
        print(f"Not found: {issue_id}"); return
    # core.get_issue already deserializes blocked_by/linked_to to lists; the
    # display code below expects strings, so re-serialize for compatibility.
    row["blocked_by"] = json.dumps(row["blocked_by"])
    row["linked_to"] = json.dumps(row["linked_to"])
    print(f"{'═' * 60}")
    type_label = f"  [{row['issue_type'].upper()}]" if row.get('issue_type') and row['issue_type'] != 'issue' else ""
    print(f"  {row['id']}{type_label}  {row['title']}")
    print(f"  Status: {row['status']}  Priority: {row['priority']}  Project: {_project_of_id(row['id'])}")
    print(f"  Created: {row['created_at'][:10]}")
    if row.get('assignee'):
        print(f"  Assignee: @{row['assignee']}")
    if row.get('agent'):
        print(f"  Agent: {row['agent']}")
    if row.get('model'):
        print(f"  Model: {row['model']}")
    linked = json.loads(row["linked_to"]) if row.get("linked_to") else []
    if linked:
        print(f"  Linked to: {', '.join(linked)}")
    if row['time_spent_min']:
        print(f"  Time spent: {row['time_spent_min']} min")
    blocked = json.loads(row["blocked_by"])
    if blocked:
        print(f"  Blocked by: {', '.join(blocked)}")
    if row["parent_id"]:
        print(f"  Parent: {row['parent_id']}")
    if row.get("scheduled_at"):
        sched_disp = row["scheduled_at"][:16].replace("T", " ")
        sched_dt = _scheduled_at_local_dt(row["scheduled_at"])
        if sched_dt is not None:
            delta = sched_dt - datetime.now()
            if delta.total_seconds() < 0:
                rel = f"{abs(delta.days)}d ago" if abs(delta.days) >= 1 else "today (past)"
                print(f"  Scheduled: {sched_disp}  ⚠ overdue ({rel})")
            else:
                rel = f"in {delta.days}d" if delta.days >= 1 else "today/soon"
                print(f"  Scheduled: {sched_disp}  ({rel})")
        else:
            print(f"  Scheduled: {sched_disp}")
    if row.get("recurrence"):
        print(f"  Recurrence: {row['recurrence']} (auto-spawns next iteration on close)")
    if row["description"]:
        print(f"\n  {row['description']}")
    # Events
    events = db.execute("SELECT * FROM events WHERE issue_id=? ORDER BY created_at DESC LIMIT 20",
                        (issue_id,)).fetchall()
    if events:
        print(f"\n  Activity ({len(events)} events):")
        for e in events:
            prefix = f"    [{e['created_at'][:16]}] {e['type']}"
            print(f"{prefix}: {e['message'][:80]}")
            meta = json.loads(e["metadata"]) if e["metadata"] else {}
            if meta.get("files"):
                print(f"      Files: {', '.join(meta['files'])}")
            if meta.get("refs"):
                print(f"      Refs: {', '.join(meta['refs'])}")
    print(f"{'═' * 60}")

def _scheduled_this_week_rows(db):
    """Return scheduled tasks with scheduled_at <= now + SCHEDULED_THIS_WEEK_DAYS.

    Includes overdue items (scheduled_at in the past) — they're the most urgent.
    Excludes terminal-state tickets and epics.
    """
    from datetime import timedelta
    cutoff = (datetime.now() + timedelta(days=SCHEDULED_THIS_WEEK_DAYS)).isoformat()
    return db.execute(
        """SELECT * FROM issues
           WHERE status='scheduled' AND issue_type='issue'
             AND scheduled_at IS NOT NULL AND scheduled_at <= ?
           ORDER BY scheduled_at ASC""",
        (cutoff,)
    ).fetchall()


def _scheduled_due_or_soon_rows(db):
    """Return scheduled tasks past or within SCHEDULED_DUE_SOON_HOURS — actionable now."""
    from datetime import timedelta
    cutoff = (datetime.now() + timedelta(hours=SCHEDULED_DUE_SOON_HOURS)).isoformat()
    return db.execute(
        """SELECT * FROM issues
           WHERE status='scheduled' AND issue_type='issue'
             AND scheduled_at IS NOT NULL AND scheduled_at <= ?
           ORDER BY scheduled_at ASC""",
        (cutoff,)
    ).fetchall()


def _format_scheduled_relative(scheduled_at):
    """Render '⚠ overdue 2d', 'in 3d', 'today', etc. for a scheduled_at value."""
    dt = _scheduled_at_local_dt(scheduled_at)
    if dt is None:
        return ""
    delta = dt - datetime.now()
    secs = delta.total_seconds()
    if secs < 0:
        days = abs(delta.days)
        return f"⚠ overdue {days}d" if days >= 1 else "⚠ overdue today"
    if secs < 24 * 3600:
        return "today/soon"
    return f"in {delta.days}d"


def cmd_board(db, args):
    # Show epics at the top (as container headlines), then per-status columns of tasks.
    include_epics = not args.get("hide_epics")
    if include_epics:
        epics = db.execute("""SELECT id, title, priority, status FROM issues
                              WHERE issue_type='epic' AND status NOT IN ('done','cancelled')
                              ORDER BY CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END""").fetchall()
        if epics:
            print(f"\n▣ EPICS ({len(epics)})")
            for e in epics:
                child_count = db.execute(
                    "SELECT COUNT(*) FROM issues WHERE parent_id=? AND status NOT IN ('done','cancelled')",
                    (e["id"],)
                ).fetchone()[0]
                print(f"  [{e['id']}] {e['priority']} {e['title']}  ({child_count} open)")

    # Scheduled column shows tickets whose scheduled_at lands within the next 7
    # days (or is already past). The column is hidden when nothing matches so
    # routine boards stay clean.
    sched_rows = _scheduled_this_week_rows(db)
    if sched_rows:
        print(f"\n⏰ SCHEDULED · this week ({len(sched_rows)})")
        for r in sched_rows:
            when = r["scheduled_at"][:16].replace("T", " ") if r["scheduled_at"] else "?"
            rel = _format_scheduled_relative(r["scheduled_at"])
            rel_str = f"  ({rel})" if rel else ""
            print(f"  [{r['id']}] {r['priority']} {r['title']}  ({r['assignee']}) — {when}{rel_str}")

    for status, icon in [("in_progress","◉"), ("todo","○")]:
        rows = db.execute("""SELECT id, title, priority, assignee, blocked_by, time_spent_min FROM issues
                             WHERE status=? AND issue_type='issue'
                             ORDER BY CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END""",
                          (status,)).fetchall()
        print(f"\n{icon} {status.upper()} ({len(rows)})")
        if not rows:
            print("  (empty)")
        for r in rows:
            time_str = f"  [{r['time_spent_min']}m]" if r['time_spent_min'] else ""
            blockers = json.loads(r["blocked_by"]) if r["blocked_by"] else []
            blocked_str = f"  ← blocked by {', '.join(blockers)}" if blockers else ""
            print(f"  [{r['id']}] {r['priority']} {r['title']}  ({r['assignee']}){time_str}{blocked_str}")

def cmd_search(db, args):
    import core
    query = args.get("query")
    if not query:
        print("Error: search query required"); return
    rows = core.search_issues(db, query)
    if not rows:
        print("No results."); return
    for r in rows:
        print(f"  [{r['id']}] {r['priority']} {r['status']:12} {r['title']}")

def cmd_log(db, args):
    issue_id = args.get("id")
    message = args.get("message")
    if not issue_id or not message:
        print("Error: issue ID and message required"); return
    if db.execute("SELECT id FROM issues WHERE id=?", (issue_id,)).fetchone() is None:
        print(f"Error: {issue_id} not found"); return
    now = datetime.now(timezone.utc).isoformat()
    event_type = args.get("type", "note")
    metadata = json.dumps(args.get("metadata", {}))
    db.execute("INSERT INTO events (issue_id, type, message, metadata, created_at) VALUES (?,?,?,?,?)",
               (issue_id, event_type, message, metadata, now))
    db.execute("UPDATE issues SET updated_at=? WHERE id=?", (now, issue_id))
    db.commit()
    print(f"Logged to {issue_id}: {message[:60]}")

def cmd_comment(db, args):
    """Add a structured comment to an issue, optionally changing status and referencing files/docs."""
    import core
    issue_id = args.get("id")
    message = args.get("message")
    if not issue_id or not message:
        print("Error: issue ID and message required"); return

    files = [f.strip() for f in args["files"].split(",")] if args.get("files") else None
    refs = [r.strip() for r in args["refs"].split(",")] if args.get("refs") else None
    new_status = args.get("status")

    # Capture pre-status for the display message
    pre = db.execute("SELECT status FROM issues WHERE id=?", (issue_id,)).fetchone()
    pre_status = pre["status"] if pre else None

    try:
        core.add_comment(db, issue_id, message,
                         status=new_status, files=files, refs=refs)
    except KeyError:
        print(f"Error: {issue_id} not found"); return
    except ValueError as e:
        print(f"Error: {e}"); return

    status_msg = ""
    if new_status and new_status != pre_status:
        status_msg = f" [{pre_status} → {new_status}]"
    print(f"Comment on {issue_id}{status_msg}: {message[:60]}")
    if files:
        print(f"  Files: {', '.join(files)}")
    if refs:
        print(f"  Refs: {', '.join(refs)}")

def cmd_events(db, args):
    import core
    types = args["type"].split(",") if args.get("type") else None
    limit = int(args.get("last", 20))
    rows = core.get_events(db, issue_id=args.get("issue"), types=types, limit=limit)
    # CLI shows newest first; core returns chronological.
    for r in reversed(rows):
        issue = f"[{r['issue_id']}]" if r["issue_id"] else "[global]"
        print(f"  {r['created_at'][:16]} {issue} {r['type']}: {r['message'][:70]}")

def cmd_snapshot(db, args):
    """Save current context state for recovery after compaction."""
    now = datetime.now(timezone.utc).isoformat()
    reason = args.get("reason", "manual")

    # Active issues — in_progress plus anything with blockers still to clear.
    active = db.execute("""SELECT id, title, status, priority, assignee FROM issues
                          WHERE status='in_progress'
                             OR (status='todo' AND blocked_by NOT IN ('[]',''))
                          ORDER BY priority""").fetchall()
    active_json = json.dumps([dict(r) for r in active])

    # Recent events (last 50)
    recent = db.execute("SELECT * FROM events ORDER BY created_at DESC LIMIT 50").fetchall()
    recent_json = json.dumps([dict(r) for r in recent])

    # Git state
    import subprocess
    try:
        branch = subprocess.check_output(["git", "branch", "--show-current"], text=True, cwd=_REPO_ROOT).strip()
        dirty = subprocess.check_output(["git", "diff", "--name-only"], text=True, cwd=_REPO_ROOT).strip().split("\n")
    except Exception:
        branch, dirty = "unknown", []

    db.execute("""INSERT INTO snapshots (reason, active_issues, recent_events, git_branch, git_dirty_files, created_at)
                 VALUES (?,?,?,?,?,?)""",
               (reason, active_json, recent_json, branch, json.dumps(dirty), now))
    db.commit()
    snap_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    print(f"Snapshot #{snap_id} saved ({len(active)} active issues, {len(recent)} recent events)")

def _enforce_counter_monotonicity(db):
    """
    Guarantee that every prefix counter on disk is >= max(existing IDs in DB) + 1.
    Mutates the counter file if needed and logs counter_set events for each fix.
    Returns a dict of {prefix: (old_value, new_value)} for any prefix that was corrected.
    """
    counters = _read_counters(db)
    db_maxes = _derive_max_ids_from_db(db)
    corrections = {}

    for prefix, max_num in db_maxes.items():
        floor = max_num + 1
        current = counters.get(prefix, 1)
        if current < floor:
            corrections[prefix] = (current, floor)
            counters[prefix] = floor
            _log_counter_event(
                db, "counter_set",
                f"Counter for {prefix} advanced from {current} to {floor} (monotonicity repair)",
                {"prefix": prefix, "old": current, "new": floor, "trigger": "recover"}
            )

    if corrections:
        _write_counters(counters, db)

    return corrections


def cmd_recover(db, args):
    """Recover context from latest snapshot and enforce counter monotonicity."""
    # 1. Enforce counter monotonicity regardless of whether a snapshot exists.
    corrections = _enforce_counter_monotonicity(db)
    if corrections:
        for prefix, (old, new) in corrections.items():
            print(f"  [counter repair] {prefix}: {old} → {new} (was below DB max)")

    snap_id = args.get("snapshot_id")
    if snap_id:
        snap = db.execute("SELECT * FROM snapshots WHERE id=?", (snap_id,)).fetchone()
    else:
        snap = db.execute("SELECT * FROM snapshots ORDER BY created_at DESC LIMIT 1").fetchone()

    if not snap:
        print("No snapshots found."); return

    print(f"Snapshot #{snap['id']} from {snap['created_at'][:16]} ({snap['reason']})")
    print(f"Git: {snap['git_branch']}")

    active = json.loads(snap["active_issues"])
    if active:
        print(f"\nActive issues ({len(active)}):")
        for i in active:
            print(f"  [{i['id']}] {i['priority']} {i['title']} ({i['status']}, {i.get('assignee','')})")

    recent = json.loads(snap["recent_events"])
    if recent:
        print(f"\nRecent activity (last {min(10, len(recent))}):")
        for e in recent[:10]:
            issue = f"[{e['issue_id']}]" if e.get("issue_id") else "[global]"
            print(f"  {e['created_at'][:16]} {issue} {e['type']}: {e['message'][:60]}")

def cmd_context(db, args):
    """Get smart context for an issue — everything needed to work on it."""
    issue_id = args.get("id")
    if not issue_id:
        # Return global context — what's active now
        active = db.execute("""SELECT * FROM issues
                              WHERE status='in_progress'
                                 OR (status='todo' AND blocked_by NOT IN ('[]',''))
                              ORDER BY CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END""").fetchall()
        # Scheduled tickets that are past due or within the next 24h — surface
        # them above active work so /start can propose acting on them now.
        due_soon = _scheduled_due_or_soon_rows(db)
        if due_soon:
            print(f"⏰ Scheduled — due now or soon ({len(due_soon)}):")
            for r in due_soon:
                when = r["scheduled_at"][:16].replace("T", " ") if r["scheduled_at"] else "?"
                rel = _format_scheduled_relative(r["scheduled_at"])
                rel_str = f" — {rel}" if rel else ""
                print(f"  [{r['id']}] {r['priority']} {r['title']}  ({when}{rel_str})")
            print("  → propose starting one of these (move to in_progress, then work).")
            print()
        print(f"Active work ({len(active)} issues):")
        for r in active:
            print(f"  [{r['id']}] {r['priority']} {r['title']} ({r['status']})")
        # Upcoming-but-not-yet-due scheduled tickets — let the operator see what's
        # on the horizon for the rest of the week without burying it.
        upcoming = [r for r in _scheduled_this_week_rows(db)
                    if r["id"] not in {x["id"] for x in due_soon}]
        if upcoming:
            print(f"\nUpcoming scheduled (this week, {len(upcoming)}):")
            for r in upcoming:
                when = r["scheduled_at"][:16].replace("T", " ") if r["scheduled_at"] else "?"
                rel = _format_scheduled_relative(r["scheduled_at"])
                rel_str = f" — {rel}" if rel else ""
                print(f"  [{r['id']}] {r['priority']} {r['title']}  ({when}{rel_str})")
        recent = db.execute("SELECT * FROM events ORDER BY created_at DESC LIMIT 10").fetchall()
        if recent:
            print("\nRecent activity:")
            for e in recent:
                print(f"  {e['created_at'][:16]} [{e['issue_id'] or 'global'}] {e['message'][:60]}")
        return

    row = db.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
    if not row:
        print(f"Not found: {issue_id}"); return

    print(f"Context for {issue_id}: {row['title']}")
    print(f"Status: {row['status']}  Priority: {row['priority']}  Assignee: {row['assignee']}")
    if row["scheduled_at"]:
        when = row["scheduled_at"][:16].replace("T", " ")
        rel = _format_scheduled_relative(row["scheduled_at"])
        rel_str = f"  ({rel})" if rel else ""
        print(f"Scheduled: {when}{rel_str}")
    if row["description"]:
        print(f"\n{row['description']}")

    # Related issues
    blocked = json.loads(row["blocked_by"])
    if blocked:
        print("\nBlocked by:")
        for bid in blocked:
            b = db.execute("SELECT id, title, status FROM issues WHERE id=?", (bid,)).fetchone()
            if b:
                print(f"  [{b['id']}] {b['title']} ({b['status']})")

    # Children
    children = db.execute("SELECT id, title, status, priority FROM issues WHERE parent_id=?", (issue_id,)).fetchall()
    if children:
        print("\nSub-issues:")
        for c in children:
            print(f"  [{c['id']}] {c['priority']} {c['title']} ({c['status']})")

    # Full event history
    events = db.execute("SELECT * FROM events WHERE issue_id=? ORDER BY created_at", (issue_id,)).fetchall()
    if events:
        print(f"\nFull history ({len(events)} events):")
        for e in events:
            print(f"  [{e['created_at'][:16]}] {e['type']}: {e['message']}")

def cmd_stats(db, args):
    total = db.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
    by_status = db.execute("SELECT status, COUNT(*) as c FROM issues GROUP BY status ORDER BY c DESC").fetchall()
    by_priority = db.execute("SELECT priority, COUNT(*) as c FROM issues WHERE status NOT IN ('done','cancelled') GROUP BY priority").fetchall()
    # Group open work by ID prefix (project) — derived, not stored.
    by_project_rows = db.execute(
        "SELECT id FROM issues WHERE status NOT IN ('done','cancelled')"
    ).fetchall()
    by_project = {}
    for r in by_project_rows:
        prefix = _project_of_id(r["id"]) or "?"
        by_project[prefix] = by_project.get(prefix, 0) + 1
    events_count = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    snaps_count = db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]

    print("Tracker Stats")
    print(f"{'─' * 40}")
    print(f"  Issues: {total} total")
    for r in by_status:
        print(f"    {r['status']:15} {r['c']}")
    print("\n  Open by priority:")
    for r in by_priority:
        print(f"    {r['priority']:5} {r['c']}")
    print("\n  Open by project:")
    for prefix, count in sorted(by_project.items()):
        print(f"    {prefix:5} {count}")
    print(f"\n  Events: {events_count}")
    print(f"  Snapshots: {snaps_count}")
    print(f"  DB size: {os.path.getsize(DB_PATH) / 1024:.1f} KB")

# --- Auto-attach helper ---

def _resolve_issue_id(db, explicit_id):
    """Return the explicit issue ID, or auto-detect if exactly 1 in_progress issue."""
    if explicit_id:
        return explicit_id
    rows = db.execute("SELECT id FROM issues WHERE status='in_progress'").fetchall()
    if len(rows) == 1:
        return rows[0]["id"]
    return None


# --- Track command ---

def cmd_track(db, args):
    """Log external events: file_edit, commit, tool_output, session_start, session_end."""
    # track subcommand is the first positional arg
    event_type = args.get("event_type")
    if not event_type:
        print("Error: event type required (file_edit, commit, tool_output, session_start, session_end)")
        return

    now = datetime.now(timezone.utc).isoformat()
    issue_id = _resolve_issue_id(db, args.get("issue"))

    if event_type == "file_edit":
        path = args.get("arg1")
        if not path:
            print("Error: file path required"); return
        metadata = json.dumps({"path": path})
        db.execute("INSERT INTO events (issue_id, type, message, metadata, created_at) VALUES (?,?,?,?,?)",
                   (issue_id, "file_edit", f"Edited {path}", metadata, now))
        if issue_id:
            db.execute("UPDATE issues SET updated_at=? WHERE id=?", (now, issue_id))
        db.commit()
        target = f" [{issue_id}]" if issue_id else ""
        print(f"Tracked file_edit{target}: {path}")

    elif event_type == "commit":
        commit_hash = args.get("arg1")
        commit_msg = args.get("arg2", "")
        if not commit_hash:
            print("Error: commit hash required"); return
        metadata = json.dumps({"hash": commit_hash, "message": commit_msg})
        db.execute("INSERT INTO events (issue_id, type, message, metadata, created_at) VALUES (?,?,?,?,?)",
                   (issue_id, "commit", f"Commit {commit_hash[:8]}: {commit_msg}", metadata, now))
        if issue_id:
            db.execute("UPDATE issues SET updated_at=? WHERE id=?", (now, issue_id))
        db.commit()
        target = f" [{issue_id}]" if issue_id else ""
        print(f"Tracked commit{target}: {commit_hash[:8]} {commit_msg}")

    elif event_type == "tool_output":
        tool_name = args.get("arg1")
        size = int(args.get("size", 0))
        if not tool_name:
            print("Error: tool name required"); return
        metadata = json.dumps({"tool": tool_name, "size": size})
        db.execute("INSERT INTO events (issue_id, type, message, metadata, created_at) VALUES (?,?,?,?,?)",
                   (issue_id, "tool_output", f"Tool {tool_name} output ({size} bytes)", metadata, now))
        db.execute("INSERT INTO token_stats (tool_name, size, issue_id, created_at) VALUES (?,?,?,?)",
                   (tool_name, size, issue_id, now))
        if issue_id:
            db.execute("UPDATE issues SET updated_at=? WHERE id=?", (now, issue_id))
        db.commit()
        running_total = db.execute("SELECT SUM(size) FROM token_stats").fetchone()[0] or 0
        target = f" [{issue_id}]" if issue_id else ""
        print(f"Tracked tool_output{target}: {tool_name} ({size} bytes, running total: {running_total})")

    elif event_type == "session_start":
        db.execute("INSERT INTO events (issue_id, type, message, metadata, created_at) VALUES (?,?,?,?,?)",
                   (None, "session_start", "Session started", "{}", now))
        db.commit()
        print(f"Tracked session_start at {now[:16]}")

    elif event_type == "session_end":
        db.execute("INSERT INTO events (issue_id, type, message, metadata, created_at) VALUES (?,?,?,?,?)",
                   (None, "session_end", "Session ended", "{}", now))
        db.commit()
        # Auto-snapshot on session end
        cmd_snapshot(db, {"reason": "session_end"})
        print(f"Tracked session_end at {now[:16]}")

    else:
        print(f"Error: unknown event type '{event_type}'. Use: file_edit, commit, tool_output, session_start, session_end")


# --- Timer command ---

def cmd_timer(db, args):
    """Time tracking: start, stop, status."""
    action = args.get("action")
    if not action:
        print("Error: timer action required (start, stop, status)"); return

    now = datetime.now(timezone.utc).isoformat()

    if action == "start":
        issue_id = args.get("arg1")
        if not issue_id:
            print("Error: issue ID required for timer start"); return
        # Check issue exists
        row = db.execute("SELECT id, title FROM issues WHERE id=?", (issue_id,)).fetchone()
        if not row:
            print(f"Error: issue {issue_id} not found"); return
        # Check no active timer already
        active = db.execute("SELECT * FROM timers WHERE stopped_at IS NULL").fetchone()
        if active:
            print(f"Error: timer already running on [{active['issue_id']}]. Stop it first."); return
        db.execute("INSERT INTO timers (issue_id, started_at) VALUES (?,?)", (issue_id, now))
        db.commit()
        print(f"Timer started on [{issue_id}] {row['title']}")

    elif action == "stop":
        issue_id = args.get("arg1")
        if issue_id:
            active = db.execute("SELECT * FROM timers WHERE issue_id=? AND stopped_at IS NULL", (issue_id,)).fetchone()
        else:
            active = db.execute("SELECT * FROM timers WHERE stopped_at IS NULL").fetchone()
        if not active:
            print("Error: no active timer found"); return

        started = datetime.fromisoformat(active["started_at"])
        stopped = datetime.fromisoformat(now)
        duration_sec = int((stopped - started).total_seconds())
        duration_min = round(duration_sec / 60)

        db.execute("UPDATE timers SET stopped_at=?, duration_sec=? WHERE id=?",
                   (now, duration_sec, active["id"]))
        # Add duration to issue's time_spent_min
        db.execute("UPDATE issues SET time_spent_min = time_spent_min + ? WHERE id=?",
                   (duration_min, active["issue_id"]))
        db.execute("INSERT INTO events (issue_id, type, message, metadata, created_at) VALUES (?,?,?,?,?)",
                   (active["issue_id"], "timer_stop", f"Worked {duration_min} min",
                    json.dumps({"duration_sec": duration_sec}), now))
        db.commit()
        print(f"Timer stopped on [{active['issue_id']}]: {duration_min} min ({duration_sec}s)")

    elif action == "status":
        active = db.execute("SELECT * FROM timers WHERE stopped_at IS NULL").fetchone()
        if not active:
            print("No active timer."); return
        started = datetime.fromisoformat(active["started_at"])
        now_dt = datetime.now(timezone.utc)
        elapsed_sec = int((now_dt - started).total_seconds())
        elapsed_min = round(elapsed_sec / 60)
        row = db.execute("SELECT title FROM issues WHERE id=?", (active["issue_id"],)).fetchone()
        title = row["title"] if row else "?"
        print(f"Timer running: [{active['issue_id']}] {title}")
        print(f"  Started: {active['started_at'][:16]}")
        print(f"  Elapsed: {elapsed_min} min ({elapsed_sec}s)")

    else:
        print(f"Error: unknown timer action '{action}'. Use: start, stop, status")


# --- Dashboard command ---

def cmd_dashboard(db, args):
    """Export JSON dashboard summary."""
    now = datetime.now(timezone.utc).isoformat()

    # Issues summary
    total = db.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
    by_status = {}
    for r in db.execute("SELECT status, COUNT(*) as c FROM issues GROUP BY status").fetchall():
        by_status[r["status"]] = r["c"]
    by_priority = {}
    for r in db.execute("SELECT priority, COUNT(*) as c FROM issues WHERE status NOT IN ('done','cancelled') GROUP BY priority").fetchall():
        by_priority[r["priority"]] = r["c"]
    by_project = {}
    for r in db.execute("SELECT id FROM issues WHERE status NOT IN ('done','cancelled')").fetchall():
        prefix = _project_of_id(r["id"]) or "?"
        by_project[prefix] = by_project.get(prefix, 0) + 1

    # Active issues (in_progress)
    active_rows = db.execute("""SELECT id, title, priority, assignee, time_spent_min FROM issues
                                WHERE status='in_progress'
                                ORDER BY CASE priority WHEN 'P0' THEN 0 WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END""").fetchall()
    active = [{"id": r["id"], "title": r["title"], "priority": r["priority"],
               "assignee": r["assignee"], "time_spent_min": r["time_spent_min"] or 0} for r in active_rows]

    # Blocked issues — anything open with a non-empty blocked_by list.
    blocked_rows = db.execute("""SELECT id, title, priority, assignee, time_spent_min FROM issues
                                 WHERE status NOT IN ('done','cancelled')
                                   AND blocked_by NOT IN ('[]','')""").fetchall()
    blocked = [{"id": r["id"], "title": r["title"], "priority": r["priority"],
                "assignee": r["assignee"], "time_spent_min": r["time_spent_min"] or 0} for r in blocked_rows]

    # Scheduled tickets due now or soon — actionable signal for the dashboard
    # consumer (SwiftBar, /start, etc.) so it can flag them with a chime icon.
    due_rows = _scheduled_due_or_soon_rows(db)
    scheduled_due = [{"id": r["id"], "title": r["title"], "priority": r["priority"],
                      "assignee": r["assignee"], "scheduled_at": r["scheduled_at"]} for r in due_rows]

    # Recent events (last 20)
    event_rows = db.execute("SELECT created_at, issue_id, type, message FROM events ORDER BY created_at DESC LIMIT 20").fetchall()
    recent_events = [{"at": r["created_at"], "issue": r["issue_id"] or "global",
                       "type": r["type"], "message": r["message"]} for r in event_rows]

    # Current timer
    current_timer = None
    timer_row = db.execute("SELECT * FROM timers WHERE stopped_at IS NULL").fetchone()
    if timer_row:
        started = datetime.fromisoformat(timer_row["started_at"])
        now_dt = datetime.now(timezone.utc)
        elapsed_min = round((now_dt - started).total_seconds() / 60)
        current_timer = {
            "issue_id": timer_row["issue_id"],
            "started_at": timer_row["started_at"],
            "elapsed_min": elapsed_min
        }

    # Snapshots count
    snaps_count = db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]

    # DB size
    db_size_kb = round(os.path.getsize(DB_PATH) / 1024, 1)

    dashboard = {
        "generated_at": now,
        "issues": {
            "total": total,
            "by_status": by_status,
            "by_priority": by_priority,
            "by_project": by_project,
        },
        "active": active,
        "blocked": blocked,
        "scheduled_due": scheduled_due,
        "recent_events": recent_events,
        "current_timer": current_timer,
        "snapshots": snaps_count,
        "db_size_kb": db_size_kb,
    }

    output_path = args.get("output")
    if output_path is None:
        # Default: print to stdout
        print(json.dumps(dashboard, indent=2))
    else:
        output_path = os.path.expanduser(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(dashboard, f, indent=2)
        print(f"Dashboard written to {output_path}")


# --- Serve command ---

def cmd_serve(db, args):
    """Boot the runloq dashboard (FastAPI + pre-built SPA) and print the URL.

    Delegates to `prism.dashboard.api.main:run`, which respects
    PRISM_HOST / PRISM_PORT environment variables (defaults: 127.0.0.1:3002).
    The database connection opened by main() is not used by this command;
    the dashboard opens its own connection on startup.
    """
    db.close()  # main() opened a connection we don't need here
    from prism.dashboard.api.main import run
    run()


# --- Purge command ---

def cmd_purge(db, args):
    """Delete old events and closed/cancelled issues older than a given date."""
    before = args.get("before")
    statuses = args.get("status", "done,cancelled").split(",")

    if not before:
        print("Error: --before YYYY-MM-DD required"); return

    # Validate date format
    try:
        datetime.strptime(before, "%Y-%m-%d")
    except ValueError:
        print("Error: --before must be YYYY-MM-DD format"); return

    before_iso = before + "T00:00:00"

    # Count what will be deleted
    placeholders = ",".join("?" * len(statuses))
    issue_count = db.execute(
        f"SELECT COUNT(*) FROM issues WHERE status IN ({placeholders}) AND updated_at < ?",
        statuses + [before_iso]
    ).fetchone()[0]
    event_count = db.execute(
        "SELECT COUNT(*) FROM events WHERE created_at < ?", (before_iso,)
    ).fetchone()[0]

    # Delete events for those issues first (to satisfy FK), then events by date
    db.execute(
        f"""DELETE FROM events WHERE issue_id IN (
            SELECT id FROM issues WHERE status IN ({placeholders}) AND updated_at < ?
        )""", statuses + [before_iso]
    )
    # Delete old events not tied to surviving issues
    db.execute("DELETE FROM events WHERE created_at < ? AND (issue_id IS NULL OR issue_id NOT IN (SELECT id FROM issues))",
               (before_iso,))

    # Delete timers for those issues
    db.execute(
        f"""DELETE FROM timers WHERE issue_id IN (
            SELECT id FROM issues WHERE status IN ({placeholders}) AND updated_at < ?
        )""", statuses + [before_iso]
    )

    # Delete token_stats for those issues
    db.execute(
        f"""DELETE FROM token_stats WHERE issue_id IN (
            SELECT id FROM issues WHERE status IN ({placeholders}) AND updated_at < ?
        )""", statuses + [before_iso]
    )

    # Delete the issues
    db.execute(
        f"DELETE FROM issues WHERE status IN ({placeholders}) AND updated_at < ?",
        statuses + [before_iso]
    )

    db.commit()
    db.execute("VACUUM")
    print(f"Purged {issue_count} issues (statuses: {', '.join(statuses)}) and associated events before {before}")
    print(f"Events removed: ~{event_count}. Snapshots preserved. DB vacuumed.")


# --- Doctor command ---

def cmd_doctor(db, args):
    """
    Read-only audit of tracker consistency. Detects:
      (a) counter_low  — counter file value < max ID in DB for a prefix
      (b) orphan_event — events.issue_id references a nonexistent issue

    Prints a human-readable report. With --fix, auto-repairs what it can
    (counter repair + counter_set audit event). Does NOT auto-fix orphan-event
    mismatches — those require human review.

    Returns a list of issue dicts for use in tests.
    """
    fix = args.get("fix", False)
    findings = []  # list of {"type": ..., "severity": ..., "detail": ...}

    # (a) Counter monotonicity
    counters = _read_counters(db)
    db_maxes = _derive_max_ids_from_db(db)
    for prefix, max_num in db_maxes.items():
        floor = max_num + 1
        current = counters.get(prefix, 1)
        if current < floor:
            findings.append({
                "type": "counter_low",
                "severity": "error",
                "detail": f"{prefix} counter={current}, DB max={max_num} (floor={floor})"
            })

    # (b) Events referencing nonexistent issue IDs (NULL issue_id is fine — those are global)
    orphan_rows = db.execute("""
        SELECT DISTINCT e.issue_id FROM events e
        WHERE e.issue_id IS NOT NULL
          AND e.issue_id NOT IN (SELECT id FROM issues)
    """).fetchall()
    for row in orphan_rows:
        findings.append({
            "type": "orphan_event",
            "severity": "error",
            "detail": f"Events reference nonexistent issue_id={row[0]}"
        })

    # Print report
    if not findings:
        print("doctor: no issues found — tracker is healthy.")
    else:
        errors = [f for f in findings if f["severity"] == "error"]
        print(f"doctor: {len(findings)} issue(s) found ({len(errors)} error(s))")
        for f in findings:
            icon = "✖" if f["severity"] == "error" else "⚠"
            print(f"  {icon} [{f['type']}] {f['detail']}")

        if fix:
            print("\ndoctor --fix: applying auto-repairs...")
            # Only auto-fix counter issues (safe)
            corrections = _enforce_counter_monotonicity(db)
            if corrections:
                for prefix, (old, new) in corrections.items():
                    print(f"  Fixed counter {prefix}: {old} → {new}")
            else:
                print("  No counter corrections needed.")
            print("  Note: md/db sync mismatches and orphan events require manual review.")
            print("  Run: tracker sync --direction both   (to resync md ↔ db)")
        else:
            print("\nRun with --fix to auto-repair counter issues.")
            print("For md/db sync: tracker sync --direction both")

    return findings


# --- Reassign-ID command ---

def cmd_reassign_id(db, args):
    """
    Atomically rename an issue from OLD to NEW:
      - Refuses if NEW already exists.
      - Updates issues.id, all events.issue_id, timers, token_stats.
      - Renames the .md file.
      - Logs a reassign event on the new ID.

    FTS5 stays in sync via the AFTER UPDATE trigger on issues — we don't
    touch the FTS table directly here. Manually issuing a 'delete' followed
    by the trigger's own 'delete' was the previous design and corrupted the
    FTS5 segment store ("database disk image is malformed").
    """
    old_id = args.get("old_id")
    new_id = args.get("new_id")
    if not old_id or not new_id:
        print("Error: old_id and new_id required"); return

    # Validate old exists
    old_row = db.execute("SELECT * FROM issues WHERE id=?", (old_id,)).fetchone()
    if old_row is None:
        print(f"Error: {old_id} not found"); return

    # Refuse if new already exists
    existing = db.execute("SELECT 1 FROM issues WHERE id=?", (new_id,)).fetchone()
    if existing is not None:
        print(f"Error: {new_id} already exists — reassign-id refuses to overwrite"); return

    now = datetime.now(timezone.utc).isoformat()

    # SQLite FK constraints would block updating issues.id while child rows exist.
    # Temporarily disable FK checks for this connection, do the rename atomically,
    # then re-enable. This is the standard SQLite pattern for cascaded PK renames.
    try:
        db.execute("PRAGMA foreign_keys=OFF")

        # Repoint child rows BEFORE renaming PK (FK is OFF so order doesn't matter)
        db.execute("UPDATE events SET issue_id=? WHERE issue_id=?", (new_id, old_id))
        db.execute("UPDATE timers SET issue_id=? WHERE issue_id=?", (new_id, old_id))
        db.execute("UPDATE token_stats SET issue_id=? WHERE issue_id=?", (new_id, old_id))
        # Fix parent_id references in other issues
        db.execute("UPDATE issues SET parent_id=? WHERE parent_id=?", (new_id, old_id))

        # Update the primary row id — the AFTER UPDATE trigger on issues
        # automatically performs the FTS delete-then-insert dance for us.
        db.execute("UPDATE issues SET id=?, updated_at=? WHERE id=?", (new_id, now, old_id))

        # Audit event (with FK OFF, we can reference new_id which now exists)
        db.execute("INSERT INTO events (issue_id, type, message, metadata, created_at) VALUES (?,?,?,?,?)",
                   (new_id, "reassigned",
                    f"Renamed from {old_id} to {new_id}",
                    json.dumps({"old_id": old_id, "new_id": new_id}),
                    now))

        db.commit()

    except Exception as exc:
        db.rollback()
        db.execute("PRAGMA foreign_keys=ON")
        print(f"Error: reassign-id failed — {exc}"); return
    finally:
        db.execute("PRAGMA foreign_keys=ON")

    print(f"Reassigned: {old_id} → {new_id}")


# --- Rename title command ---

def cmd_rename(db, args):
    """Update an issue's title. Thin wrapper around cmd_update for discoverability."""
    issue_id = args.get("id")
    new_title = args.get("title")
    if not issue_id or not new_title:
        print("Error: issue ID and new title required"); return
    cmd_update(db, {"id": issue_id, "title": new_title})


# --- CLI parser ---

def parse_args(argv):
    if len(argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = argv[1]
    args = {}

    # Positional args by command
    positionals = {
        "create": ["title"],
        "update": ["id"],
        "close": ["id", "message"],
        "show": ["id"],
        "search": ["query"],
        "comment": ["id", "message"],
        "log": ["id", "message"],
        "context": ["id"],
        "track": ["event_type", "arg1", "arg2"],
        "timer": ["action", "arg1"],
        "rename": ["id", "title"],
        "reassign-id": ["old_id", "new_id"],
    }

    pos_keys = positionals.get(cmd, [])
    pos_idx = 0
    i = 2
    while i < len(argv):
        if argv[i].startswith("--"):
            key = argv[i][2:].replace("-", "_")
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                args[key] = argv[i + 1]
                i += 2
            else:
                args[key] = True
                i += 1
        else:
            if pos_idx < len(pos_keys):
                args[pos_keys[pos_idx]] = argv[i]
                pos_idx += 1
            i += 1

    return cmd, args


def main():
    cmd, args = parse_args(sys.argv)

    os.makedirs(_cfg().state_dir, exist_ok=True)
    db = get_db()
    init_db(db)
    migrate_db(db)

    commands = {
        "init": cmd_init, "create": cmd_create, "list": cmd_list,
        "update": cmd_update, "close": cmd_close, "show": cmd_show,
        "board": cmd_board,
        "search": cmd_search, "comment": cmd_comment, "log": cmd_log,
        "events": cmd_events, "snapshot": cmd_snapshot, "recover": cmd_recover,
        "context": cmd_context, "stats": cmd_stats,
        "track": cmd_track, "timer": cmd_timer, "dashboard": cmd_dashboard,
        "serve": cmd_serve,
        "purge": cmd_purge, "doctor": cmd_doctor,
        "rename": cmd_rename, "reassign-id": cmd_reassign_id,
        "seed": cmd_seed,
    }

    if cmd in commands:
        commands[cmd](db, args)
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)

    db.close()

if __name__ == "__main__":
    main()
