"""Tests for prism/mcp/server.py — MCP tool handlers.

Tests call the tool handler functions directly against a temp DB without
requiring a live MCP transport.  Pattern mirrors test_core.py: env is
bootstrapped via make_env() from test_prism, and TRACKER_DB is patched so
the server opens the test DB instead of the production one.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest

# ---------------------------------------------------------------------------
# Bootstrap sys.path so bare ``import core``, ``import config``, and
# ``from prism.mcp.server import ...`` all resolve correctly.
# ---------------------------------------------------------------------------
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_TESTS_DIR)

# APPEND (not insert-0) to avoid the local mcp/ directory shadowing the
# installed mcp SDK.  The prism package registration (sys.modules["prism"])
# is already handled by conftest.py which runs before this module is
# collected, so insert-at-0 is not needed to resolve the prism package.
if _REPO_ROOT not in sys.path:
    sys.path.append(_REPO_ROOT)

# ---------------------------------------------------------------------------
# Test-config isolation
# ---------------------------------------------------------------------------
# config.py discovers prism.config.toml from the package directory.
# Tests require the built-in default project ("TASK") without interference from
# site-specific config files.  Tests in this file rely on the built-in default project
# ("TASK") and must not be influenced by the site config.  We write a
# minimal config to a temp file; _call_tool() sets PRISM_CONFIG to this
# file for the duration of each tool call and restores the original value
# afterwards — ensuring no env leakage into other test modules.
_TEST_CONFIG_DIR = tempfile.mkdtemp(prefix="prism_test_cfg_")
_TEST_CONFIG_PATH = os.path.join(_TEST_CONFIG_DIR, "test_prism.config.toml")
with open(_TEST_CONFIG_PATH, "w") as _fh:
    _fh.write('[projects]\nTASK = "Tasks"\n')

# Load prism.py (the CLI) via importlib so its helpers are available for DB setup.
_spec = importlib.util.spec_from_file_location(
    "_prism_cli_tests", os.path.join(_REPO_ROOT, "prism.py")
)
T = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(T)


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

def _make_db(tmp_dir: str) -> tuple[sqlite3.Connection, str]:
    """Create a throwaway DB and return (connection, db_path)."""
    state_dir = os.path.join(tmp_dir, "state")
    os.makedirs(state_dir)
    db_path = os.path.join(state_dir, "prism.db")

    # Tell the CLI module to use the test DB so schema init works.
    T.DB_PATH = db_path
    T.STATE_DIR = state_dir

    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    T.init_db(db)
    T.migrate_db(db)
    return db, db_path


# ---------------------------------------------------------------------------
# Helper: call an MCP tool function in isolation by patching TRACKER_DB
# ---------------------------------------------------------------------------

def _call_tool(tool_fn, db_path: str, **kwargs):
    """Patch TRACKER_DB and PRISM_CONFIG, call tool_fn(**kwargs), restore env.

    PRISM_CONFIG is temporarily set to the test-only config (TASK project) so
    calls are isolated from any site-specific prism.config.toml that may exist
    in the developer's checkout.  The original value is restored unconditionally
    in the finally block to avoid leaking into other test modules.
    """
    old_db = os.environ.get("TRACKER_DB")
    old_cfg = os.environ.get("PRISM_CONFIG")
    os.environ["TRACKER_DB"] = db_path
    os.environ["PRISM_CONFIG"] = _TEST_CONFIG_PATH

    # config.load_config() is lru_cached; clear it so the patched values take.
    try:
        import config as _cfg_mod
        _cfg_mod.load_config.cache_clear()
    except Exception:
        pass

    try:
        return tool_fn(**kwargs)
    finally:
        if old_db is None:
            os.environ.pop("TRACKER_DB", None)
        else:
            os.environ["TRACKER_DB"] = old_db
        if old_cfg is None:
            os.environ.pop("PRISM_CONFIG", None)
        else:
            os.environ["PRISM_CONFIG"] = old_cfg
        try:
            _cfg_mod.load_config.cache_clear()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Import tool handlers
# ---------------------------------------------------------------------------

from prism.mcp.server import (  # noqa: E402
    create_issue,
    list_issues,
    get_issue,
    update_issue,
    close_issue,
    comment_issue,
    board,
    search,
    context,
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCreateIssue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db, self.db_path = _make_db(self.tmp)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)

    def _call(self, **kwargs):
        return _call_tool(create_issue, self.db_path, **kwargs)

    def test_minimal_returns_dict_with_id(self):
        result = self._call(title="Test ticket")
        self.assertIsInstance(result, dict)
        self.assertIn("id", result)
        self.assertTrue(result["id"].startswith("TASK-"))

    def test_defaults(self):
        result = self._call(title="Defaults check")
        self.assertEqual(result["status"], "todo")
        self.assertEqual(result["priority"], "P1")
        self.assertEqual(result["assignee"], "claude")
        self.assertEqual(result["model"], "opus")

    def test_custom_project_raises_for_unknown(self):
        # Unknown projects must return an error instead of silently
        # falling back to the default prefix — misfiled issues are hard to find.
        result = self._call(title="Unknown project ticket", project="UNKNOWNXXX")
        self.assertIsInstance(result, dict)
        self.assertIn("error", result)
        self.assertIn("UNKNOWNXXX", result["error"])

    def test_scheduled_at_sets_status(self):
        result = self._call(title="Future", scheduled_at="2026-12-01")
        self.assertEqual(result["status"], "scheduled")
        self.assertIsNotNone(result["scheduled_at"])

    def test_human_assignee_clears_agent_model(self):
        result = self._call(title="Human task", assignee="me", agent="cto", model="sonnet")
        self.assertIsNone(result["agent"])
        self.assertIsNone(result["model"])


class TestListIssues(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db, self.db_path = _make_db(self.tmp)
        # Seed some issues.
        _call_tool(create_issue, self.db_path, title="A", priority="P0")
        _call_tool(create_issue, self.db_path, title="B", priority="P2", assignee="me")

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)

    def _call(self, **kwargs):
        return _call_tool(list_issues, self.db_path, **kwargs)

    def test_returns_list(self):
        result = self._call()
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)

    def test_priority_filter(self):
        result = self._call(priority="P0")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "A")

    def test_assignee_filter(self):
        result = self._call(assignee="me")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "B")

    def test_excludes_done_by_default(self):
        _call_tool(close_issue, self.db_path, id=_call_tool(list_issues, self.db_path)[0]["id"])
        result = self._call()
        self.assertEqual(len(result), 1)

    def test_status_filter_shows_done(self):
        issues = self._call()
        _call_tool(close_issue, self.db_path, id=issues[0]["id"])
        result = self._call(status="done")
        self.assertEqual(len(result), 1)


class TestGetIssue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db, self.db_path = _make_db(self.tmp)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)

    def test_returns_issue(self):
        created = _call_tool(create_issue, self.db_path, title="X", description="brief")
        result = _call_tool(get_issue, self.db_path, id=created["id"])
        self.assertEqual(result["id"], created["id"])
        self.assertEqual(result["description"], "brief")

    def test_not_found_returns_error(self):
        result = _call_tool(get_issue, self.db_path, id="TASK-9999")
        self.assertIn("error", result)


class TestUpdateIssue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db, self.db_path = _make_db(self.tmp)
        self.issue = _call_tool(create_issue, self.db_path, title="Original")

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)

    def _call(self, **kwargs):
        return _call_tool(update_issue, self.db_path, id=self.issue["id"], **kwargs)

    def test_update_title(self):
        result = self._call(title="Updated")
        self.assertEqual(result["issue"]["title"], "Updated")
        self.assertIn("title: Original → Updated", result["changes"])

    def test_update_status(self):
        result = self._call(status="in_progress")
        self.assertEqual(result["issue"]["status"], "in_progress")

    def test_no_changes_returns_empty_changes(self):
        result = self._call()  # nothing to change
        self.assertEqual(result["changes"], [])

    def test_not_found_returns_error(self):
        result = _call_tool(update_issue, self.db_path, id="TASK-9999", title="X")
        self.assertIn("error", result)

    def test_blocked_by_as_csv(self):
        other = _call_tool(create_issue, self.db_path, title="Blocker")
        result = self._call(blocked_by=other["id"])
        self.assertIn(other["id"], result["issue"]["blocked_by"])


class TestCloseIssue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db, self.db_path = _make_db(self.tmp)
        self.issue = _call_tool(create_issue, self.db_path, title="To close")

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)

    def test_close_done(self):
        result = _call_tool(
            close_issue, self.db_path, id=self.issue["id"], resolution="Finished"
        )
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["resolution"], "Finished")
        self.assertIsNotNone(result["closed_at"])

    def test_close_cancelled(self):
        result = _call_tool(
            close_issue, self.db_path, id=self.issue["id"], status="cancelled"
        )
        self.assertEqual(result["status"], "cancelled")

    def test_close_not_found(self):
        result = _call_tool(close_issue, self.db_path, id="TASK-9999")
        self.assertIn("error", result)

    def test_recurrence_spawns_next(self):
        sched = _call_tool(
            create_issue,
            self.db_path,
            title="Weekly job",
            scheduled_at="2026-06-01",
            recurrence="weekly",
        )
        result = _call_tool(
            close_issue, self.db_path, id=sched["id"], resolution="Done"
        )
        self.assertIsNotNone(result.get("_next_issue_id"))
        self.assertIsNotNone(result.get("_next_scheduled_at"))


class TestCommentIssue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db, self.db_path = _make_db(self.tmp)
        self.issue = _call_tool(create_issue, self.db_path, title="Commentable")

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)

    def test_comment_appended(self):
        result = _call_tool(
            comment_issue, self.db_path, id=self.issue["id"], message="Progress note"
        )
        self.assertIsInstance(result, dict)
        self.assertEqual(result["id"], self.issue["id"])

    def test_comment_with_status_transition(self):
        result = _call_tool(
            comment_issue,
            self.db_path,
            id=self.issue["id"],
            message="Moving to in_progress",
            status="in_progress",
        )
        self.assertEqual(result["status"], "in_progress")

    def test_comment_not_found(self):
        result = _call_tool(
            comment_issue, self.db_path, id="TASK-9999", message="X"
        )
        self.assertIn("error", result)


class TestBoard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db, self.db_path = _make_db(self.tmp)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)

    def test_board_returns_expected_keys(self):
        _call_tool(create_issue, self.db_path, title="A")
        created_b = _call_tool(create_issue, self.db_path, title="B")
        _call_tool(update_issue, self.db_path, id=created_b["id"], status="in_progress")
        result = _call_tool(board, self.db_path)
        self.assertIn("epics", result)
        self.assertIn("in_progress", result)
        self.assertIn("todo", result)
        self.assertIn("scheduled_this_week", result)

    def test_board_todo_contains_created_issue(self):
        _call_tool(create_issue, self.db_path, title="Todo task")
        result = _call_tool(board, self.db_path)
        titles = [r["title"] for r in result["todo"]]
        self.assertIn("Todo task", titles)


class TestSearch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db, self.db_path = _make_db(self.tmp)
        _call_tool(
            create_issue,
            self.db_path,
            title="Auth refactor",
            description="JWT and session handling",
        )
        _call_tool(create_issue, self.db_path, title="Database indexing")

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)

    def test_search_returns_list(self):
        result = _call_tool(search, self.db_path, query="auth")
        self.assertIsInstance(result, list)

    def test_search_finds_by_title(self):
        result = _call_tool(search, self.db_path, query="Database")
        titles = [r["title"] for r in result]
        self.assertIn("Database indexing", titles)

    def test_search_no_results(self):
        result = _call_tool(search, self.db_path, query="zzznomatch9999")
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 0)


class TestContext(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db, self.db_path = _make_db(self.tmp)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)

    def test_context_returns_expected_keys(self):
        result = _call_tool(context, self.db_path)
        self.assertIn("active", result)
        self.assertIn("due_soon", result)
        self.assertIn("upcoming_this_week", result)
        self.assertIn("recent_activity", result)

    def test_in_progress_appears_in_active(self):
        created = _call_tool(create_issue, self.db_path, title="Active task")
        _call_tool(update_issue, self.db_path, id=created["id"], status="in_progress")
        result = _call_tool(context, self.db_path)
        active_ids = [r["id"] for r in result["active"]]
        self.assertIn(created["id"], active_ids)


class TestRoundTrip(unittest.TestCase):
    """Integration: create → list → show → update → close."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db, self.db_path = _make_db(self.tmp)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)

    def test_full_lifecycle(self):
        # Create
        created = _call_tool(
            create_issue,
            self.db_path,
            title="Lifecycle test",
            description="Full round-trip",
            priority="P2",
        )
        issue_id = created["id"]
        self.assertTrue(issue_id.startswith("TASK-"))
        self.assertEqual(created["status"], "todo")

        # List — appears in todo
        listed = _call_tool(list_issues, self.db_path)
        ids = [r["id"] for r in listed]
        self.assertIn(issue_id, ids)

        # Show
        shown = _call_tool(get_issue, self.db_path, id=issue_id)
        self.assertEqual(shown["description"], "Full round-trip")

        # Update — mark in_progress
        updated = _call_tool(
            update_issue, self.db_path, id=issue_id, status="in_progress"
        )
        self.assertEqual(updated["issue"]["status"], "in_progress")

        # Comment
        commented = _call_tool(
            comment_issue,
            self.db_path,
            id=issue_id,
            message="Half done",
        )
        self.assertEqual(commented["status"], "in_progress")

        # Close
        closed = _call_tool(
            close_issue,
            self.db_path,
            id=issue_id,
            resolution="All done",
            files="src/foo.py,src/bar.py",
            refs="docs/spec.md",
        )
        self.assertEqual(closed["status"], "done")
        self.assertEqual(closed["resolution"], "All done")

        # No longer appears in default list (excludes done)
        after = _call_tool(list_issues, self.db_path)
        ids_after = [r["id"] for r in after]
        self.assertNotIn(issue_id, ids_after)


if __name__ == "__main__":
    unittest.main()
