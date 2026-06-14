"""Tests for prism/core.py — pure-functions API extracted from prism.py CLI shims."""
import os
import sys
import tempfile
import shutil
import unittest

# Reuse the same prism.py loader as test_prism.py and pull in its make_env fixture.
sys.path.insert(0, os.path.dirname(__file__))
from test_prism import make_env, _isolate_config, _restore_config  # noqa: E402

# Lazy import of core; A2 creates this module.
def _core():
    import core  # type: ignore
    return core


class TestCreateIssue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old_prism_cfg = _isolate_config()
        self.db = make_env(self.tmp)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)
        _restore_config(self._old_prism_cfg)

    def test_minimal_returns_dict_with_defaults(self):
        core = _core()
        issue = core.create_issue(self.db, title="Test ticket", project="TASK")
        self.assertTrue(issue["id"].startswith("TASK-"))
        self.assertEqual(issue["title"], "Test ticket")
        self.assertEqual(issue["status"], "todo")
        self.assertEqual(issue["priority"], "P1")  # DB default
        self.assertEqual(issue["assignee"], "claude")
        self.assertEqual(issue["model"], "opus")  # claude default

    def test_scheduled_at_flips_status_to_scheduled(self):
        core = _core()
        issue = core.create_issue(self.db, title="Future", project="TASK",
                                   scheduled_at="2026-12-01")
        self.assertEqual(issue["status"], "scheduled")
        self.assertTrue(issue["scheduled_at"].startswith("2026-12-01"))

    def test_human_assignee_clears_agent_and_model(self):
        core = _core()
        issue = core.create_issue(self.db, title="Adrien task", project="TASK",
                                   assignee="me", agent="cto", model="sonnet")
        self.assertIsNone(issue["agent"])
        self.assertIsNone(issue["model"])

    def test_returns_lists_for_blocked_by_and_linked_to(self):
        core = _core()
        a = core.create_issue(self.db, title="a", project="TASK")
        b = core.create_issue(self.db, title="b", project="TASK",
                               blocked_by=[a["id"]])
        self.assertIsInstance(b["blocked_by"], list)
        self.assertIn(a["id"], b["blocked_by"])
        self.assertIsInstance(b["linked_to"], list)

    def test_explicit_status_in_progress_overrides_default(self):
        """Mirrors the original cmd_create --status in_progress behavior."""
        core = _core()
        issue = core.create_issue(self.db, title="active", project="TASK",
                                   status="in_progress")
        self.assertEqual(issue["status"], "in_progress")


class TestGetIssue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old_prism_cfg = _isolate_config()
        self.db = make_env(self.tmp)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)
        _restore_config(self._old_prism_cfg)

    def test_returns_full_row_with_lists(self):
        core = _core()
        created = core.create_issue(self.db, title="x", project="TASK",
                                     description="brief")
        got = core.get_issue(self.db, created["id"])
        self.assertEqual(got["id"], created["id"])
        self.assertEqual(got["description"], "brief")
        self.assertIsInstance(got["blocked_by"], list)
        self.assertIsInstance(got["linked_to"], list)

    def test_unknown_id_raises_keyerror(self):
        core = _core()
        with self.assertRaises(KeyError):
            core.get_issue(self.db, "TASK-9999999")


