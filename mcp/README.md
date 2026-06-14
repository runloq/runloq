# runloq MCP Server

Exposes the runloq issue tracker as an [MCP](https://modelcontextprotocol.io/) server
so any MCP-capable agent (Claude Code, Cursor, Codex) can drive the tracker
programmatically over the stdio transport — no CLI, no UI required.

## Tools

| Tool | Description |
|------|-------------|
| `create_issue` | Create a new issue (title, description, project, priority, assignee, agent, model, scheduled_at, recurrence, type) |
| `list_issues` | List issues with optional filters (status, project, priority, assignee, type) |
| `get_issue` | Fetch the full details of a single issue by ID |
| `update_issue` | Update one or more fields of an existing issue |
| `close_issue` | Close an issue as `done` or `cancelled` (with resolution, files, refs) |
| `comment_issue` | Append a comment; optionally transition status |
| `board` | Return the grouped board state (epics / scheduled / in_progress / todo) |
| `search` | Full-text search across titles and descriptions (FTS5 + LIKE fallback) |
| `context` | Active work + due-soon + upcoming + recent activity — ideal at session start |

All tools return plain JSON-serialisable dicts / lists.  Validation errors are
returned as `{"error": "<message>"}` rather than raising transport-level errors.

## Registration

### Claude Code (`~/.claude/mcp.json` or project `.mcp.json`)

```json
{
  "mcpServers": {
    "prism": {
      "command": "runloq-mcp",
      "args": [],
      "env": {
        "TRACKER_DB": "/path/to/your/prism/state/runloq.db"
      }
    }
  }
}
```

If `runloq-mcp` is not on `PATH` (before the package is installed with its
entry point), use the absolute path to the server script:

```json
{
  "mcpServers": {
    "prism": {
      "command": "/path/to/your/venv/bin/python",
      "args": ["/path/to/prism/prism/mcp/server.py"],
      "env": {
        "PYTHONPATH": "/path/to/prism",
        "TRACKER_DB": "/path/to/your/prism/state/runloq.db"
      }
    }
  }
}
```

### Cursor (`~/.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "prism": {
      "command": "runloq-mcp",
      "args": [],
      "env": {
        "TRACKER_DB": "/path/to/your/prism/state/runloq.db"
      }
    }
  }
}
```

### Generic stdio MCP config (any client)

```json
{
  "name": "prism",
  "transport": "stdio",
  "command": "runloq-mcp",
  "env": {
    "TRACKER_DB": "/path/to/your/prism/state/runloq.db"
  }
}
```

## Environment variables

| Variable | Description |
|----------|-------------|
| `TRACKER_DB` | Absolute path to `runloq.db`. Overrides config-file path. |
| `TRACKER_STATE_DIR` | Directory containing `runloq.db` (ignored when `TRACKER_DB` is set). |
| `RUNLOQ_CONFIG` | Explicit path to a `runloq.config.toml` config file. |
| `TRACKER_SKIP_AGENT_VALIDATION` | Set to `1` to skip agent-slug validation (useful in tests). |

## Packaging agent note

Add these to the root `pyproject.toml`:

**Dependency:** `mcp>=1.0` (tested with 1.27.x)

**Console entry point:**
```toml
[project.scripts]
runloq-mcp = "prism.mcp.server:main"
```

**Packages:** ensure `prism/mcp` is included in the package discovery:
```toml
[tool.setuptools.packages.find]
where = ["."]
include = ["prism*"]
```

## Development / testing

```bash
# Run tests (no live transport needed — tool handlers are tested as functions)
PYTHONPATH=. TRACKER_SKIP_AGENT_VALIDATION=1 python -m pytest tests/test_mcp.py -v

# Verify import
PYTHONPATH=. python -c "from prism.mcp.server import main; print('import ok')"

# Smoke-test: construct the FastMCP app (no stdio needed)
PYTHONPATH=. python -c "from prism.mcp.server import mcp; print('app:', mcp.name)"
```
