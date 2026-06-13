"""UserPromptSubmit hook helper: surface issues created since last check.

Prints a short notice block when new issues exist, then advances the
watermark to the most recent `created_at` so the same issue is never
re-flagged. Silent when nothing is new.

Watermark file: prism/state/.last_seen_issue_at — single ISO timestamp
line. Per-machine state, not committed (covered by .gitignore for prism/state/.*).

Usage (called from .claude/hooks/prism-new.sh):
    python3 prism/check_new.py

Exit code is always 0 — this hook never blocks the user prompt.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "prism" / "state" / "runloq.db"
WATERMARK = REPO / "prism" / "state" / ".last_seen_issue_at"

# Cap output so a batch import doesn't flood the prompt context.
MAX_LINES = 8


def read_watermark() -> str:
    """Return the last-seen ISO timestamp, or default to 24h ago on first run."""
    if WATERMARK.exists():
        try:
            v = WATERMARK.read_text().strip()
            if v:
                return v
        except OSError:
            pass
    return (datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds")


def write_watermark(ts: str) -> None:
    try:
        WATERMARK.parent.mkdir(parents=True, exist_ok=True)
        WATERMARK.write_text(ts + "\n")
    except OSError:
        pass


def actionable_for_claude(row: sqlite3.Row) -> bool:
    """A ticket Claude could pick up: assigned to claude, not closed, not blocked."""
    if row["assignee"] != "claude":
        return False
    if row["status"] in ("done", "cancelled"):
        return False
    blocked = row["blocked_by"] or ""
    return blocked.strip() in ("", "[]")


def main() -> int:
    if not DB.exists():
        return 0
    last_seen = read_watermark()

    try:
        conn = sqlite3.connect(str(DB))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, title, status, priority, assignee, agent, model,
                   issue_type, created_at, blocked_by
            FROM issues
            WHERE created_at > ?
            ORDER BY created_at ASC
            """,
            (last_seen,),
        ).fetchall()
        conn.close()
    except sqlite3.Error:
        return 0

    if not rows:
        return 0

    # Advance watermark to most recent created_at — anything Claude creates
    # during this turn will land after this and surface on the next turn.
    newest = max(r["created_at"] for r in rows)
    write_watermark(newest)

    p0 = [r for r in rows if r["priority"] == "P0"]
    pickups = [r for r in rows if actionable_for_claude(r)]

    lines: list[str] = []
    header = f"📥 {len(rows)} new issue{'s' if len(rows) != 1 else ''} since last turn"
    if p0:
        header += f" ({len(p0)} P0)"
    lines.append(header)

    shown = rows[:MAX_LINES]
    for r in shown:
        epic = " [epic]" if r["issue_type"] == "epic" else ""
        owner = f"@{r['assignee']}"
        prio = r["priority"]
        # Sortable, non-noisy single-line summary.
        lines.append(f"  {r['id']} {prio}{epic}  {r['title'][:80]}  ({r['status']}, {owner})")
    if len(rows) > MAX_LINES:
        lines.append(f"  +{len(rows) - MAX_LINES} more — see board or `prism.py list`")

    if pickups:
        ids = ", ".join(p["id"] for p in pickups[:3])
        more = f" +{len(pickups) - 3} more" if len(pickups) > 3 else ""
        lines.append(
            f"💡 Pickup candidates ({len(pickups)} actionable for @claude): {ids}{more} — suggest one when responding."
        )

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
