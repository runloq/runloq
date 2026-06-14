"""Pydantic request/response schemas for the dashboard API.

Mirror the tracker's invariants — see `prism/core.py` for the
authoritative business-rule logic. These schemas are the validation
layer at the HTTP boundary.

Project, Assignee, and Model are config-driven (loaded from runloq.config.toml
via ``config.load_config()``). This allows fresh OSS installs with default
projects={"TASK": "Tasks"} and assignees=["claude", "me"] to work without
any schema changes. Priority, Status, Recurrence, and IssueType remain fixed
Literal enums — they are not user-configurable.
"""
from __future__ import annotations
from typing import Literal, Optional, List
from pydantic import BaseModel, ConfigDict, Field, field_validator

try:
    from config import load_config
except ModuleNotFoundError:  # package context (dashboard via PYTHONPATH)
    from prism.config import load_config


# Fixed enums — not config-driven.
Priority = Literal["P0", "P1", "P2", "P3"]
Status = Literal["todo", "in_progress", "scheduled", "done", "cancelled"]
Recurrence = Literal["daily", "weekly", "biweekly", "monthly"]
IssueType = Literal["issue", "epic"]


def _default_project() -> str:
    """Return the first configured project prefix, falling back to 'TASK'."""
    cfg = load_config()
    keys = list(cfg.projects.keys())
    return keys[0] if keys else "TASK"


def _default_assignee() -> str:
    """Return the first configured assignee, falling back to 'claude'."""
    cfg = load_config()
    return cfg.assignees[0] if cfg.assignees else "claude"


class CreateIssueRequest(BaseModel):
    """Body for POST /api/issues."""
    title: str = Field(min_length=1, max_length=500)
    project: str = Field(default_factory=_default_project)
    type: IssueType = "issue"
    priority: Priority = "P1"
    assignee: str = Field(default_factory=_default_assignee)
    agent: Optional[str] = None
    model: Optional[str] = None
    description: Optional[str] = None
    blocked_by: List[str] = Field(default_factory=list)
    linked_to: List[str] = Field(default_factory=list)
    parent_id: Optional[str] = None
    scheduled_at: Optional[str] = None
    recurrence: Optional[Recurrence] = None
    status: Optional[Status] = None  # parity with cmd_create's --status flag

    @field_validator("project")
    @classmethod
    def validate_project(cls, v: str) -> str:
        cfg = load_config()
        upper = v.upper()
        if upper not in cfg.project_prefixes:
            allowed = sorted(cfg.project_prefixes)
            raise ValueError(
                f"Invalid project {v!r}. Allowed values: {allowed}"
            )
        return upper

    @field_validator("assignee")
    @classmethod
    def validate_assignee(cls, v: str) -> str:
        cfg = load_config()
        if v not in cfg.assignee_set:
            allowed = sorted(cfg.assignee_set)
            raise ValueError(
                f"Invalid assignee {v!r}. Allowed values: {allowed}"
            )
        return v

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        cfg = load_config()
        if v not in cfg.model_set:
            allowed = sorted(cfg.model_set)
            raise ValueError(
                f"Invalid model {v!r}. Allowed values: {allowed}"
            )
        return v


class UpdateIssueRequest(BaseModel):
    """Body for PATCH /api/issues/{id}. All fields optional; only provided ones change."""
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[Status] = None
    type: Optional[IssueType] = None
    priority: Optional[Priority] = None
    assignee: Optional[str] = None
    agent: Optional[str] = None
    model: Optional[str] = None
    blocked_by: Optional[List[str]] = None
    linked_to: Optional[List[str]] = None
    parent_id: Optional[str] = None
    scheduled_at: Optional[str] = None
    recurrence: Optional[Recurrence] = None
    resolution: Optional[str] = None
    closed_at: Optional[str] = None
    clear_agent: bool = False
    clear_model: bool = False
    clear_scheduled_at: bool = False
    clear_recurrence: bool = False

    @field_validator("assignee")
    @classmethod
    def validate_assignee(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        cfg = load_config()
        if v not in cfg.assignee_set:
            allowed = sorted(cfg.assignee_set)
            raise ValueError(
                f"Invalid assignee {v!r}. Allowed values: {allowed}"
            )
        return v

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        cfg = load_config()
        if v not in cfg.model_set:
            allowed = sorted(cfg.model_set)
            raise ValueError(
                f"Invalid model {v!r}. Allowed values: {allowed}"
            )
        return v


class CloseIssueRequest(BaseModel):
    """Body for POST /api/issues/{id}/close."""
    status: Literal["done", "cancelled"] = "done"
    resolution: Optional[str] = None
    files: List[str] = Field(default_factory=list)
    refs: List[str] = Field(default_factory=list)


class CommentRequest(BaseModel):
    """Body for POST /api/issues/{id}/comment."""
    message: str = Field(min_length=1)
    status: Optional[Status] = None
    files: List[str] = Field(default_factory=list)
    refs: List[str] = Field(default_factory=list)


class IssueResponse(BaseModel):
    """Response shape for any single issue."""
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    description: Optional[str] = None
    status: Status
    issue_type: IssueType
    priority: Priority
    assignee: str
    agent: Optional[str] = None
    model: Optional[str] = None
    blocked_by: List[str] = Field(default_factory=list)
    linked_to: List[str] = Field(default_factory=list)
    parent_id: Optional[str] = None
    scheduled_at: Optional[str] = None
    recurrence: Optional[Recurrence] = None
    resolution: Optional[str] = None
    created_at: str
    updated_at: str
    closed_at: Optional[str] = None


class CloseIssueResponse(IssueResponse):
    """Closing returns the row plus optional auto-spawn metadata."""
    next_issue_id: Optional[str] = Field(default=None, alias="_next_issue_id")
    next_scheduled_at: Optional[str] = Field(default=None, alias="_next_scheduled_at")

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class UpdateIssueResponse(BaseModel):
    """PATCH returns both the updated row and the human-readable change list
    so the dashboard can show 'priority: P1 → P0' chips."""
    issue: IssueResponse
    changes: List[str]


class EventResponse(BaseModel):
    """Single event row from the events table."""
    id: int
    issue_id: Optional[str] = None
    type: str
    message: str
    metadata: Optional[str] = None
    created_at: str

    model_config = ConfigDict(extra="ignore")


class AgentInfo(BaseModel):
    """One row in the meta endpoint's agent list — name + parsed frontmatter."""
    name: str
    description: Optional[str] = None
    model: Optional[str] = None


class MetaResponse(BaseModel):
    """Static enum metadata + dynamic agent list — feeds the form pickers."""
    projects: List[str]
    priorities: List[str]
    statuses: List[str]
    assignees: List[str]
    models: List[str]
    recurrences: List[str]
    agents: List[AgentInfo]


class ErrorResponse(BaseModel):
    detail: str
