"""CRUD on issues — wraps prism.core."""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from prism import core
from .. import schemas
from ..deps import get_db
from ..sse import broker

router = APIRouter(prefix="/issues", tags=["issues"])


def _strip_underscore_keys(d: dict) -> dict:
    """Drop keys starting with underscore (close_issue's _next_* extras)."""
    return {k: v for k, v in d.items() if not k.startswith("_")}


@router.get("", response_model=List[schemas.IssueResponse])
def list_issues(
    status: Optional[List[str]] = Query(None),
    project: Optional[List[str]] = Query(None),
    priority: Optional[List[str]] = Query(None),
    assignee: Optional[List[str]] = Query(None),
    agent: Optional[List[str]] = Query(None),
    model: Optional[List[str]] = Query(None),
    type: Optional[List[str]] = Query(None),
    include_epics: bool = Query(False),
    blocked_only: bool = Query(False),
    scheduled_window: Optional[str] = Query(None, pattern="^(due|this_week|all)$"),
    parent: Optional[str] = Query(None),
    db=Depends(get_db),
):
    return core.list_issues(
        db,
        status=status,
        project=project,
        priority=priority,
        assignee=assignee,
        agent=agent,
        model=model,
        type=type,
        include_epics=include_epics,
        blocked_only=blocked_only,
        scheduled_window=scheduled_window,
        parent_id=parent,
    )


@router.get("/{issue_id}", response_model=schemas.IssueResponse)
def get_issue(issue_id: str, db=Depends(get_db)):
    try:
        return core.get_issue(db, issue_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")


@router.post("", response_model=schemas.IssueResponse, status_code=201)
async def create_issue(req: schemas.CreateIssueRequest, db=Depends(get_db)):
    try:
        row = core.create_issue(db, **req.model_dump(exclude_none=False))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    await broker.publish({"type": "issue-changed", "id": row["id"], "action": "create"})
    return row


@router.patch("/{issue_id}", response_model=schemas.UpdateIssueResponse)
async def update_issue(
    issue_id: str, req: schemas.UpdateIssueRequest, db=Depends(get_db)
):
    try:
        row, changes = core.update_issue(
            db, issue_id, **req.model_dump(exclude_unset=True)
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    await broker.publish({"type": "issue-changed", "id": issue_id, "action": "update"})
    return {"issue": row, "changes": changes}


@router.post("/{issue_id}/close", response_model=schemas.CloseIssueResponse)
async def close_issue(
    issue_id: str, req: schemas.CloseIssueRequest, db=Depends(get_db)
):
    try:
        result = core.close_issue(
            db, issue_id,
            status=req.status,
            resolution=req.resolution,
            files=req.files or None,
            refs=req.refs or None,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    await broker.publish({"type": "issue-changed", "id": issue_id, "action": "close"})
    return result


@router.post("/{issue_id}/comment", response_model=schemas.IssueResponse)
async def comment(issue_id: str, req: schemas.CommentRequest, db=Depends(get_db)):
    try:
        row = core.add_comment(
            db, issue_id, req.message,
            status=req.status,
            files=req.files or None,
            refs=req.refs or None,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")
    await broker.publish({"type": "issue-changed", "id": issue_id, "action": "comment"})
    return _strip_underscore_keys(row)
