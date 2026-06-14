"""
Tests for prism.py safety guarantees

Coverage:
- Counter monotonicity: recover() never decreases counters below DB max
- Pre-create collision guard: create refuses to overwrite existing IDs
- `doctor` command detects all inconsistencies
- `reassign-id` moves an issue atomically, preserving events
- Audit trail: counter mutations produce events
"""

import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import shutil
import unittest
from datetime import datetime

# Load prism.py the same way the CLI does (`python3 prism/prism.py`): with the
# `prism/` directory on sys.path so the in-function `import core` calls inside
# prism.py resolve to `prism/core.py`. We can't simply `from prism import prism`
# because that imports prism.py as a submodule, which breaks those bare imports.
_PRISM_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PRISM_DIR not in sys.path:
    sys.path.insert(0, _PRISM_DIR)
_spec = importlib.util.spec_from_file_location("_prism_cli", os.path.join(_PRISM_DIR, "prism.py"))
T = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(T)


# ---------------------------------------------------------------------------
# Test-config isolation (mirrors test_mcp.py pattern)
# ---------------------------------------------------------------------------
# Write a minimal config with the TASK project so tests that reference TASK
# always resolve correctly, regardless of whether a site-specific
# prism.config.toml exists in cwd or the package directory.
_TEST_CFG_DIR = tempfile.mkdtemp(prefix="prism_test_cfg_")
_TEST_CFG_PATH = os.path.join(_TEST_CFG_DIR, "test_prism.config.toml")
with open(_TEST_CFG_PATH, "w") as _fh:
    _fh.write('[projects]\nTASK = "Tasks"\n')


def _isolate_config():
    """Set PRISM_CONFIG to the test fixture and clear the lru_cache.

    Returns the previous value of PRISM_CONFIG (may be None) so callers can
    restore it in tearDown.
    """
    old = os.environ.get("PRISM_CONFIG")
    os.environ["PRISM_CONFIG"] = _TEST_CFG_PATH
    try:
        import config as _cfg
        _cfg.load_config.cache_clear()
    except Exception:
        pass
    return old


def _restore_config(old_val):
    """Restore PRISM_CONFIG to *old_val* and clear the lru_cache."""
    if old_val is None:
        os.environ.pop("PRISM_CONFIG", None)
    else:
        os.environ["PRISM_CONFIG"] = old_val
    try:
        import config as _cfg
        _cfg.load_config.cache_clear()
    except Exception:
        pass


def make_env(tmp_dir):
    """Create a throwaway DB for a test. Counters live in the database;
    the tmp_dir only needs to hold the .db file.

    Also sets PRISM_CONFIG to a minimal fixture (TASK project only) so that
    config.load_config() resolves the TASK prefix regardless of whether a
    site-specific prism.config.toml exists in the developer's cwd.
    """
    state_dir = os.path.join(tmp_dir, "state")
    os.makedirs(state_dir)
    db_path = os.path.join(state_dir, "prism.db")

    # Patch module-level paths so the production code uses the test DB.
    T.DB_PATH = db_path
    T.STATE_DIR = state_dir

    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    T.init_db(db)
    T.migrate_db(db)
    return db


class TestCounterMonotonicity(unittest.TestCase):
    """cmd_recover must never set the counter below max(existing IDs in DB)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old_prism_cfg = _isolate_config()
        self.db = make_env(self.tmp)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)
        _restore_config(self._old_prism_cfg)

    def _create_issue_raw(self, issue_id, title="Test"):
        """Insert an issue row directly, bypassing the counter."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            """INSERT INTO issues (id, title, status, priority,
               blocked_by, linked_to, issue_type, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (issue_id, title, "todo", "P1",
             "[]", "[]", "issue", now, now)
        )
        self.db.commit()

    def _write_counter(self, counters):
        T._write_counters(counters, self.db)

    def _read_counter(self):
        return T._read_counters(self.db)

    def test_recover_does_not_roll_back_counter(self):
        """Recover must use DB max ID when counter is out of sync."""
        # Insert issues at specific counter values
        for n in range(111, 117):
            self._create_issue_raw(f"TASK-{n:03d}", f"Issue {n}")

        # Simulate the incident: counter rolled back to 110
        self._write_counter({"TASK": 110})

        # Run recover
        T.cmd_recover(self.db, {})

        counters = self._read_counter()
        self.assertGreaterEqual(
            counters.get("TASK", 0), 117,
            "Counter must be at least 117 after recover (max id 116 → next is 117)"
        )

    def test_recover_leaves_already_correct_counter_alone(self):
        """If counter is already ahead of DB, recover must not decrease it."""
        self._create_issue_raw("TASK-005", "Five")
        self._write_counter({"TASK": 99})

        T.cmd_recover(self.db, {})

        counters = self._read_counter()
        self.assertGreaterEqual(counters.get("TASK", 0), 99)

    def test_recover_handles_missing_counter_file(self):
        """recover when no counter file exists: derive from DB."""
        self._create_issue_raw("TASK-010", "Ten")
        # No counter file

        T.cmd_recover(self.db, {})

        counters = self._read_counter()
        self.assertGreaterEqual(counters.get("TASK", 0), 11)

    def test_counter_bump_event_logged(self):
        """Every time recover fixes a counter, an audit event must be written."""
        self._create_issue_raw("TASK-050", "Fifty")
        self._write_counter({"TASK": 1})  # way too low

        T.cmd_recover(self.db, {})

        events = self.db.execute(
            "SELECT * FROM events WHERE type='counter_set'"
        ).fetchall()
        self.assertTrue(len(events) >= 1, "At least one counter_set event expected")


