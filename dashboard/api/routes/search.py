"""Full-text search across issue titles + descriptions (FTS5 with LIKE fallback)."""
from typing import List
from fastapi import APIRouter, Depends, Query

from prism import core
from .. import schemas
from ..deps import get_db

router = APIRouter(tags=["search"])


@router.get("/search", response_model=List[schemas.IssueResponse])
def search(q: str = Query(..., min_length=1), db=Depends(get_db)):
    return core.search_issues(db, q)