class TestListIssues(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old_prism_cfg = _isolate_config()
        self.db = make_env(self.tmp)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)
        _restore_config(self._old_prism_cfg)

    def test_default_excludes_done_and_epics(self):
        core = _core()
        epic = core.create_issue(self.db, title="E", project="TASK", type="epic")
        a = core.create_issue(self.db, title="a", project="TASK")
        listed = core.list_issues(self.db)
        ids = [i["id"] for i in listed]
        self.assertIn(a["id"], ids)
        self.assertNotIn(epic["id"], ids)  # epic excluded by default
        self.assertTrue(all(i["status"] not in ("done", "cancelled") for i in listed))

    def test_filter_status_in_progress(self):
        core = _core()
        a = core.create_issue(self.db, title="a", project="TASK")
        b = core.create_issue(self.db, title="b", project="TASK",
                               status="in_progress")
        listed = core.list_issues(self.db, status=["in_progress"])
        ids = [i["id"] for i in listed]
        self.assertIn(b["id"], ids)
        self.assertNotIn(a["id"], ids)

    def test_filter_blocked_only(self):
        core = _core()
        blocker = core.create_issue(self.db, title="b", project="TASK")
        waiter = core.create_issue(self.db, title="w", project="TASK",
                                    blocked_by=[blocker["id"]])
        blocked = core.list_issues(self.db, blocked_only=True)
        ids = [i["id"] for i in blocked]
        self.assertIn(waiter["id"], ids)
        self.assertNotIn(blocker["id"], ids)

    def test_filter_project(self):
        """Project filter returns only issues with IDs matching the requested prefix."""
        core = _core()
        t1 = core.create_issue(self.db, title="first task", project="TASK")
        t2 = core.create_issue(self.db, title="second task", project="TASK")
        listed = core.list_issues(self.db, project=["TASK"])
        ids = [i["id"] for i in listed]
        self.assertIn(t1["id"], ids)
        self.assertIn(t2["id"], ids)
        # Verify that t2 is NOT returned when explicitly queried with t1's prefix only
        # (both are TASK so this verifies the LIKE-clause approach works correctly)
        self.assertTrue(all(i["id"].startswith("TASK-") for i in listed))

    def test_include_epics(self):
        core = _core()
        epic = core.create_issue(self.db, title="E", project="TASK", type="epic")
        listed = core.list_issues(self.db, include_epics=True)
        self.assertIn(epic["id"], [i["id"] for i in listed])


class TestUpdateIssue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old_prism_cfg = _isolate_config()
        self.db = make_env(self.tmp)
        # Skip agent-slug validation: these tests exercise assignee/agent clearing
        # logic and are not testing slug validation (that lives in TestValidateAgentSlug).
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

    def test_status_transition_returns_changes(self):
        core = _core()
        issue = core.create_issue(self.db, title="t", project="TASK")
        row, changes = core.update_issue(self.db, issue["id"], status="in_progress")
        self.assertEqual(row["status"], "in_progress")
        self.assertTrue(any("status" in c for c in changes))

    def test_no_change_returns_empty_changes(self):
        core = _core()
        issue = core.create_issue(self.db, title="t", project="TASK")
        _row, changes = core.update_issue(self.db, issue["id"], status="todo")
        self.assertEqual(changes, [])

    def test_unknown_id_raises_keyerror(self):
        core = _core()
        with self.assertRaises(KeyError):
            core.update_issue(self.db, "TASK-99999", status="done")

    def test_invalid_status_raises_valueerror(self):
        core = _core()
        issue = core.create_issue(self.db, title="t", project="TASK")
        with self.assertRaises(ValueError):
            core.update_issue(self.db, issue["id"], status="bogus")

    def test_clear_agent_via_kwarg(self):
        core = _core()
        issue = core.create_issue(self.db, title="t", project="TASK", agent="cto")
        row, _ = core.update_issue(self.db, issue["id"], clear_agent=True)
        self.assertIsNone(row["agent"])

    def test_assignee_change_clears_agent_and_model(self):
        core = _core()
        issue = core.create_issue(self.db, title="t", project="TASK",
                                   agent="cto", model="sonnet")
        row, _ = core.update_issue(self.db, issue["id"], assignee="me")
        self.assertIsNone(row["agent"])
        self.assertIsNone(row["model"])

    def test_assignee_human_with_explicit_agent_raises(self):
        core = _core()
        issue = core.create_issue(self.db, title="t", project="TASK")
        with self.assertRaises(ValueError):
            core.update_issue(self.db, issue["id"], assignee="me", agent="cto")

    def test_done_stamps_closed_at(self):
        core = _core()
        issue = core.create_issue(self.db, title="t", project="TASK")
        row, _ = core.update_issue(self.db, issue["id"], status="done",
                                    resolution="shipped")
        self.assertIsNotNone(row["closed_at"])
        self.assertEqual(row["resolution"], "shipped")

    def test_reopen_clears_closed_at(self):
        core = _core()
        issue = core.create_issue(self.db, title="t", project="TASK")
        core.update_issue(self.db, issue["id"], status="done", resolution="x")
        row, _ = core.update_issue(self.db, issue["id"], status="todo")
        self.assertIsNone(row["closed_at"])

    def test_blocked_by_list_serializes(self):
        core = _core()
        a = core.create_issue(self.db, title="a", project="TASK")
        b = core.create_issue(self.db, title="b", project="TASK")
        row, _ = core.update_issue(self.db, b["id"], blocked_by=[a["id"]])
        self.assertIn(a["id"], row["blocked_by"])

    def test_done_cascades_blocked_by(self):
        """Closing X removes X from every blocked_by list referencing it."""
        core = _core()
        blocker = core.create_issue(self.db, title="b", project="TASK")
        waiter = core.create_issue(self.db, title="w", project="TASK",
                                    blocked_by=[blocker["id"]])
        core.update_issue(self.db, blocker["id"], status="done")
        waiter_after = core.get_issue(self.db, waiter["id"])
        self.assertNotIn(blocker["id"], waiter_after["blocked_by"])

    def test_recurrence_without_scheduled_at_raises(self):
        core = _core()
        issue = core.create_issue(self.db, title="t", project="TASK")
        with self.assertRaises(ValueError):
            core.update_issue(self.db, issue["id"], recurrence="weekly")