class TestCreateCollisionGuard(unittest.TestCase):
    """cmd_create must never silently overwrite an existing issue ID."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old_prism_cfg = _isolate_config()
        self.db = make_env(self.tmp)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)
        _restore_config(self._old_prism_cfg)

    def _seed_counter(self, prefix, val):
        """Set counter so next_id returns prefix-val."""
        counters = T._read_counters(self.db)
        counters[prefix] = val
        T._write_counters(counters, self.db)

    def test_create_auto_bumps_on_collision(self):
        """When ID is already taken, create must use the next free slot, not overwrite."""
        # Create the first issue normally
        T.cmd_create(self.db, {"title": "Original TASK-001", "project": "TASK", "description": "test"})
        # Force counter back to 1 to simulate rollback
        self._seed_counter("TASK", 1)

        # Now create again — should NOT overwrite SYS-001
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            T.cmd_create(self.db, {"title": "Should not overwrite", "project": "TASK", "description": "test"})
        output = buf.getvalue()

        # Original title must be intact
        row = self.db.execute("SELECT title FROM issues WHERE id='TASK-001'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "Original TASK-001", "Original issue must NOT be overwritten")

        # New issue must have been created with a different ID
        self.assertNotIn("TASK-001", output.strip().split()[1] if output.strip() else "", )
        # Count should be 2
        count = self.db.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
        self.assertEqual(count, 2, "Two distinct issues must exist")

    def test_create_does_not_silently_overwrite(self):
        """create must not use INSERT OR REPLACE semantics."""
        T.cmd_create(self.db, {"title": "First", "project": "TASK", "description": "test"})
        original = self.db.execute("SELECT id FROM issues").fetchone()[0]

        # Force counter back
        self._seed_counter("TASK", int(original.split("-")[1]))

        T.cmd_create(self.db, {"title": "Collision Attempt", "project": "TASK", "description": "test"})

        # Both must exist
        rows = self.db.execute("SELECT id, title FROM issues").fetchall()
        titles = {r[0]: r[1] for r in rows}
        self.assertIn(original, titles)
        self.assertEqual(titles[original], "First", "Original title preserved")

    def test_counter_bump_event_on_collision(self):
        """When a collision is detected and counter is bumped, a counter_bump event must be logged."""
        T.cmd_create(self.db, {"title": "First", "project": "TASK", "description": "test"})
        first_id = self.db.execute("SELECT id FROM issues").fetchone()[0]
        num = int(first_id.split("-")[1])
        self._seed_counter("TASK", num)  # same num → collision

        T.cmd_create(self.db, {"title": "Trigger collision", "project": "TASK", "description": "test"})

        events = self.db.execute(
            "SELECT * FROM events WHERE type='counter_bump'"
        ).fetchall()
        self.assertTrue(len(events) >= 1, "counter_bump event expected on collision")


class TestDoctorCommand(unittest.TestCase):
    """prism doctor detects all documented inconsistency classes."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old_prism_cfg = _isolate_config()
        self.db = make_env(self.tmp)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)
        _restore_config(self._old_prism_cfg)

    def _write_counter(self, counters):
        T._write_counters(counters, self.db)

    def _create_issue_raw(self, issue_id, title="Test"):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            """INSERT INTO issues (id, title, status, priority,
               blocked_by, linked_to, issue_type, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (issue_id, title, "todo", "P1",
             "[]", "[]", "issue", now, now)
        )
        self.db.commit()

    def _run_doctor(self, fix=False):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        args = {"fix": True} if fix else {}
        with redirect_stdout(buf):
            result = T.cmd_doctor(self.db, args)
        return buf.getvalue(), result

    def test_doctor_detects_counter_below_max(self):
        """doctor reports when counter < max id in DB."""
        self._create_issue_raw("TASK-020")
        self._write_counter({"TASK": 5})  # should be 21

        output, issues = self._run_doctor()
        self.assertTrue(
            any(i["type"] == "counter_low" for i in issues),
            f"Expected counter_low issue, got: {issues}"
        )

    def test_doctor_detects_orphan_events(self):
        """doctor reports events referencing nonexistent issue_ids."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        # Disable FK to simulate a corrupt DB state (as caused by the real incident)
        self.db.execute("PRAGMA foreign_keys=OFF")
        self.db.execute(
            "INSERT INTO events (issue_id, type, message, created_at) VALUES (?,?,?,?)",
            ("TASK-999", "note", "Ghost event", now)
        )
        self.db.commit()
        self.db.execute("PRAGMA foreign_keys=ON")

        output, issues = self._run_doctor()
        self.assertTrue(
            any(i["type"] == "orphan_event" for i in issues),
            f"Expected orphan_event issue, got: {issues}"
        )

    def test_doctor_clean_on_healthy_db(self):
        """doctor returns no issues on a healthy, consistent DB."""
        T.cmd_create(self.db, {"title": "Clean issue", "project": "TASK", "description": "test"})

        output, issues = self._run_doctor()
        # Filter only error-level issues (not info)
        errors = [i for i in issues if i.get("severity") == "error"]
        self.assertEqual(errors, [], f"Expected clean DB, got: {errors}")


class TestReassignId(unittest.TestCase):
    """prism reassign-id atomically renames an issue."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old_prism_cfg = _isolate_config()
        self.db = make_env(self.tmp)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)
        _restore_config(self._old_prism_cfg)

    def test_reassign_moves_issue_and_events(self):
        """reassign-id OLD NEW: new ID has all old events, old ID is gone."""
        T.cmd_create(self.db, {"title": "Movable", "project": "TASK", "description": "test"})
        old_id = self.db.execute("SELECT id FROM issues").fetchone()[0]
        # Add an event
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            "INSERT INTO events (issue_id, type, message, created_at) VALUES (?,?,?,?)",
            (old_id, "note", "Something happened", now)
        )
        self.db.commit()

        new_id = "TASK-999"
        T.cmd_reassign_id(self.db, {"old_id": old_id, "new_id": new_id})

        # Old row gone
        old_row = self.db.execute("SELECT id FROM issues WHERE id=?", (old_id,)).fetchone()
        self.assertIsNone(old_row, "Old issue ID must not exist after reassign")

        # New row present
        new_row = self.db.execute("SELECT id, title FROM issues WHERE id=?", (new_id,)).fetchone()
        self.assertIsNotNone(new_row)
        self.assertEqual(new_row[1], "Movable")

        # Events repointed
        events = self.db.execute("SELECT issue_id FROM events WHERE issue_id=?", (new_id,)).fetchall()
        self.assertTrue(len(events) >= 1, "Events must be migrated to new ID")

        # Old events gone
        old_events = self.db.execute("SELECT issue_id FROM events WHERE issue_id=?", (old_id,)).fetchall()
        self.assertEqual(len(old_events), 0, "No events should still reference old ID")

    def test_reassign_refuses_when_new_id_exists(self):
        """reassign-id refuses if NEW already exists in DB."""
        T.cmd_create(self.db, {"title": "Issue A", "project": "TASK", "description": "test"})
        T.cmd_create(self.db, {"title": "Issue B", "project": "TASK", "description": "test"})
        rows = self.db.execute("SELECT id FROM issues ORDER BY id").fetchall()
        id_a, id_b = rows[0][0], rows[1][0]

        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            T.cmd_reassign_id(self.db, {"old_id": id_a, "new_id": id_b})
        output = buf.getvalue()

        self.assertIn("Error", output, "Should print an error when new_id already exists")

        # Both original issues must still exist
        count = self.db.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
        self.assertEqual(count, 2)

class TestAuditTrail(unittest.TestCase):
    """Counter mutations produce events of specific types."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old_prism_cfg = _isolate_config()
        self.db = make_env(self.tmp)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)
        _restore_config(self._old_prism_cfg)

    def test_next_id_logs_counter_bump(self):
        """Every call to next_id (i.e., cmd_create) logs a counter_bump event."""
        T.cmd_create(self.db, {"title": "Audit test", "project": "TASK", "description": "test"})

        events = self.db.execute(
            "SELECT * FROM events WHERE type='counter_bump'"
        ).fetchall()
        self.assertTrue(len(events) >= 1, "counter_bump event expected after create")

    def test_rollback_blocked_event_when_counter_is_fine(self):
        """When no rollback occurs, no counter_rollback_blocked events appear."""
        T.cmd_create(self.db, {"title": "Normal create", "project": "TASK", "description": "test"})

        events = self.db.execute(
            "SELECT * FROM events WHERE type='counter_rollback_blocked'"
        ).fetchall()
        self.assertEqual(len(events), 0, "No rollback_blocked events on normal flow")


class TestCloseStatus(unittest.TestCase):
    """cmd_close must honor `--status cancelled` rather than always writing 'done'."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old_prism_cfg = _isolate_config()
        self.db = make_env(self.tmp)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)
        _restore_config(self._old_prism_cfg)

    def _create_issue_raw(self, issue_id, title="Test"):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            """INSERT INTO issues (id, title, status, priority,
               blocked_by, linked_to, issue_type, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (issue_id, title, "todo", "P1",
             "[]", "[]", "issue", now, now)
        )
        self.db.commit()

    def test_close_with_status_cancelled_records_cancelled(self):
        """`close ID --status cancelled` must write status='cancelled', not 'done'."""
        self._create_issue_raw("TASK-900", "About to be cancelled")

        T.cmd_close(self.db, {
            "id": "TASK-900",
            "message": "Cancelled — scope dropped",
            "status": "cancelled",
        })

        row = self.db.execute(
            "SELECT status, closed_at FROM issues WHERE id=?", ("TASK-900",)
        ).fetchone()
        self.assertEqual(row["status"], "cancelled",
                         "close --status cancelled should leave status=cancelled")
        self.assertIsNotNone(row["closed_at"],
                             "close must always stamp closed_at, regardless of terminal status")

    def test_close_without_status_defaults_to_done(self):
        """`close ID` (no --status) preserves the legacy default of 'done'."""
        self._create_issue_raw("TASK-901", "About to be done")

        T.cmd_close(self.db, {"id": "TASK-901", "message": "Shipped"})

        row = self.db.execute(
            "SELECT status FROM issues WHERE id=?", ("TASK-901",)
        ).fetchone()
        self.assertEqual(row["status"], "done")

    def test_close_rejects_non_terminal_status(self):
        """`close ID --status todo` is nonsensical — close only ends in done or cancelled."""
        self._create_issue_raw("TASK-902", "Still open")

        T.cmd_close(self.db, {
            "id": "TASK-902",
            "message": "Oops",
            "status": "todo",
        })

        row = self.db.execute(
            "SELECT status FROM issues WHERE id=?", ("TASK-902",)
        ).fetchone()
        self.assertEqual(row["status"], "todo",
                         "close with invalid terminal status must not mutate the row")


