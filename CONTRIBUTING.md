# Contributing to runloq

Thanks for your interest in contributing to runloq! This guide walks you through local development, testing, and submitting changes.

## Development Setup

### Prerequisites

- Python 3.11+
- Node 18+ (only if building the dashboard SPA locally)
- `pip`, `pipx`, or `uv` for package management

### Install for Development

```bash
git clone https://github.com/runloq/runloq.git
cd prism

# Install runloq + dev dependencies (includes pytest, MCP SDK, dashboard API test deps)
pip install -e ".[dev,mcp]"
```

If you're only working on the CLI or core tracker (not the dashboard), you can skip the MCP extra:

```bash
pip install -e ".[dev]"
```

### Build the Dashboard SPA (if modifying UI)

```bash
cd dashboard/web
pnpm install
pnpm build
cd ../..
```

For interactive UI development, run the API and dev server side-by-side:

```bash
# Shell 1 — API (default http://127.0.0.1:3002)
runloq serve

# Shell 2 — Vite dev server (proxies /api to :3002)
cd dashboard/web
pnpm dev
```

## Testing

runloq has two test suites:

1. **Unit tests** (`tests/`) — pure Python, stdlib-only (no external deps). Run with:
   ```bash
   python -m pytest tests/ -q
   ```

2. **Dashboard API integration tests** (`dashboard/api/tests/`) — FastAPI routes with real async contexts. Require `fastapi`, `httpx`, `pytest-asyncio`. Run with:
   ```bash
   python -m pytest dashboard/api/tests/ -q
   ```

**Run both test suites together (recommended for pre-commit verification):**

```bash
python -m pytest tests/ dashboard/api/tests/ -q
```

> **Note:** Plain `pytest` (without paths) only runs `tests/` by design. This is configured in `pyproject.toml` via `testpaths = ["tests"]` — it keeps the lightweight unit suite fast for quick iteration, and you explicitly opt into the heavier dashboard tests when needed. Both run together in CI.

## Code Style

The codebase follows Python conventions with no enforced formatter or linter yet. Keep these in mind:

- Use type hints where helpful (especially function signatures).
- Docstrings for public functions and classes.
- One assertion per test (Arrange-Act-Assert pattern).

## Before Submitting a PR

- [ ] Tests pass: `python -m pytest tests/ dashboard/api/tests/ -q`
- [ ] No uncommitted changes to `runloq.config.toml` (this is local-only config, not tracked)
- [ ] New features include tests (or extend existing test suites)
- [ ] Commits are logical, with descriptive messages
- [ ] No secrets in code (tokens, API keys, personal paths)

## Reporting Issues

Please use the GitHub issue tracker. Include:

- A clear title and description
- Steps to reproduce (if it's a bug)
- Actual vs. expected behavior
- Python version (`python --version`)
- How you installed runloq (`pip`, `pipx`, from source)

## Questions?

Open an issue or start a discussion on GitHub.

Thank you for contributing!
