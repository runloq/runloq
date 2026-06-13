"""runloq configuration loader.

Resolution order (first found wins), cached per process:
  1. $RUNLOQ_CONFIG          explicit path to a .toml file
  2. ./runloq.config.toml    current working directory
  3. <package_dir>/runloq.config.toml   same dir as the installed package
  4. <package_dir>/.runloq/config.toml
  5. built-in defaults

Legacy prism-named paths ($PRISM_CONFIG, prism.config.toml, .prism/config.toml)
are still accepted as fallbacks for existing instances.

Env precedence: RUNLOQ_DB / RUNLOQ_STATE_DIR (or the legacy TRACKER_DB /
TRACKER_STATE_DIR) OVERRIDE the config file (env > config file > built-in default).

Format: TOML.  Requires ``tomllib`` (Python 3.11+) or ``tomli`` (backport).
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# TOML parser — stdlib (3.11+) or backport
# ---------------------------------------------------------------------------
try:
    import tomllib  # type: ignore
    _toml_loads = tomllib.loads
except ModuleNotFoundError:
    try:
        import tomli as tomllib  # type: ignore
        _toml_loads = tomllib.loads
    except ModuleNotFoundError:
        tomllib = None  # type: ignore
        _toml_loads = None  # type: ignore


# ---------------------------------------------------------------------------
# Package directory (same folder as this file / prism.py)
# ---------------------------------------------------------------------------
_PKG_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Built-in defaults
# ---------------------------------------------------------------------------
_DEFAULT_PROJECTS: Dict[str, str] = {"TASK": "Tasks"}
_DEFAULT_ASSIGNEES: List[str] = ["claude", "me"]
_DEFAULT_MODELS: List[str] = ["opus", "sonnet", "haiku"]
_DEFAULT_AGENTS_DIR: Optional[str] = None  # No default; must be configured via [agents] dir
_DEFAULT_STATE_DIR: str = str(_PKG_DIR / "state")
# db default is derived from state_dir at load time


# ---------------------------------------------------------------------------
# Config dataclass (plain dict to stay dependency-free)
# ---------------------------------------------------------------------------
class PrismConfig:
    """Resolved Prism configuration.  All values are final after __init__."""

    def __init__(
        self,
        projects: Dict[str, str],
        assignees: List[str],
        models: List[str],
        agents_dir: Optional[str],
        agents_list: Optional[List[str]],
        state_dir: str,
        db: str,
        dashboard_host: str,
        dashboard_port: int,
        api_token: Optional[str] = None,
    ) -> None:
        self.projects = projects            # prefix → display name, e.g. {"TASK": "Tasks"}
        self.assignees = assignees          # bare names (no '@')
        self.models = models
        self.agents_dir = agents_dir        # None = no agents dir configured
        self.agents_list = agents_list      # explicit list (optional)
        self.state_dir = state_dir
        self.db = db
        self.dashboard_host = dashboard_host
        self.dashboard_port = dashboard_port
        # Optional bearer-token for the dashboard API (opt-in auth).
        # Set via RUNLOQ_API_TOKEN env var or [dashboard] token = "..." in config.
        self.api_token: Optional[str] = api_token

    # Convenience sets for O(1) validation
    @property
    def project_prefixes(self) -> frozenset:
        return frozenset(self.projects.keys())

    @property
    def assignee_set(self) -> frozenset:
        return frozenset(self.assignees)

    @property
    def model_set(self) -> frozenset:
        return frozenset(self.models)

    def __repr__(self) -> str:
        return (
            f"PrismConfig(projects={self.projects}, assignees={self.assignees}, "
            f"models={self.models}, state_dir={self.state_dir!r}, db={self.db!r}, "
            f"api_token={'<set>' if self.api_token else '<unset>'})"
        )


# ---------------------------------------------------------------------------
# Config file discovery
# ---------------------------------------------------------------------------
def _env(*names: str) -> Optional[str]:
    """Return the first set environment variable among `names`, else None.

    Used so the runloq-prefixed names are primary while the legacy PRISM_*/
    TRACKER_* names keep working (backward compatibility for existing instances).
    """
    for n in names:
        v = os.environ.get(n)
        if v is not None:
            return v
    return None


def _default_db_path(state_dir: str) -> str:
    """Default DB path inside `state_dir`.

    Prefers `runloq.db`. For backward compatibility, if `runloq.db` does not yet
    exist but a legacy `prism.db` does, keep using `prism.db` so existing
    instances don't silently start from an empty database.
    """
    runloq_db = Path(state_dir) / "runloq.db"
    legacy_db = Path(state_dir) / "prism.db"
    if not runloq_db.exists() and legacy_db.exists():
        return str(legacy_db)
    return str(runloq_db)


def _find_config_file() -> Optional[Path]:
    """Return the first config file that exists, or None for built-in defaults.

    Prefers the runloq-named config; falls back to the legacy prism-named one so
    existing instances keep resolving their config unchanged.
    """
    candidates: List[Path] = []

    env_path = _env("RUNLOQ_CONFIG", "PRISM_CONFIG")
    if env_path:
        # Explicit env var — always use it (even if missing, so error is loud)
        return Path(env_path)

    # runloq-named (preferred), then legacy prism-named (back-compat).
    # User-level config lives OUTSIDE any git repo so it survives `git clean`.
    candidates.append(Path.cwd() / "runloq.config.toml")
    candidates.append(Path.cwd() / "prism.config.toml")
    candidates.append(Path.home() / ".runloq" / "config.toml")
    candidates.append(Path.home() / ".prism" / "config.toml")
    candidates.append(_PKG_DIR / "runloq.config.toml")
    candidates.append(_PKG_DIR / "prism.config.toml")
    candidates.append(_PKG_DIR / ".runloq" / "config.toml")
    candidates.append(_PKG_DIR / ".prism" / "config.toml")

    for p in candidates:
        if p.exists():
            return p
    return None


# ---------------------------------------------------------------------------
# Parse a TOML dict into a PrismConfig
# ---------------------------------------------------------------------------
def _build_config(data: Dict[str, Any], source_dir: Optional[Path] = None) -> PrismConfig:
    """Build a PrismConfig from a parsed TOML dict.

    `source_dir` is the directory containing the config file (used to resolve
    relative paths).  None when building from built-in defaults.
    """
    # --- [projects] ---
    raw_projects = data.get("projects", {})
    if raw_projects:
        projects = {k.upper(): v for k, v in raw_projects.items()}
    else:
        projects = dict(_DEFAULT_PROJECTS)

    # --- [assignees] ---
    raw_assignees = data.get("assignees", {})
    if isinstance(raw_assignees, dict):
        assignees_list = raw_assignees.get("list", _DEFAULT_ASSIGNEES)
    elif isinstance(raw_assignees, list):
        # Flat list under key (legacy / simpler format)
        assignees_list = raw_assignees
    else:
        assignees_list = list(_DEFAULT_ASSIGNEES)

    # --- [models] ---
    raw_models = data.get("models", {})
    if isinstance(raw_models, dict):
        models_list = raw_models.get("list", _DEFAULT_MODELS)
    elif isinstance(raw_models, list):
        models_list = raw_models
    else:
        models_list = list(_DEFAULT_MODELS)

    # --- [agents] ---
    raw_agents = data.get("agents", {})
    agents_dir_raw = raw_agents.get("dir") if isinstance(raw_agents, dict) else None
    agents_list = raw_agents.get("list") if isinstance(raw_agents, dict) else None

    if agents_dir_raw:
        p = Path(agents_dir_raw)
        if not p.is_absolute() and source_dir:
            p = (source_dir / p).resolve()
        agents_dir: Optional[str] = str(p)
    else:
        agents_dir = None  # Not configured; validated at use-time in core.py

    # --- [paths] ---
    raw_paths = data.get("paths", {})

    state_dir_raw = raw_paths.get("state_dir") if isinstance(raw_paths, dict) else None
    if state_dir_raw:
        p_state = Path(state_dir_raw)
        if not p_state.is_absolute() and source_dir:
            p_state = (source_dir / p_state).resolve()
        state_dir_cfg: str = str(p_state)
    else:
        state_dir_cfg = _DEFAULT_STATE_DIR

    db_raw = raw_paths.get("db") if isinstance(raw_paths, dict) else None
    if db_raw:
        p_db = Path(db_raw)
        if not p_db.is_absolute() and source_dir:
            p_db = (source_dir / p_db).resolve()
        db_cfg: str = str(p_db)
    else:
        db_cfg = _default_db_path(state_dir_cfg)

    # --- env overrides (highest precedence after explicit env var paths) ---
    state_dir_final = _env("RUNLOQ_STATE_DIR", "TRACKER_STATE_DIR") or state_dir_cfg
    # If the state dir was overridden, recompute db default UNLESS db is also overridden
    db_default_from_state = _default_db_path(state_dir_final)
    db_final = _env("RUNLOQ_DB", "TRACKER_DB") or (
        db_default_from_state if state_dir_final != state_dir_cfg else db_cfg
    )

    # --- [dashboard] ---
    raw_dashboard = data.get("dashboard", {})
    dashboard_host = raw_dashboard.get("host", "127.0.0.1") if isinstance(raw_dashboard, dict) else "127.0.0.1"
    dashboard_port = int(raw_dashboard.get("port", 3002)) if isinstance(raw_dashboard, dict) else 3002
    # Optional bearer-token: RUNLOQ_API_TOKEN env var takes precedence over
    # [dashboard] token = "..." in the config file.  When unset/empty → auth off.
    _token_from_cfg = raw_dashboard.get("token") if isinstance(raw_dashboard, dict) else None
    _token_raw = _env("RUNLOQ_API_TOKEN", "PRISM_API_TOKEN") or _token_from_cfg or None
    api_token_cfg: Optional[str] = _token_raw.strip() if _token_raw else None

    return PrismConfig(
        projects=projects,
        assignees=list(assignees_list),
        models=list(models_list),
        agents_dir=agents_dir,
        agents_list=agents_list,
        state_dir=state_dir_final,
        db=db_final,
        dashboard_host=dashboard_host,
        dashboard_port=dashboard_port,
        api_token=api_token_cfg,
    )


# ---------------------------------------------------------------------------
# Loud-fail guard: warn (or hard-error) when falling back to OSS defaults  (SYS-340)
# ---------------------------------------------------------------------------
def _warn_if_oss_defaults(cfg: PrismConfig, source: str) -> None:
    """Emit a loud warning to stderr when the resolved config is OSS-default only.

    Specifically: if the only project is TASK (the built-in OSS default), there
    is almost certainly a misconfiguration — pkg-dir config was wiped by
    ``git clean`` or was never created.  Staying silent causes misfiled tickets
    (SYS-340).

    Set RUNLOQ_STRICT=1 to turn the warning into a hard RuntimeError so CI and
    subagents fail loudly instead of silently misfiling work.
    """
    import sys

    oss_default_projects = frozenset({"TASK"})
    if frozenset(cfg.projects.keys()) != oss_default_projects:
        return  # Non-default projects configured — all good.

    msg = (
        "WARNING [runloq/config]: falling back to OSS defaults (projects={TASK}).\n"
        f"  Config source: {source}\n"
        "  Tickets will be filed under TASK-* instead of your project prefixes.\n"
        "  Fix: set RUNLOQ_CONFIG=/path/to/your/runloq.config.toml, or create\n"
        "  ~/.runloq/config.toml (survives git clean), or restore\n"
        "  <cwd>/runloq.config.toml.\n"
        "  Set RUNLOQ_STRICT=1 to make this a hard error."
    )
    print(msg, file=sys.stderr)

    if _env("RUNLOQ_STRICT", "PRISM_STRICT") == "1":
        raise RuntimeError(
            f"RUNLOQ_STRICT=1: refusing to run with OSS-default TASK-only config "
            f"(source: {source}). Set RUNLOQ_CONFIG or create a project config file."
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def load_config() -> PrismConfig:
    """Load and cache the Prism configuration.

    Safe to call multiple times — result is cached per process.
    Call ``load_config.cache_clear()`` in tests to reset between cases.
    """
    config_file = _find_config_file()

    if config_file is None:
        # No config file found anywhere — fall back to built-in defaults, but
        # warn loudly so TASK-misfiling is never silent (SYS-340).
        cfg = _build_config({})
        _warn_if_oss_defaults(cfg, source="<no config file found>")
        return cfg

    if not config_file.exists():
        if _env("RUNLOQ_CONFIG", "PRISM_CONFIG"):
            raise FileNotFoundError(
                f"RUNLOQ_CONFIG points to a missing file: {config_file}"
            )
        cfg = _build_config({})
        _warn_if_oss_defaults(cfg, source=f"<config file missing: {config_file}>")
        return cfg

    if _toml_loads is None:
        raise RuntimeError(
            "TOML parser not available. Install 'tomli' (pip install tomli) "
            "or upgrade to Python 3.11+."
        )

    with open(config_file, "rb") as fh:
        # Use tomllib.load() on the binary handle per the spec — handles BOM
        # and encoding correctly without an intermediate decode step.
        data = tomllib.load(fh)

    return _build_config(data, source_dir=config_file.parent)


# ---------------------------------------------------------------------------
# Config file template (used by `prism init`)
# ---------------------------------------------------------------------------
CONFIG_TEMPLATE = """\
# runloq.config.toml — runloq issue tracker configuration
# Generated by `runloq init`. Edit freely.

[projects]
# Map of project prefix → display name.
# The prefix is used in ticket IDs (e.g. TASK-001).
# Add as many projects as you need.
TASK = "Tasks"

[assignees]
# List of valid assignees (bare names, no '@').
list = ["claude", "me"]

[models]
# LLM model tiers for agent-driven tickets.
list = ["opus", "sonnet", "haiku"]

[agents]
# Path to agent definition files (Markdown, .md extension).
# Relative paths are resolved from this file's directory.
# Omit or leave empty if you're not using agent routing.
# dir = ".claude/agents"

[paths]
# Where Prism stores its SQLite database.
# Relative paths are resolved from this file's directory.
# state_dir = "state"          # directory containing runloq.db
# db = "state/runloq.db"        # explicit DB path (overrides state_dir)

[dashboard]
host = "127.0.0.1"
port = 3002
# token = ""   # Optional bearer-token.  When set, every API route except
               # /healthz requires "Authorization: Bearer <token>".
               # Prefer the RUNLOQ_API_TOKEN env var to avoid storing secrets
               # in the config file.
"""