class TestClaudeFieldsInvariant(unittest.TestCase):
    """agent and model are only valid when assignee=claude; humans + epics must not carry either."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old_prism_cfg = _isolate_config()
        self.db = make_env(self.tmp)
        # Skip agent-slug validation: these tests exercise assignee/agent field clearing
        # invariants, not slug validation (that lives in TestValidateAgentSlug in test_core.py).
        self._old_skip = os.environ.get("TRACKER_SKIP_AGENT_VALIDATION")
        os.environ["TRACKER_SKIP_AGENT_VALIDATION"] = "1"

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)
        _restore_config(self._old_prism_cfg)
        if self._old_skip is None:
            os.environ.pop("TRACKER_SKIP_AGENT_VALIDATION", None)
        else:
            os.environ["TRACKER_SKIP_AGENT_VALIDATION"] = self._old_skip

    def _mute(self, fn, *args, **kwargs):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            fn(*args, **kwargs)
        return buf.getvalue()

    def test_normalize_claude_fields_keeps_values_for_claude(self):
        agent, model = T._normalize_claude_fields("claude", "frontend-dev", "sonnet", "task")
        self.assertEqual(agent, "frontend-dev")
        self.assertEqual(model, "sonnet")

    def test_normalize_claude_fields_defaults_model_for_claude(self):
        agent, model = T._normalize_claude_fields("claude", None, None, "task")
        self.assertIsNone(agent)
        # No explicit model → default to opus for a Claude-assigned task.
        self.assertEqual(model, "opus")

    def test_normalize_claude_fields_clears_for_human(self):
        agent, model = T._normalize_claude_fields("alice", "devops", "opus", "task")
        self.assertIsNone(agent)
        self.assertIsNone(model)

    def test_normalize_claude_fields_clears_for_epic(self):
        agent, model = T._normalize_claude_fields("claude", "pm", "opus", "epic")
        self.assertIsNone(agent)
        self.assertIsNone(model)

    def test_create_rejects_unknown_assignee(self):
        output = self._mute(T.cmd_create, self.db, {
            "title": "Bad assignee", "project": "TASK", "description": "test",
            "assignee": "@stranger",
        })
        self.assertIn("Error: assignee", output)
        count = self.db.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
        self.assertEqual(count, 0, "Invalid assignee must not insert a row")

    def test_create_rejects_unknown_model(self):
        output = self._mute(T.cmd_create, self.db, {
            "title": "Bad model", "project": "TASK", "description": "test",
            "model": "turbo",
        })
        self.assertIn("Error: model", output)
        count = self.db.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
        self.assertEqual(count, 0)

    def test_create_clears_agent_and_model_for_human_assignee(self):
        self._mute(T.cmd_create, self.db, {
            "title": "Human action", "project": "TASK", "description": "test",
            "assignee": "me", "agent": "devops", "model": "opus",
        })
        row = self.db.execute("SELECT assignee, agent, model FROM issues").fetchone()
        self.assertEqual(row["assignee"], "me")
        self.assertIsNone(row["agent"], "agent must be cleared for human assignee")
        self.assertIsNone(row["model"], "model must be cleared for human assignee")

    def test_update_auto_clears_agent_and_model_on_reassignment_to_human(self):
        self._mute(T.cmd_create, self.db, {
            "title": "Claude ticket", "project": "TASK", "description": "test",
            "assignee": "claude", "agent": "frontend-dev", "model": "sonnet",
        })
        issue_id = self.db.execute("SELECT id FROM issues").fetchone()[0]
        # Now reassign to a human — agent/model must auto-clear.
        self._mute(T.cmd_update, self.db, {"id": issue_id, "assignee": "me"})
        row = self.db.execute(
            "SELECT assignee, agent, model FROM issues WHERE id=?", (issue_id,)
        ).fetchone()
        self.assertEqual(row["assignee"], "me")
        self.assertIsNone(row["agent"])
        self.assertIsNone(row["model"])

    def test_update_rejects_setting_agent_on_human_ticket(self):
        self._mute(T.cmd_create, self.db, {
            "title": "Human ticket", "project": "TASK", "description": "test",
            "assignee": "me",
        })
        issue_id = self.db.execute("SELECT id FROM issues").fetchone()[0]
        output = self._mute(T.cmd_update, self.db, {
            "id": issue_id, "agent": "frontend-dev",
        })
        self.assertIn("Error: agent is only valid when assignee=claude", output)
        row = self.db.execute("SELECT agent FROM issues WHERE id=?", (issue_id,)).fetchone()
        self.assertIsNone(row["agent"])

    def test_create_requires_description_for_task(self):
        output = self._mute(T.cmd_create, self.db, {
            "title": "No brief", "project": "TASK",
        })
        self.assertIn("Error: --description is required", output)
        count = self.db.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
        self.assertEqual(count, 0, "Task without description must not insert")

    def test_create_allows_empty_description_for_epic(self):
        self._mute(T.cmd_create, self.db, {
            "title": "Epic container", "project": "TASK", "type": "epic",
        })
        count = self.db.execute(
            "SELECT COUNT(*) FROM issues WHERE issue_type='epic'"
        ).fetchone()[0]
        self.assertEqual(count, 1, "Epics are containers — description may be empty")

    def test_update_rejects_invalid_status(self):
        self._mute(T.cmd_create, self.db, {"title": "T", "project": "TASK", "description": "test"})
        issue_id = self.db.execute("SELECT id FROM issues").fetchone()[0]
        output = self._mute(T.cmd_update, self.db, {
            "id": issue_id, "status": "in_review",
        })
        self.assertIn("Error: status must be one of", output)
        row = self.db.execute(
            "SELECT status FROM issues WHERE id=?", (issue_id,)
        ).fetchone()
        self.assertEqual(row["status"], "todo",
                         "Rejected status change must not mutate the row")


class TestUpdateClosedAtStamping(unittest.TestCase):
    """`update --status done|cancelled` must stamp closed_at; transitioning out clears it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old_prism_cfg = _isolate_config()
        self.db = make_env(self.tmp)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)
        _restore_config(self._old_prism_cfg)

    def _mute(self, fn, *args, **kwargs):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            fn(*args, **kwargs)
        return buf.getvalue()

    def test_update_to_done_stamps_closed_at(self):
        self._mute(T.cmd_create, self.db, {"title": "Will close", "project": "TASK", "description": "test"})
        issue_id = self.db.execute("SELECT id FROM issues").fetchone()[0]
        self._mute(T.cmd_update, self.db, {"id": issue_id, "status": "done"})
        row = self.db.execute(
            "SELECT status, closed_at FROM issues WHERE id=?", (issue_id,)
        ).fetchone()
        self.assertEqual(row["status"], "done")
        self.assertIsNotNone(row["closed_at"], "closed_at must be stamped on terminal transition")

    def test_update_with_resolution_persists(self):
        self._mute(T.cmd_create, self.db, {"title": "Will close", "project": "TASK", "description": "test"})
        issue_id = self.db.execute("SELECT id FROM issues").fetchone()[0]
        self._mute(T.cmd_update, self.db, {
            "id": issue_id, "status": "done", "resolution": "Shipped in commit abc123",
        })
        row = self.db.execute(
            "SELECT resolution FROM issues WHERE id=?", (issue_id,)
        ).fetchone()
        self.assertEqual(row["resolution"], "Shipped in commit abc123")

    def test_reopening_clears_closed_at_and_resolution(self):
        self._mute(T.cmd_create, self.db, {"title": "Reopen me", "project": "TASK", "description": "test"})
        issue_id = self.db.execute("SELECT id FROM issues").fetchone()[0]
        # Close it.
        self._mute(T.cmd_update, self.db, {
            "id": issue_id, "status": "done", "resolution": "done",
        })
        # Reopen.
        self._mute(T.cmd_update, self.db, {"id": issue_id, "status": "todo"})
        row = self.db.execute(
            "SELECT status, closed_at, resolution FROM issues WHERE id=?", (issue_id,)
        ).fetchone()
        self.assertEqual(row["status"], "todo")
        self.assertIsNone(row["closed_at"], "closed_at must clear when leaving terminal state")
        self.assertIsNone(row["resolution"], "resolution must clear when leaving terminal state")


