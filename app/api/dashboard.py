from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import current_user, get_container

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/submissions")
def submissions(request: Request, widget_id: Optional[str] = None, limit: int = Query(50, ge=1, le=200),
                offset: int = Query(0, ge=0), user: dict = Depends(current_user)):
    return get_container(request).dashboard.submissions(user["id"], widget_id, limit, offset)


@router.get("/stats")
def stats(request: Request, widget_id: Optional[str] = None, days: int = Query(30, ge=1, le=365),
          user: dict = Depends(current_user)):
    return get_container(request).dashboard.stats(user["id"], widget_id, days)


@router.get("/jobs/failed")
def failed_jobs(request: Request, user: dict = Depends(current_user)):
    """Failure alert surface: background jobs that exhausted their retries."""
    return {"items": get_container(request).dashboard.failed_jobs(user["id"])}
