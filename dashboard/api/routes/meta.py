"""Static enums + dynamic agent list — feeds form pickers in the SPA.

Projects / assignees / models / the agents directory are sourced from the
runloq config (``runloq.config.toml``) so the dashboard matches the CLI exactly.
Priorities / statuses / recurrences are fixed enums, not user-configurable.
"""
from pathlib import Path
import re

from fastapi import APIRouter

from .. import schemas

try:
    from config import load_config
except ModuleNotFoundError:  # package context (dashboard via PYTHONPATH)
    from prism.config import load_config

router = APIRouter(tags=["meta"])

PRIORITIES = ["P0", "P1", "P2", "P3"]
STATUSES = ["todo", "in_progress", "scheduled", "done", "cancelled"]
RECURRENCES = ["daily", "weekly", "biweekly", "monthly"]

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_KEY_RE = re.compile(r"^(\w+):\s*(.*?)\s*$", re.MULTILINE)


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Tiny YAML-frontmatter parser — handles the flat key:value subset our
    agent files use (no nested keys, no multi-line strings). Anything fancier
    would mean importing PyYAML; not worth the dep for two scalars."""
    m = _FM_RE.match(text)
    if not m:
        return {}
    out: dict[str, str] = {}
    for k, v in _KEY_RE.findall(m.group(1)):
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        out[k] = v
    return out


def _load_agents(agents_dir: str | None) -> list[schemas.AgentInfo]:
    if not agents_dir:
        return []
    d = Path(agents_dir)
    if not d.exists():
        return []
    agents: list[schemas.AgentInfo] = []
    for p in sorted(d.glob("*.md")):
        if p.stem == "index":
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = _parse_frontmatter(text)
        agents.append(
            schemas.AgentInfo(
                name=fm.get("name", p.stem),
                description=fm.get("description") or None,
                model=fm.get("model") or None,
            )
        )
    return agents


@router.get("/meta", response_model=schemas.MetaResponse)
def meta():
    cfg = load_config()
    return schemas.MetaResponse(
        projects=list(cfg.projects.keys()),
        priorities=PRIORITIES,
        statuses=STATUSES,
        assignees=list(cfg.assignees),
        models=list(cfg.models),
        recurrences=RECURRENCES,
        agents=_load_agents(cfg.agents_dir),
    )