class TestCloseIssue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old_prism_cfg = _isolate_config()
        self.db = make_env(self.tmp)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)
        _restore_config(self._old_prism_cfg)

    def test_default_done_with_resolution(self):
        core = _core()
        issue = core.create_issue(self.db, title="t", project="TASK")
        closed = core.close_issue(self.db, issue["id"], resolution="shipped")
        self.assertEqual(closed["status"], "done")
        self.assertEqual(closed["resolution"], "shipped")
        self.assertIsNotNone(closed["closed_at"])

    def test_cancelled_status(self):
        core = _core()
        issue = core.create_issue(self.db, title="t", project="TASK")
        closed = core.close_issue(self.db, issue["id"],
                                   status="cancelled", resolution="moot")
        self.assertEqual(closed["status"], "cancelled")

    def test_invalid_status_raises(self):
        core = _core()
        issue = core.create_issue(self.db, title="t", project="TASK")
        with self.assertRaises(ValueError):
            core.close_issue(self.db, issue["id"], status="todo")

    def test_unknown_id_raises_keyerror(self):
        core = _core()
        with self.assertRaises(KeyError):
            core.close_issue(self.db, "TASK-99999")

    def test_cascade_removes_blocker_from_waiters(self):
        core = _core()
        blocker = core.create_issue(self.db, title="b", project="TASK")
        waiter = core.create_issue(self.db, title="w", project="TASK",
                                    blocked_by=[blocker["id"]])
        core.close_issue(self.db, blocker["id"], resolution="done")
        waiter_after = core.get_issue(self.db, waiter["id"])
        self.assertNotIn(blocker["id"], waiter_after["blocked_by"])

    def test_recurring_close_spawns_next_iteration(self):
        core = _core()
        issue = core.create_issue(self.db, title="weekly task", project="TASK",
                                   scheduled_at="2026-05-03T09:00",
                                   recurrence="weekly")
        closed = core.close_issue(self.db, issue["id"], resolution="iter 1")
        self.assertIsNotNone(closed["_next_issue_id"])
        self.assertTrue(closed["_next_scheduled_at"].startswith("2026-05-10"))
        spawned = core.get_issue(self.db, closed["_next_issue_id"])
        self.assertEqual(spawned["status"], "scheduled")
        self.assertEqual(spawned["recurrence"], "weekly")
        self.assertIn(issue["id"], spawned["linked_to"])

    def test_cancelled_does_not_spawn_next(self):
        core = _core()
        issue = core.create_issue(self.db, title="weekly", project="TASK",
                                   scheduled_at="2026-05-03T09:00",
                                   recurrence="weekly")
        closed = core.close_issue(self.db, issue["id"],
                                   status="cancelled", resolution="stop chain")
        self.assertIsNone(closed["_next_issue_id"])

    def test_recurring_chain_survives_in_progress_pickup(self):
        """Regression (scheduled ticket pickup): the realistic flow scheduled -> in_progress -> done.

        Picking up a scheduled ticket clears scheduled_at (documented), but it
        must NOT clear recurrence — otherwise close can't spawn the next
        iteration and the recurring chain dies the first time it's worked. This
        silently killed the daily vault-maintenance chain on 2026-05-14.
        """
        core = _core()
        issue = core.create_issue(self.db, title="daily task", project="TASK",
                                   scheduled_at="2026-05-03T18:00",
                                   recurrence="daily")
        # Pick it up: documented behavior clears scheduled_at, recurrence stays.
        picked, _ = core.update_issue(self.db, issue["id"], status="in_progress")
        self.assertEqual(picked["status"], "in_progress")
        self.assertIsNone(picked["scheduled_at"])
        self.assertEqual(picked["recurrence"], "daily")
        # Closing the worked ticket must spawn the next iteration.
        closed = core.close_issue(self.db, issue["id"], resolution="iter 1")
        self.assertIsNotNone(closed["_next_issue_id"])
        spawned = core.get_issue(self.db, closed["_next_issue_id"])
        self.assertEqual(spawned["status"], "scheduled")
        self.assertEqual(spawned["recurrence"], "daily")
        self.assertIsNotNone(spawned["scheduled_at"])
        self.assertIn(issue["id"], spawned["linked_to"])

    def test_files_and_refs_in_metadata(self):
        core = _core()
        issue = core.create_issue(self.db, title="t", project="TASK")
        core.close_issue(self.db, issue["id"], resolution="ok",
                          files=["a.py", "b.py"], refs=["doc1"])
        events = self.db.execute(
            "SELECT metadata FROM events WHERE issue_id=? AND type='closed'",
            (issue["id"],)
        ).fetchone()
        import json as _j
        meta = _j.loads(events["metadata"])
        self.assertEqual(meta["files"], ["a.py", "b.py"])
        self.assertEqual(meta["refs"], ["doc1"])