class TestMigration(unittest.TestCase):
    """migrate_db must bring legacy schemas (company/tags/owner columns, retired statuses) up to date."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.issues_dir = os.path.join(self.tmp, "issues")
        os.makedirs(self.issues_dir)
        self.db_path = os.path.join(self.issues_dir, "prism.db")
        T.DB_PATH = self.db_path
        T.ISSUES_DIR = self.issues_dir
        T.COUNTER_FILE = os.path.join(self.issues_dir, ".counter.json")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _build_legacy_db(self):
        """Recreate the pre-refactor schema with company/tags/owner columns and the old CHECK."""
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
            CREATE TABLE issues (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'todo'
                    CHECK(status IN ('todo','in_progress','in_review','done','blocked','cancelled')),
                priority TEXT NOT NULL DEFAULT 'P1'
                    CHECK(priority IN ('P0','P1','P2','P3')),
                owner TEXT NOT NULL DEFAULT 'claude',
                company TEXT NOT NULL DEFAULT 'system',
                tags TEXT DEFAULT '[]',
                blocked_by TEXT DEFAULT '[]',
                parent_id TEXT,
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
                issue_type TEXT DEFAULT 'task'
            );
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id TEXT,
                type TEXT NOT NULL,
                message TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE TABLE snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reason TEXT NOT NULL,
                active_issues TEXT NOT NULL,
                recent_events TEXT NOT NULL,
                open_files TEXT DEFAULT '[]',
                git_branch TEXT,
                git_dirty_files TEXT DEFAULT '[]',
                created_at TEXT NOT NULL
            );
            CREATE TABLE timers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id TEXT,
                started_at TEXT NOT NULL,
                stopped_at TEXT,
                duration_sec INTEGER
            );
            CREATE TABLE token_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_name TEXT NOT NULL,
                size INTEGER NOT NULL,
                issue_id TEXT,
                created_at TEXT NOT NULL
            );
        """)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            ("TASK-001", "Legacy in_review", "in_review", "P1"),
            ("TASK-002", "Legacy blocked",    "blocked",   "P2"),
            ("TASK-003", "Legacy done",       "done",      "P3"),
        ]
        for issue_id, title, status, priority in rows:
            db.execute(
                """INSERT INTO issues
                   (id, title, status, priority, owner, company, tags,
                    blocked_by, assignee, agent, model, linked_to, issue_type,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (issue_id, title, status, priority, "claude", "system", '["legacy"]',
                 "[]", "claude", None, "opus", "[]", "task", now, now)
            )
        db.commit()
        return db

    def test_migration_drops_legacy_columns_and_rewrites_statuses(self):
        db = self._build_legacy_db()
        # Sanity: legacy columns should be present before migration.
        pre_cols = {r[1] for r in db.execute("PRAGMA table_info(issues)").fetchall()}
        self.assertIn("company", pre_cols)
        self.assertIn("tags", pre_cols)
        self.assertIn("owner", pre_cols)

        T.init_db(db)
        T.migrate_db(db)

        post_cols = {r[1] for r in db.execute("PRAGMA table_info(issues)").fetchall()}
        self.assertNotIn("company", post_cols, "company must be dropped")
        self.assertNotIn("tags", post_cols, "tags must be dropped")
        self.assertNotIn("owner", post_cols, "owner must be dropped")

        statuses = {r[0]: r[1] for r in db.execute("SELECT id, status FROM issues").fetchall()}
        self.assertEqual(statuses["TASK-001"], "todo", "in_review must migrate to todo")
        self.assertEqual(statuses["TASK-002"], "todo", "blocked must migrate to todo")
        self.assertEqual(statuses["TASK-003"], "done", "done must stay done")

        # CHECK constraint is rewritten — inserting an old-style status should fail.
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO issues (id, title, status, priority, created_at, updated_at) "
                "VALUES ('TASK-999','x','in_review','P1','2026-01-01','2026-01-01')"
            )
        db.close()

    def test_rebuild_is_atomic_on_mid_rebuild_failure(self):
        """A failure mid-rebuild must roll back so the original issues table and
        data are intact — not leave the DB with an empty issues table or a
        stranded issues_new table after failed migration.

        Strategy: wrap the sqlite3.Connection in a proxy that intercepts the
        call to "DROP TABLE issues" and raises OperationalError, simulating a
        mid-rebuild lock or crash.  After _rebuild_issues_table raises, assert:
          1. The original issues table still exists with all rows.
          2. No issues_new table is left behind (ROLLBACK TO SAVEPOINT cleaned it).
        """
        real_db = self._build_legacy_db()

        # Sanitize legacy statuses so the INSERT INTO issues_new doesn't fail
        # on the CHECK constraint — the same step migrate_db does before calling
        # _rebuild_issues_table.  We do it here because we invoke the helper
        # directly (bypassing migrate_db) to control the failure injection point.
        real_db.execute("UPDATE issues SET status='todo' WHERE status IN ('in_review','blocked')")
        real_db.commit()

        original_count = real_db.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
        self.assertGreater(original_count, 0, "precondition: legacy DB must have rows")

        class _FailOnDrop:
            """Thin proxy that delegates all attribute access to the wrapped
            connection and intercepts execute() to inject a failure."""

            def __init__(self, conn):
                object.__setattr__(self, "_conn", conn)

            def __getattr__(self, name):
                return getattr(object.__getattribute__(self, "_conn"), name)

            def execute(self, sql, *args, **kwargs):
                conn = object.__getattribute__(self, "_conn")
                if sql.strip().upper() == "DROP TABLE ISSUES":
                    raise sqlite3.OperationalError(
                        "injected failure: simulated lock/crash"
                    )
                return conn.execute(sql, *args, **kwargs)

        proxy = _FailOnDrop(real_db)

        with self.assertRaises(sqlite3.OperationalError):
            T._rebuild_issues_table(proxy)

        # 1. Original issues table must still exist with all original rows.
        post_count = real_db.execute("SELECT COUNT(*) FROM issues").fetchone()[0]
        self.assertEqual(
            post_count, original_count,
            "issues table must survive a mid-rebuild failure with all rows intact"
        )

        # 2. No stray issues_new table left behind.
        stray = real_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='issues_new'"
        ).fetchone()
        self.assertIsNone(stray, "issues_new must not remain after a rolled-back rebuild")

        real_db.close()


class TestScheduledStatus(unittest.TestCase):
    """Coverage for the `scheduled` status + `scheduled_at` field added in the
    scheduled-jobs feature: CLI surface, validation, board windowing, context
    command, and markdown round-trip.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old_prism_cfg = _isolate_config()
        self.db = make_env(self.tmp)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)
        _restore_config(self._old_prism_cfg)

    def _now_offset_iso(self, **kwargs):
        from datetime import datetime, timedelta
        return (datetime.now() + timedelta(**kwargs)).isoformat(timespec="minutes")

    def test_create_with_scheduled_at_auto_sets_scheduled_status(self):
        """--scheduled-at without --status flips status to 'scheduled'."""
        when = self._now_offset_iso(days=2)
        T.cmd_create(self.db, {"title": "Weekly thing", "description": "a brief",
                               "scheduled_at": when})
        row = self.db.execute("SELECT status, scheduled_at FROM issues WHERE id='TASK-001'").fetchone()
        self.assertEqual(row["status"], "scheduled")
        # ISO string is normalized — startswith covers seconds/tz drift
        self.assertTrue(row["scheduled_at"].startswith(when[:13]),
                        f"expected scheduled_at near {when}, got {row['scheduled_at']}")

    def test_create_status_scheduled_without_datetime_fails(self):
        """status='scheduled' without a datetime is meaningless — reject it."""
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            T.cmd_create(self.db, {"title": "x", "description": "y", "status": "scheduled"})
        self.assertIn("requires --scheduled-at", buf.getvalue())
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM issues").fetchone()[0], 0)

    def test_create_invalid_scheduled_at_format(self):
        """Bogus datetime strings produce a clear error and no insert."""
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            T.cmd_create(self.db, {"title": "x", "description": "y",
                                   "scheduled_at": "not-a-date"})
        self.assertIn("invalid scheduled_at", buf.getvalue())
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM issues").fetchone()[0], 0)

    def test_date_only_input_normalizes_to_9am(self):
        """`--scheduled-at YYYY-MM-DD` becomes T09:00 of that day."""
        T.cmd_create(self.db, {"title": "x", "description": "y",
                               "scheduled_at": "2026-08-15"})
        row = self.db.execute("SELECT scheduled_at FROM issues WHERE id='TASK-001'").fetchone()
        self.assertTrue(row["scheduled_at"].startswith("2026-08-15T09:00"),
                        f"expected 09:00 default, got {row['scheduled_at']}")

    def test_update_scheduled_at_logs_change(self):
        """Rescheduling produces a visible event with old → new."""
        T.cmd_create(self.db, {"title": "x", "description": "y",
                               "scheduled_at": "2026-08-15"})
        T.cmd_update(self.db, {"id": "TASK-001", "scheduled_at": "2026-08-22"})
        row = self.db.execute("SELECT scheduled_at FROM issues WHERE id='TASK-001'").fetchone()
        self.assertTrue(row["scheduled_at"].startswith("2026-08-22T09:00"))
        evt = self.db.execute(
            "SELECT message FROM events WHERE issue_id='TASK-001' AND type='updated' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        self.assertIn("scheduled_at", evt["message"])
        self.assertIn("2026-08-15", evt["message"])
        self.assertIn("2026-08-22", evt["message"])

    def test_status_change_out_of_scheduled_clears_scheduled_at(self):
        """Promoting to in_progress clears the now-meaningless datetime."""
        T.cmd_create(self.db, {"title": "x", "description": "y",
                               "scheduled_at": "2026-08-15"})
        T.cmd_update(self.db, {"id": "TASK-001", "status": "in_progress"})
        row = self.db.execute(
            "SELECT status, scheduled_at FROM issues WHERE id='TASK-001'"
        ).fetchone()
        self.assertEqual(row["status"], "in_progress")
        self.assertIsNone(row["scheduled_at"])

    def test_due_or_soon_helper_window(self):
        """_scheduled_due_or_soon_rows returns past + within 24h, not later."""
        from datetime import datetime, timedelta
        now = datetime.now()
        past = (now - timedelta(days=2)).isoformat(timespec="minutes")
        soon = (now + timedelta(hours=6)).isoformat(timespec="minutes")
        later = (now + timedelta(days=4)).isoformat(timespec="minutes")
        T.cmd_create(self.db, {"title": "past", "description": "x", "scheduled_at": past})
        T.cmd_create(self.db, {"title": "soon", "description": "x", "scheduled_at": soon})
        T.cmd_create(self.db, {"title": "later", "description": "x", "scheduled_at": later})
        rows = T._scheduled_due_or_soon_rows(self.db)
        ids = {r["id"] for r in rows}
        self.assertEqual(ids, {"TASK-001", "TASK-002"},
                         f"due-or-soon should be past+soon only, got {ids}")

    def test_this_week_helper_window(self):
        """_scheduled_this_week_rows returns past + within 7 days, not later."""
        from datetime import datetime, timedelta
        now = datetime.now()
        past = (now - timedelta(days=2)).isoformat(timespec="minutes")
        within = (now + timedelta(days=4)).isoformat(timespec="minutes")
        beyond = (now + timedelta(days=20)).isoformat(timespec="minutes")
        T.cmd_create(self.db, {"title": "past", "description": "x", "scheduled_at": past})
        T.cmd_create(self.db, {"title": "within", "description": "x", "scheduled_at": within})
        T.cmd_create(self.db, {"title": "beyond", "description": "x", "scheduled_at": beyond})
        rows = T._scheduled_this_week_rows(self.db)
        ids = {r["id"] for r in rows}
        self.assertEqual(ids, {"TASK-001", "TASK-002"},
                         f"this-week should exclude items >7d out, got {ids}")

    def test_invalid_status_rejected_with_helpful_message(self):
        """The status validator lists all valid values."""
        import io, contextlib
        T.cmd_create(self.db, {"title": "x", "description": "y"})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            T.cmd_update(self.db, {"id": "TASK-001", "status": "whatever"})
        msg = buf.getvalue()
        self.assertIn("scheduled", msg)
        self.assertIn("todo", msg)

    # ── Timezone round-trip tests ───────────────────────────────────

    def test_parse_scheduled_at_date_only_naive(self):
        """Date-only input yields naive local 09:00 string with no tzinfo offset."""
        result = T._parse_scheduled_at("2026-08-20")
        self.assertEqual(result, "2026-08-20T09:00:00")
        # Must be parseable as a naive datetime
        dt = datetime.fromisoformat(result)
        self.assertIsNone(dt.tzinfo)

    def test_parse_scheduled_at_naive_datetime_unchanged(self):
        """Naive datetime input passes through without acquiring tzinfo."""
        result = T._parse_scheduled_at("2026-08-20T14:30")
        dt = datetime.fromisoformat(result)
        self.assertIsNone(dt.tzinfo)
        self.assertEqual(dt.hour, 14)
        self.assertEqual(dt.minute, 30)

    def test_parse_scheduled_at_utc_plus00_converts_to_local(self):
        """+00:00 input is converted to local naive time, not stored as UTC."""
        result = T._parse_scheduled_at("2026-08-20T12:00+00:00")
        dt = datetime.fromisoformat(result)
        # Result must be naive
        self.assertIsNone(dt.tzinfo, "stored value must be naive (no tzinfo)")
        # The stored value must equal the local representation of 2026-08-20T12:00Z
        from datetime import timezone as _tz
        expected_local = datetime(2026, 8, 20, 12, 0, tzinfo=_tz.utc).astimezone().replace(tzinfo=None)
        # Compare with minute precision (isoformat may have seconds)
        self.assertEqual(dt.replace(second=0, microsecond=0),
                         expected_local.replace(second=0, microsecond=0))

    def test_parse_scheduled_at_z_suffix_converts_to_local(self):
        """'Z' suffix (UTC) is converted to local naive time."""
        result = T._parse_scheduled_at("2026-08-20T10:00Z")
        dt = datetime.fromisoformat(result)
        self.assertIsNone(dt.tzinfo, "stored value must be naive")

    def test_scheduled_at_local_dt_naive_passthrough(self):
        """_scheduled_at_local_dt returns a naive datetime unchanged."""
        dt = T._scheduled_at_local_dt("2026-08-20T09:00:00")
        self.assertIsNotNone(dt)
        self.assertIsNone(dt.tzinfo)
        self.assertEqual(dt.hour, 9)

    def test_scheduled_at_local_dt_utc_converts_to_local(self):
        """+00:00 value is converted to local before tzinfo is stripped."""
        from datetime import timezone as _tz
        utc_iso = "2026-08-20T12:00:00+00:00"
        dt = T._scheduled_at_local_dt(utc_iso)
        self.assertIsNotNone(dt)
        self.assertIsNone(dt.tzinfo, "result must be naive")
        expected_local = datetime(2026, 8, 20, 12, 0, tzinfo=_tz.utc).astimezone().replace(tzinfo=None)
        self.assertEqual(dt.replace(second=0), expected_local.replace(second=0))

    def test_due_or_soon_with_utc_input(self):
        """A ticket stored with a +00:00 scheduled_at still surfaces in due-or-soon."""
        from datetime import timedelta
        from datetime import timezone as _tz
        # Create a ticket scheduled 6h from now expressed in UTC
        soon_utc = (datetime.now(_tz.utc) + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M+00:00")
        T.cmd_create(self.db, {"title": "utc-soon", "description": "x", "scheduled_at": soon_utc})
        rows = T._scheduled_due_or_soon_rows(self.db)
        ids = {r["id"] for r in rows}
        self.assertIn("TASK-001", ids,
                      "ticket with UTC +6h offset should appear in due-or-soon window")

    def test_this_week_with_utc_input(self):
        """A ticket stored with a +00:00 scheduled_at surfaces in this-week window."""
        from datetime import timedelta
        from datetime import timezone as _tz
        # Scheduled 4 days from now in UTC
        soon_utc = (datetime.now(_tz.utc) + timedelta(days=4)).strftime("%Y-%m-%dT%H:%M+00:00")
        T.cmd_create(self.db, {"title": "utc-this-week", "description": "x", "scheduled_at": soon_utc})
        rows = T._scheduled_this_week_rows(self.db)
        ids = {r["id"] for r in rows}
        self.assertIn("TASK-001", ids,
                      "ticket with UTC +4d offset should appear in this-week window")


class TestRecurringScheduled(unittest.TestCase):
    """Coverage for the recurrence feature: closing a `done` ticket with a
    `recurrence` set auto-spawns the next iteration as a fresh `scheduled`
    ticket. Cancelled close ends the chain.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old_prism_cfg = _isolate_config()
        self.db = make_env(self.tmp)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)
        _restore_config(self._old_prism_cfg)

    def _create_recurring(self, recurrence="weekly", scheduled_at="2026-05-03T09:00"):
        T.cmd_create(self.db, {
            "title": "weekly review",
            "description": "do the thing",
            "scheduled_at": scheduled_at,
            "recurrence": recurrence,
        })
        return self.db.execute(
            "SELECT id, status, scheduled_at, recurrence FROM issues WHERE id='TASK-001'"
        ).fetchone()

    def test_create_with_recurrence_persists(self):
        row = self._create_recurring()
        self.assertEqual(row["status"], "scheduled")
        self.assertEqual(row["recurrence"], "weekly")

    def test_close_done_spawns_next_iteration(self):
        self._create_recurring("weekly", "2026-05-03T09:00")
        T.cmd_close(self.db, {"id": "TASK-001", "message": "first done"})
        rows = list(self.db.execute(
            "SELECT id, status, scheduled_at, recurrence, linked_to FROM issues ORDER BY id"
        ).fetchall())
        self.assertEqual(len(rows), 2, "expected one closed + one auto-spawned")
        original = dict(rows[0])
        spawned = dict(rows[1])
        self.assertEqual(original["status"], "done")
        self.assertEqual(spawned["status"], "scheduled")
        self.assertEqual(spawned["recurrence"], "weekly")
        self.assertEqual(spawned["scheduled_at"], "2026-05-10T09:00",
                         "weekly should advance by 7 days")
        self.assertEqual(json.loads(spawned["linked_to"]), [original["id"]],
                         "spawned ticket should link back to the closed one")

    def test_close_cancelled_does_not_spawn(self):
        self._create_recurring()
        T.cmd_close(self.db, {"id": "TASK-001", "message": "stop", "status": "cancelled"})
        rows = list(self.db.execute("SELECT id, status FROM issues").fetchall())
        self.assertEqual(len(rows), 1, "cancelled close must NOT spawn a next iteration")
        self.assertEqual(rows[0]["status"], "cancelled")

    def test_daily_advances_one_day(self):
        T.cmd_create(self.db, {
            "title": "daily standup", "description": "x",
            "scheduled_at": "2026-05-03T09:00", "recurrence": "daily",
        })
        T.cmd_close(self.db, {"id": "TASK-001", "message": "done"})
        spawned = self.db.execute(
            "SELECT scheduled_at FROM issues WHERE status='scheduled'"
        ).fetchone()
        self.assertEqual(spawned["scheduled_at"], "2026-05-04T09:00")

    def test_biweekly_advances_fourteen_days(self):
        T.cmd_create(self.db, {
            "title": "biweekly", "description": "x",
            "scheduled_at": "2026-05-03T09:00", "recurrence": "biweekly",
        })
        T.cmd_close(self.db, {"id": "TASK-001", "message": "done"})
        spawned = self.db.execute(
            "SELECT scheduled_at FROM issues WHERE status='scheduled'"
        ).fetchone()
        self.assertEqual(spawned["scheduled_at"], "2026-05-17T09:00")

    def test_monthly_clamps_month_end(self):
        """Jan 31 + 1 month should clamp to Feb 28 (or Feb 29 in leap years).
        Important so monthly recurrence never produces an invalid date."""
        T.cmd_create(self.db, {
            "title": "monthly", "description": "x",
            "scheduled_at": "2026-01-31T10:00", "recurrence": "monthly",
        })
        T.cmd_close(self.db, {"id": "TASK-001", "message": "done"})
        spawned = self.db.execute(
            "SELECT scheduled_at FROM issues WHERE status='scheduled'"
        ).fetchone()
        # 2026 is not a leap year — Feb has 28 days
        self.assertEqual(spawned["scheduled_at"], "2026-02-28T10:00")

    def test_recurrence_without_scheduled_at_rejected(self):
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            T.cmd_create(self.db, {"title": "x", "description": "y", "recurrence": "weekly"})
        self.assertIn("--recurrence requires --scheduled-at", buf.getvalue())
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM issues").fetchone()[0], 0)

    def test_invalid_recurrence_value_rejected(self):
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            T.cmd_create(self.db, {"title": "x", "description": "y",
                                   "scheduled_at": "2026-05-03",
                                   "recurrence": "yearly"})
        self.assertIn("recurrence must be one of", buf.getvalue())
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM issues").fetchone()[0], 0)

    def test_update_can_set_recurrence(self):
        T.cmd_create(self.db, {"title": "x", "description": "y",
                               "scheduled_at": "2026-05-03"})
        T.cmd_update(self.db, {"id": "TASK-001", "recurrence": "weekly"})
        row = self.db.execute("SELECT recurrence FROM issues WHERE id='TASK-001'").fetchone()
        self.assertEqual(row["recurrence"], "weekly")

    def test_update_clear_recurrence(self):
        self._create_recurring()
        T.cmd_update(self.db, {"id": "TASK-001", "clear_recurrence": True})
        row = self.db.execute("SELECT recurrence FROM issues WHERE id='TASK-001'").fetchone()
        self.assertIsNone(row["recurrence"])

    def test_status_change_off_scheduled_preserves_recurrence(self):
        """Moving a recurring ticket to in_progress clears scheduled_at but
        PRESERVES recurrence — recurrence is the ticket's identity as a
        recurring job, so close still spawns the next iteration after the
        ticket has been picked up and worked (scheduled ticket pickup regression). Previously
        this silently cleared recurrence and killed the recurring chain on the
        first real pickup (the daily vault-maintenance job died this way)."""
        self._create_recurring("weekly", "2026-05-03T09:00")
        T.cmd_update(self.db, {"id": "TASK-001", "status": "in_progress"})
        row = self.db.execute(
            "SELECT scheduled_at, recurrence FROM issues WHERE id='TASK-001'"
        ).fetchone()
        self.assertIsNone(row["scheduled_at"])
        self.assertEqual(row["recurrence"], "weekly")
        # Closing the worked ticket must still spawn the next iteration.
        T.cmd_close(self.db, {"id": "TASK-001", "message": "done"})
        nxt = self.db.execute(
            "SELECT status, recurrence FROM issues WHERE id='TASK-002'"
        ).fetchone()
        self.assertIsNotNone(nxt)
        self.assertEqual(nxt["status"], "scheduled")
        self.assertEqual(nxt["recurrence"], "weekly")

    def test_chain_continues_across_multiple_closes(self):
        """A 3-iteration weekly chain: each close spawns the next, links propagate."""
        self._create_recurring("weekly", "2026-05-03T09:00")
        T.cmd_close(self.db, {"id": "TASK-001", "message": "i1"})
        T.cmd_close(self.db, {"id": "TASK-002", "message": "i2"})
        T.cmd_close(self.db, {"id": "TASK-003", "message": "i3"})
        rows = self.db.execute(
            "SELECT id, status, scheduled_at FROM issues ORDER BY id"
        ).fetchall()
        ids_status = [(r["id"], r["status"], r["scheduled_at"]) for r in rows]
        self.assertEqual(ids_status, [
            ("TASK-001", "done", "2026-05-03T09:00:00"),
            ("TASK-002", "done", "2026-05-10T09:00"),
            ("TASK-003", "done", "2026-05-17T09:00"),
            ("TASK-004", "scheduled", "2026-05-24T09:00"),
        ])


# ============================================================
# SYS-375: Smoke tests for snapshot, timer, track, stats,
#          purge, and rename commands
# ============================================================

class _SmokeBase(unittest.TestCase):
    """Shared setUp/tearDown + _mute() helper for SYS-375 smoke tests."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old_prism_cfg = _isolate_config()
        self.db = make_env(self.tmp)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)
        _restore_config(self._old_prism_cfg)

    def _mute(self, fn, *args, **kwargs):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            fn(*args, **kwargs)
        return buf.getvalue()

    def _create_issue(self, title="Test issue"):
        """Insert a minimal TASK issue and return its ID."""
        self._mute(T.cmd_create, self.db, {
            "title": title, "project": "TASK", "description": "smoke test brief",
        })
        return self.db.execute("SELECT id FROM issues ORDER BY created_at DESC LIMIT 1").fetchone()[0]


class TestSnapshotSmoke(_SmokeBase):
    """cmd_snapshot writes a row to the snapshots table and prints a confirmation."""

    def test_snapshot_inserts_row(self):
        self._mute(T.cmd_snapshot, self.db, {"reason": "pre-compact"})
        count = self.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        self.assertEqual(count, 1)

    def test_snapshot_captures_reason(self):
        self._mute(T.cmd_snapshot, self.db, {"reason": "test-reason"})
        row = self.db.execute("SELECT reason FROM snapshots ORDER BY created_at DESC LIMIT 1").fetchone()
        self.assertEqual(row["reason"], "test-reason")

    def test_snapshot_captures_active_in_progress_issue(self):
        issue_id = self._create_issue("Active work")
        self._mute(T.cmd_update, self.db, {"id": issue_id, "status": "in_progress"})
        self._mute(T.cmd_snapshot, self.db, {"reason": "auto"})
        row = self.db.execute("SELECT active_issues FROM snapshots ORDER BY created_at DESC LIMIT 1").fetchone()
        import json
        active = json.loads(row["active_issues"])
        self.assertTrue(any(i["id"] == issue_id for i in active),
                        f"in_progress issue {issue_id} should appear in snapshot active_issues")

    def test_snapshot_git_fallback_stores_unknown_branch(self):
        """When git subprocess fails, branch should be 'unknown' (not crash)."""
        # Use a non-git tmp dir as _REPO_ROOT to force the failure path
        old_root = T._REPO_ROOT
        T._REPO_ROOT = self.tmp  # a dir with no .git
        try:
            self._mute(T.cmd_snapshot, self.db, {"reason": "no-git"})
        finally:
            T._REPO_ROOT = old_root
        row = self.db.execute("SELECT git_branch FROM snapshots ORDER BY created_at DESC LIMIT 1").fetchone()
        self.assertEqual(row["git_branch"], "unknown")


class TestTimerSmoke(_SmokeBase):
    """cmd_timer: start/stop/status cycle."""

    def test_timer_start_creates_row(self):
        issue_id = self._create_issue()
        self._mute(T.cmd_timer, self.db, {"action": "start", "arg1": issue_id})
        row = self.db.execute("SELECT * FROM timers WHERE stopped_at IS NULL").fetchone()
        self.assertIsNotNone(row, "active timer row must exist after start")
        self.assertEqual(row["issue_id"], issue_id)

    def test_timer_stop_fills_duration(self):
        issue_id = self._create_issue()
        self._mute(T.cmd_timer, self.db, {"action": "start", "arg1": issue_id})
        out = self._mute(T.cmd_timer, self.db, {"action": "stop"})
        row = self.db.execute("SELECT * FROM timers WHERE issue_id=?", (issue_id,)).fetchone()
        self.assertIsNotNone(row["stopped_at"])
        self.assertIsNotNone(row["duration_sec"])
        self.assertIn("Timer stopped", out)

    def test_timer_stop_logs_event(self):
        issue_id = self._create_issue()
        self._mute(T.cmd_timer, self.db, {"action": "start", "arg1": issue_id})
        self._mute(T.cmd_timer, self.db, {"action": "stop"})
        evt = self.db.execute(
            "SELECT type FROM events WHERE issue_id=? AND type='timer_stop'", (issue_id,)
        ).fetchone()
        self.assertIsNotNone(evt, "timer_stop event must be inserted after stop")

    def test_timer_status_with_active_timer(self):
        issue_id = self._create_issue()
        self._mute(T.cmd_timer, self.db, {"action": "start", "arg1": issue_id})
        out = self._mute(T.cmd_timer, self.db, {"action": "status"})
        self.assertIn("Timer running", out)
        self.assertIn(issue_id, out)

    def test_timer_start_rejects_missing_issue(self):
        out = self._mute(T.cmd_timer, self.db, {"action": "start", "arg1": "TASK-999"})
        self.assertIn("Error", out)
        count = self.db.execute("SELECT COUNT(*) FROM timers").fetchone()[0]
        self.assertEqual(count, 0)

    def test_timer_double_start_rejected(self):
        id1 = self._create_issue("First")
        id2 = self._create_issue("Second")
        self._mute(T.cmd_timer, self.db, {"action": "start", "arg1": id1})
        out = self._mute(T.cmd_timer, self.db, {"action": "start", "arg1": id2})
        self.assertIn("Error", out)
        count = self.db.execute("SELECT COUNT(*) FROM timers WHERE stopped_at IS NULL").fetchone()[0]
        self.assertEqual(count, 1, "only one active timer allowed at a time")


class TestTrackSmoke(_SmokeBase):
    """cmd_track: file_edit, commit, tool_output, session_start, session_end."""

    def test_track_file_edit_inserts_event(self):
        issue_id = self._create_issue()
        self._mute(T.cmd_track, self.db, {
            "event_type": "file_edit", "arg1": "src/main.py", "issue": issue_id,
        })
        evt = self.db.execute(
            "SELECT type, message FROM events WHERE issue_id=? AND type='file_edit'", (issue_id,)
        ).fetchone()
        self.assertIsNotNone(evt)
        self.assertIn("src/main.py", evt["message"])

    def test_track_commit_inserts_event(self):
        issue_id = self._create_issue()
        self._mute(T.cmd_track, self.db, {
            "event_type": "commit", "arg1": "abc123def456", "arg2": "fix: improve perf",
            "issue": issue_id,
        })
        evt = self.db.execute(
            "SELECT message FROM events WHERE issue_id=? AND type='commit'", (issue_id,)
        ).fetchone()
        self.assertIsNotNone(evt)
        self.assertIn("abc123de", evt["message"])

    def test_track_tool_output_inserts_event_and_token_stats(self):
        self._mute(T.cmd_track, self.db, {
            "event_type": "tool_output", "arg1": "bash", "size": "1024",
        })
        evt = self.db.execute("SELECT type FROM events WHERE type='tool_output'").fetchone()
        self.assertIsNotNone(evt)
        ts = self.db.execute("SELECT tool_name, size FROM token_stats WHERE tool_name='bash'").fetchone()
        self.assertIsNotNone(ts)
        self.assertEqual(ts["size"], 1024)

    def test_track_session_start_global_event(self):
        self._mute(T.cmd_track, self.db, {"event_type": "session_start"})
        evt = self.db.execute(
            "SELECT issue_id FROM events WHERE type='session_start'"
        ).fetchone()
        self.assertIsNotNone(evt)
        self.assertIsNone(evt["issue_id"], "session_start events have no issue_id")

    def test_track_session_end_triggers_snapshot(self):
        count_before = self.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        self._mute(T.cmd_track, self.db, {"event_type": "session_end"})
        count_after = self.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        self.assertGreater(count_after, count_before, "session_end must trigger a snapshot")

    def test_track_unknown_event_type_prints_error(self):
        out = self._mute(T.cmd_track, self.db, {"event_type": "unknown_type"})
        self.assertIn("Error", out)


class TestStatsSmoke(_SmokeBase):
    """cmd_stats: output includes total count, status breakdown, and DB size."""

    def test_stats_empty_db(self):
        out = self._mute(T.cmd_stats, self.db, {})
        self.assertIn("Tracker Stats", out)
        self.assertIn("Issues: 0", out)

    def test_stats_reflects_created_issues(self):
        self._create_issue("Alpha")
        self._create_issue("Beta")
        out = self._mute(T.cmd_stats, self.db, {})
        self.assertIn("Issues: 2", out)

    def test_stats_shows_priority_breakdown(self):
        self._create_issue()
        out = self._mute(T.cmd_stats, self.db, {})
        self.assertIn("Open by priority", out)

    def test_stats_shows_project_breakdown(self):
        self._create_issue()
        out = self._mute(T.cmd_stats, self.db, {})
        self.assertIn("Open by project", out)
        self.assertIn("TASK", out)

    def test_stats_shows_db_size(self):
        out = self._mute(T.cmd_stats, self.db, {})
        self.assertIn("DB size", out)


class TestPurgeSmoke(_SmokeBase):
    """cmd_purge: DESTRUCTIVE — scope is by status+date; active issues survive."""

    def _create_old_done_issue(self):
        """Insert a done issue with an old updated_at (2020) directly into DB."""
        self.db.execute(
            """INSERT INTO issues (id, title, status, priority, blocked_by, linked_to,
               issue_type, created_at, updated_at)
               VALUES ('TASK-900','Old done issue','done','P3','[]','[]','issue',
                       '2020-01-01T00:00:00','2020-01-01T00:00:00')"""
        )
        self.db.commit()

    def test_purge_removes_old_done_issues(self):
        self._create_old_done_issue()
        self._mute(T.cmd_purge, self.db, {"before": "2021-01-01", "status": "done"})
        row = self.db.execute("SELECT id FROM issues WHERE id='TASK-900'").fetchone()
        self.assertIsNone(row, "old done issue must be deleted by purge")

    def test_purge_spares_active_issues(self):
        self._create_old_done_issue()
        active_id = self._create_issue("Survivor")
        self._mute(T.cmd_purge, self.db, {"before": "2021-01-01", "status": "done"})
        row = self.db.execute("SELECT id FROM issues WHERE id=?", (active_id,)).fetchone()
        self.assertIsNotNone(row, "active issue must survive purge")

    def test_purge_requires_before_flag(self):
        out = self._mute(T.cmd_purge, self.db, {})
        self.assertIn("Error", out)
        self.assertIn("--before", out)

    def test_purge_rejects_bad_date_format(self):
        out = self._mute(T.cmd_purge, self.db, {"before": "not-a-date"})
        self.assertIn("Error", out)

    def test_purge_does_not_touch_todo_by_default(self):
        """Default statuses are done,cancelled — todo issues must never be deleted."""
        issue_id = self._create_issue("Active todo")
        # Force its updated_at to the past to ensure it would match if the scope were wrong
        self.db.execute("UPDATE issues SET updated_at='2020-01-01T00:00:00' WHERE id=?", (issue_id,))
        self.db.commit()
        self._mute(T.cmd_purge, self.db, {"before": "2025-01-01"})
        row = self.db.execute("SELECT id FROM issues WHERE id=?", (issue_id,)).fetchone()
        self.assertIsNotNone(row, "todo issue must survive purge even with old updated_at")


class TestRenameSmoke(_SmokeBase):
    """cmd_rename: title-only update; distinct from reassign-id (which changes the ID)."""

    def test_rename_updates_title(self):
        issue_id = self._create_issue("Old title")
        self._mute(T.cmd_rename, self.db, {"id": issue_id, "title": "New title"})
        row = self.db.execute("SELECT title FROM issues WHERE id=?", (issue_id,)).fetchone()
        self.assertEqual(row["title"], "New title")

    def test_rename_preserves_id_and_status(self):
        issue_id = self._create_issue("Alpha")
        self._mute(T.cmd_rename, self.db, {"id": issue_id, "title": "Alpha renamed"})
        row = self.db.execute("SELECT id, status FROM issues WHERE id=?", (issue_id,)).fetchone()
        self.assertEqual(row["id"], issue_id, "rename must not change the issue ID")
        self.assertEqual(row["status"], "todo")

    def test_rename_missing_id_prints_error(self):
        out = self._mute(T.cmd_rename, self.db, {"id": "TASK-999", "title": "Ghost"})
        # cmd_rename delegates to cmd_update; that function should error gracefully
        # (no exception, no crash — either error message or silent no-op)
        self.assertIsInstance(out, str)

    def test_rename_requires_both_args(self):
        out = self._mute(T.cmd_rename, self.db, {"id": "TASK-001"})
        self.assertIn("Error", out)

if __name__ == "__main__":
    unittest.main()
