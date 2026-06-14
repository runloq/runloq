"""pytest conftest — ensures `prism` is importable as a package.

When running tests from source (repo root may be named anything: "prism",
"packaging", a git worktree slug), Python may see `prism` as `prism.py`
rather than the package.  This conftest runs before any test collection and
registers the repo root as the `prism` package in sys.modules so that all
`from prism import ...` / `from prism.dashboard.api import ...` paths resolve.

When the package is installed via pip, `prism` is already a proper package in
site-packages and this conftest is effectively a no-op.

Name-shadowing fix
------------------
The repo root contains a ``mcp/`` directory that is the *prism* MCP server
package.  Python's default ``sys.path`` always starts with ``''`` (cwd), so
when tests are run from inside the repo root, ``import mcp`` resolves to the
*local* ``mcp/`` package instead of the installed ``mcp`` SDK — even before
any explicit ``sys.path`` manipulation.

``_pre_cache_real_mcp_sdk()`` below fixes this by loading the real SDK from
site-packages (temporarily removing ``''`` from sys.path so the local dir
can't shadow it) and pinning it in ``sys.modules`` *before* anything else
runs.  Once cached, subsequent ``import mcp`` calls in test modules and in
``mcp/server.py`` itself use the cached real SDK regardless of sys.path order.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent  # tests/ -> repo root


def _pre_cache_real_mcp_sdk() -> None:
    """Pin the installed mcp SDK in sys.modules before local mcp/ can shadow it.

    Python prepends ``''`` (cwd) to sys.path, so when pytest runs from inside
    the prism repo the local ``mcp/`` directory intercepts ``import mcp``
    before the venv/site-packages version.  We solve this once, here, before
    any test module is collected:

    1. Temporarily remove any cwd entries (``''``, ``'.'``, and the repo root
       itself) from sys.path.
    2. Load the real ``mcp`` package from whatever remains (site-packages).
    3. Pre-populate ``sys.modules`` with the loaded real package and its key
       sub-modules so subsequent imports everywhere get the cached version.
    4. Restore sys.path.

    If ``mcp`` is already correctly cached (e.g. installed use, or the SDK was
    imported before this conftest ran) the function is a no-op.
    """
    # If mcp is already cached and is the real SDK (has server.fastmcp), skip.
    cached = sys.modules.get("mcp")
    if cached is not None:
        try:
            from mcp.server.fastmcp import FastMCP  # noqa: F401
            return  # real SDK already in sys.modules — nothing to do
        except (ImportError, AttributeError):
            # The cached module is the local stub — evict it and reload below.
            for key in list(sys.modules):
                if key == "mcp" or key.startswith("mcp."):
                    del sys.modules[key]

    # Temporarily strip cwd-like entries so find_spec sees site-packages first.
    cwd_entries = {"", ".", str(_REPO_ROOT), str(_REPO_ROOT) + "/"}
    saved_path = sys.path[:]
    sys.path[:] = [p for p in sys.path if p not in cwd_entries]

    try:
        spec = importlib.util.find_spec("mcp")
        if spec is None:
            # mcp SDK is not installed — leave sys.modules alone and let
            # individual tests skip/fail with a clear ImportError.
            return

        # Load the real package.
        real_mcp = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(real_mcp)  # type: ignore[union-attr]
        sys.modules["mcp"] = real_mcp

        # Pre-cache the sub-modules that mcp/server.py imports at module level
        # so they too resolve from the real SDK rather than the local package.
        for sub in ("mcp.server", "mcp.server.fastmcp"):
            if sub not in sys.modules:
                try:
                    importlib.import_module(sub)
                except ImportError:
                    pass  # best-effort; individual tests will surface the error
    finally:
        sys.path[:] = saved_path


def _register_prism_package() -> None:
    """Ensure `prism` in sys.modules is the PACKAGE (not the prism.py module)."""
    existing = sys.modules.get("prism")

    # Already a proper package (has __path__)? Nothing to do.
    if existing is not None and hasattr(existing, "__path__"):
        return

    # Build a package module pointing at the repo root.
    pkg = types.ModuleType("prism")
    pkg.__path__ = [str(_REPO_ROOT)]  # type: ignore[assignment]
    pkg.__package__ = "prism"
    pkg.__spec__ = importlib.util.spec_from_file_location(  # type: ignore[assignment]
        "prism",
        str(_REPO_ROOT / "__init__.py"),
        submodule_search_locations=[str(_REPO_ROOT)],
    )
    sys.modules["prism"] = pkg

    # Make sure the repo root itself is on sys.path so bare `import core`,
    # `import config` (used inside prism.py functions) still resolve.
    # APPEND (not insert-0) so the repo-local `mcp/` package never shadows the
    # installed `mcp` SDK that prism/mcp/server.py imports.
    if str(_REPO_ROOT) not in sys.path:
        sys.path.append(str(_REPO_ROOT))


# Order matters: pre-cache the real SDK FIRST, then register the prism package.
# This ensures that when _register_prism_package() appends the repo root to
# sys.path, the mcp SDK is already pinned and cannot be displaced.
_pre_cache_real_mcp_sdk()
_register_prism_package()