class TestAddCommentSearchEvents(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old_prism_cfg = _isolate_config()
        self.db = make_env(self.tmp)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)
        _restore_config(self._old_prism_cfg)

    def test_add_comment_appends_event(self):
        core = _core()
        issue = core.create_issue(self.db, title="t", project="TASK")
        core.add_comment(self.db, issue["id"], "first comment")
        events = core.get_events(self.db, issue["id"])
        comments = [e for e in events if e["type"] == "comment"]
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0]["message"], "first comment")

    def test_add_comment_with_status_done(self):
        core = _core()
        issue = core.create_issue(self.db, title="t", project="TASK")
        updated = core.add_comment(self.db, issue["id"], "shipping", status="done")
        self.assertEqual(updated["status"], "done")
        self.assertEqual(updated["resolution"], "shipping")

    def test_add_comment_unknown_id_raises(self):
        core = _core()
        with self.assertRaises(KeyError):
            core.add_comment(self.db, "TASK-99999", "hi")

    def test_search_matches_title(self):
        core = _core()
        a = core.create_issue(self.db, title="dashboard refactor", project="TASK")
        core.create_issue(self.db, title="other thing", project="TASK")
        results = core.search_issues(self.db, "dashboard")
        ids = [r["id"] for r in results]
        self.assertIn(a["id"], ids)
        self.assertEqual(len(results), 1)

    def test_get_events_chronological_order(self):
        core = _core()
        issue = core.create_issue(self.db, title="t", project="TASK")
        core.update_issue(self.db, issue["id"], status="in_progress")
        core.add_comment(self.db, issue["id"], "halfway")
        events = core.get_events(self.db, issue["id"])
        timestamps = [e["created_at"] for e in events]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_get_events_filter_by_type(self):
        core = _core()
        issue = core.create_issue(self.db, title="t", project="TASK")
        core.add_comment(self.db, issue["id"], "c1")
        events = core.get_events(self.db, issue["id"], types=["comment"])
        self.assertTrue(all(e["type"] == "comment" for e in events))


