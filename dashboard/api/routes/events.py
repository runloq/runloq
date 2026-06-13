"""Activity timeline for a single issue."""
from typing import List
from fastapi import APIRouter, Depends

from prism import core
from .. import schemas
from ..deps import get_db

router = APIRouter(prefix="/issues", tags=["events"])


@router.get("/{issue_id}/events", response_model=List[schemas.EventResponse])
def list_events(issue_id: str, db=Depends(get_db)):
    return core.get_events(db, issue_id)