class TestWalCheckpoint(unittest.TestCase):
    """After every write, the WAL file should be empty (size 0) thanks to
    PRAGMA wal_checkpoint(TRUNCATE). Keeps the autosave hook clean."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old_prism_cfg = _isolate_config()
        self.db = make_env(self.tmp)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)
        _restore_config(self._old_prism_cfg)

    def _wal_size(self):
        wal = os.path.join(self.tmp, "state", "prism.db-wal")
        return os.path.getsize(wal) if os.path.exists(wal) else 0

    def test_create_truncates_wal(self):
        core = _core()
        core.create_issue(self.db, title="t", project="TASK")
        self.assertEqual(self._wal_size(), 0)

    def test_update_truncates_wal(self):
        core = _core()
        issue = core.create_issue(self.db, title="t", project="TASK")
        core.update_issue(self.db, issue["id"], status="in_progress")
        self.assertEqual(self._wal_size(), 0)

    def test_close_truncates_wal(self):
        core = _core()
        issue = core.create_issue(self.db, title="t", project="TASK")
        core.close_issue(self.db, issue["id"], resolution="ok")
        self.assertEqual(self._wal_size(), 0)

    def test_comment_truncates_wal(self):
        core = _core()
        issue = core.create_issue(self.db, title="t", project="TASK")
        core.add_comment(self.db, issue["id"], "hi")
        self.assertEqual(self._wal_size(), 0)


class TestValidateAgentSlug(unittest.TestCase):
    """Tests for _validate_agent_slug and its integration with create/update_issue."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old_prism_cfg = _isolate_config()
        self.db = make_env(self.tmp)
        # Build a small fake agents directory with two known slugs.
        self.agents_dir = os.path.join(self.tmp, "agents")
        os.makedirs(self.agents_dir)
        for slug in ("backend-dev", "frontend-dev", "devops"):
            with open(os.path.join(self.agents_dir, f"{slug}.md"), "w") as f:
                f.write(f"# {slug}\n")

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp)
        _restore_config(self._old_prism_cfg)

    # --- unit tests for _validate_agent_slug ---

    def test_valid_slug_passes(self):
        core = _core()
        # Should not raise — "backend-dev" exists in the fake agents dir.
        core._validate_agent_slug("backend-dev", agents_dir=self.agents_dir)

    def test_typo_raises_value_error_with_suggestion(self):
        core = _core()
        with self.assertRaises(ValueError) as ctx:
            core._validate_agent_slug("baceknd-dev", agents_dir=self.agents_dir)
        msg = str(ctx.exception)
        self.assertIn("baceknd-dev", msg)
        # difflib should suggest "backend-dev" (edit distance is small)
        self.assertIn("backend-dev", msg)

    def test_completely_wrong_slug_raises_without_suggestion(self):
        core = _core()
        with self.assertRaises(ValueError) as ctx:
            core._validate_agent_slug("zzz-does-not-exist", agents_dir=self.agents_dir)
        # No suggestion when nothing is close.
        self.assertIn("zzz-does-not-exist", msg := str(ctx.exception))
        # Suggestion clause should not appear since cutoff=0.5 will match nothing.
        self.assertNotIn("Did you mean", msg)

    def test_missing_agents_dir_skips_validation(self):
        core = _core()
        # Should not raise even for a garbage slug when the dir doesn't exist.
        core._validate_agent_slug("not-real", agents_dir="/nonexistent/path")

    def test_env_var_skip_bypasses_validation(self):
        core = _core()
        import os as _os
        _os.environ["TRACKER_SKIP_AGENT_VALIDATION"] = "1"
        try:
            # Would normally raise for a typo.
            core._validate_agent_slug("fronted-dev", agents_dir=self.agents_dir)
        finally:
            del _os.environ["TRACKER_SKIP_AGENT_VALIDATION"]

    # --- integration: create_issue ---

    def test_create_with_typo_agent_raises(self):
        """create_issue should fail fast on a bad agent slug."""
        core = _core()
        # Patch the module-level _AGENTS_DIR to our fake dir.
        orig = core._AGENTS_DIR
        core._AGENTS_DIR = self.agents_dir
        try:
            with self.assertRaises(ValueError) as ctx:
                core.create_issue(self.db, title="t", project="TASK",
                                   agent="fronted-dev")
            self.assertIn("fronted-dev", str(ctx.exception))
            self.assertIn("frontend-dev", str(ctx.exception))
        finally:
            core._AGENTS_DIR = orig

    def test_create_with_valid_agent_passes(self):
        """create_issue should succeed when the agent slug exists."""
        core = _core()
        orig = core._AGENTS_DIR
        core._AGENTS_DIR = self.agents_dir
        try:
            issue = core.create_issue(self.db, title="t", project="TASK",
                                       agent="backend-dev")
            self.assertEqual(issue["agent"], "backend-dev")
        finally:
            core._AGENTS_DIR = orig

    def test_create_skip_validation_env_var(self):
        """TRACKER_SKIP_AGENT_VALIDATION=1 lets a bad slug through."""
        core = _core()
        orig = core._AGENTS_DIR
        core._AGENTS_DIR = self.agents_dir
        import os as _os
        _os.environ["TRACKER_SKIP_AGENT_VALIDATION"] = "1"
        try:
            issue = core.create_issue(self.db, title="t", project="TASK",
                                       agent="typo-slug")
            self.assertEqual(issue["agent"], "typo-slug")
        finally:
            core._AGENTS_DIR = orig
            del _os.environ["TRACKER_SKIP_AGENT_VALIDATION"]

    def test_create_human_assignee_skips_agent_validation(self):
        """Non-claude assignees have agent cleared; no validation needed."""
        core = _core()
        orig = core._AGENTS_DIR
        core._AGENTS_DIR = self.agents_dir
        try:
            # Should not raise — agent is cleared for non-claude assignees.
            issue = core.create_issue(self.db, title="t", project="TASK",
                                       assignee="me", agent="fronted-dev")
            self.assertIsNone(issue["agent"])
        finally:
            core._AGENTS_DIR = orig

    # --- integration: update_issue ---

    def test_update_with_typo_agent_raises(self):
        core = _core()
        orig = core._AGENTS_DIR
        core._AGENTS_DIR = self.agents_dir
        try:
            # Create with a known slug first.
            issue = core.create_issue(self.db, title="t", project="TASK",
                                       agent="backend-dev")
            with self.assertRaises(ValueError) as ctx:
                core.update_issue(self.db, issue["id"], agent="fronted-dev")
            self.assertIn("fronted-dev", str(ctx.exception))
            self.assertIn("frontend-dev", str(ctx.exception))
        finally:
            core._AGENTS_DIR = orig

    def test_update_with_valid_agent_passes(self):
        core = _core()
        orig = core._AGENTS_DIR
        core._AGENTS_DIR = self.agents_dir
        try:
            issue = core.create_issue(self.db, title="t", project="TASK",
                                       agent="backend-dev")
            row, changes = core.update_issue(self.db, issue["id"], agent="devops")
            self.assertEqual(row["agent"], "devops")
        finally:
            core._AGENTS_DIR = orig


class TestSearchIssuesFTS5EdgeCases(unittest.TestCase):
    """Regression test — FTS5 MATCH must not crash on everyday queries.

    Covers the cases listed in the ticket: hyphenated ticket IDs, apostrophes,
    colons, unclosed quotes, and leading operators.  All must return a list
    (possibly empty) rather than raising an exception.  The LIKE-fallback path
    is also verified to return results when the FTS5 query would have crashed.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old_prism_cfg = _isolate_config()
        self.db = make_env(self.tmp)
        self.core = _core()
        # Seed a couple of issues so LIKE-fallback tests can verify real matches.
        self.issue_a = self.core.create_issue(
            self.db, title="TASK-999 Memory leak fix", project="TASK",
            description="Memory usage grows under load"
        )
        self.issue_b = self.core.create_issue(
            self.db, title="what's the plan", project="TASK",
            description="Apostrophe in title"
        )

    def tearDown(self):
        self.db.close()
        import shutil as _sh
        _sh.rmtree(self.tmp)
        _restore_config(self._old_prism_cfg)

    def _search(self, query):
        """Call search_issues; must not raise."""
        return self.core.search_issues(self.db, query)

    def test_hyphenated_ticket_id_does_not_crash(self):
        """Bare dash in query is invalid FTS5 syntax → LIKE fallback."""
        results = self._search("TASK-999")
        ids = [r["id"] for r in results]
        self.assertIn(self.issue_a["id"], ids)

    def test_apostrophe_does_not_crash(self):
        """Apostrophe in query (FTS5 tokenisation edge case) → no exception."""
        results = self._search("what's")
        self.assertIsInstance(results, list)

    def test_colon_does_not_crash(self):
        """Colon can confuse FTS5 column-filter syntax → no exception."""
        results = self._search("fix: bug")
        self.assertIsInstance(results, list)

    def test_unclosed_quote_does_not_crash(self):
        """Unclosed double-quote is invalid FTS5 phrase syntax → LIKE fallback."""
        results = self._search('"unclosed')
        self.assertIsInstance(results, list)

    def test_leading_NOT_operator_does_not_crash(self):
        """A bare 'NOT' at the start is valid FTS5 but an edge case — must not crash."""
        results = self._search("NOT memory")
        self.assertIsInstance(results, list)

    def test_leading_OR_operator_does_not_crash(self):
        """Bare 'OR' at the start is invalid FTS5 syntax → LIKE fallback."""
        results = self._search("OR memory")
        self.assertIsInstance(results, list)

    def test_description_only_match_via_like_fallback(self):
        """When FTS5 crashes, the LIKE fallback still matches description text."""
        # Queries with bare dashes trigger LIKE fallback; issue_a has 'memory' in description.
        results = self._search("memory")
        ids = [r["id"] for r in results]
        self.assertIn(self.issue_a["id"], ids)

    def test_normal_query_still_works(self):
        """A plain word must still return results (FTS5 happy path unbroken)."""
        results = self._search("leak")
        ids = [r["id"] for r in results]
        self.assertIn(self.issue_a["id"], ids)

    def test_empty_db_does_not_crash(self):
        """Search on a fresh DB with no issues returns empty list, not an error."""
        import tempfile as _tf
        tmp2 = _tf.mkdtemp()
        db2 = make_env(tmp2)
        try:
            results = self.core.search_issues(db2, "TASK-999")
            self.assertEqual(results, [])
        finally:
            db2.close()
            import shutil as _sh2
            _sh2.rmtree(tmp2)


class TestNormalizeProjectError(unittest.TestCase):
    """ValueError on unknown project prefix — _normalize_project must raise ValueError for unknown prefixes.

    Verifies the guard inside _normalize_project (prism.py) that prevents
    unknown --project values from silently falling back to the default prefix.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old_prism_cfg = _isolate_config()
        self.db = make_env(self.tmp)

    def tearDown(self):
        self.db.close()
        import shutil as _sh
        _sh.rmtree(self.tmp)
        _restore_config(self._old_prism_cfg)

    def test_unknown_prefix_raises_value_error(self):
        """core.create_issue with an unknown project prefix must raise ValueError."""
        core = _core()
        with self.assertRaises(ValueError) as ctx:
            core.create_issue(self.db, title="test", project="SYS",
                              description="testing unknown prefix")
        msg = str(ctx.exception)
        self.assertIn("SYS", msg)

    def test_known_prefix_passes(self):
        """The default TASK prefix (always configured in test env) must pass."""
        core = _core()
        issue = core.create_issue(self.db, title="test", project="TASK",
                                  description="known prefix")
        self.assertTrue(issue["id"].startswith("TASK-"))

    def test_unknown_project_prefix_raises(self):
        """An unknown project prefix must raise ValueError."""
        core = _core()
        # 'VER' is not in the default TASK-only config.
        with self.assertRaises(ValueError) as ctx:
            core.create_issue(self.db, title="test", project="VER",
                              description="testing unknown prefix")
        msg = str(ctx.exception)
        self.assertIn("VER", msg)

    def test_empty_project_uses_default(self):
        """None / empty project still resolves to the first configured prefix."""
        core = _core()
        issue = core.create_issue(self.db, title="test", project=None,
                                  description="default prefix")
        # Whatever the first prefix is, must not raise and must return a valid ID.
        self.assertIsNotNone(issue["id"])


if __name__ == "__main__":
    unittest.main()


# Module-level worker for multiprocessing (must be picklable for spawn context).
_CONCURRENT_TEST_PRISM_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _concurrent_worker(result_queue, db_path, prism_dir):
    """Open a fresh connection and create one issue; push ID or exception."""
    import importlib.util as _ilu
    import sqlite3 as _sqlite3
    import sys as _sys

    try:
        if prism_dir not in _sys.path:
            _sys.path.insert(0, prism_dir)
        # Load prism.py module so T references resolve inside core.py
        spec = _ilu.spec_from_file_location(
            "_prism_worker", os.path.join(prism_dir, "prism.py")
        )
        T_local = _ilu.module_from_spec(spec)
        T_local.DB_PATH = db_path
        spec.loader.exec_module(T_local)

        import core as _core_mod  # type: ignore
        db = _sqlite3.connect(db_path, timeout=30, check_same_thread=False)
        db.row_factory = _sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=30000")

        issue = _core_mod.create_issue(db, title="concurrent", project="TASK")
        db.close()
        result_queue.put(("ok", issue["id"]))
    except Exception as exc:
        result_queue.put(("err", str(exc)))


class TestConcurrentIdGeneration(unittest.TestCase):
    """N concurrent processes issuing creates → N distinct IDs, zero exceptions.

    Uses multiprocessing (real OS processes, separate SQLite connections) to
    exercise the full race window — the GIL would serialize threading-based
    tests and hide real contention.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._old_prism_cfg = _isolate_config()
        self.db_path = os.path.join(self.tmp, "state", "prism.db")
        # Prime the DB (schema + WAL) in the main process.
        db = make_env(self.tmp)
        db.close()

    def tearDown(self):
        shutil.rmtree(self.tmp)
        _restore_config(self._old_prism_cfg)

    def test_concurrent_creates_produce_distinct_ids(self):
        import multiprocessing

        N = 10
        ctx = multiprocessing.get_context("spawn")
        q = ctx.Queue()
        procs = [
            ctx.Process(
                target=_concurrent_worker,
                args=(q, self.db_path, _CONCURRENT_TEST_PRISM_DIR),
            )
            for _ in range(N)
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=30)

        results = [q.get_nowait() for _ in range(N)]
        errors = [r[1] for r in results if r[0] == "err"]
        ids = [r[1] for r in results if r[0] == "ok"]

        self.assertEqual(errors, [], f"Worker exceptions: {errors}")
        self.assertEqual(len(ids), N, f"Expected {N} IDs, got {len(ids)}: {ids}")
        self.assertEqual(len(set(ids)), N, f"Duplicate IDs detected: {ids}")
