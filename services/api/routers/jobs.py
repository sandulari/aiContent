"""Job monitoring — scoped to the current user's own work.

The old /api/admin/jobs endpoint had no auth guard and leaked every job
across every user. This now requires authentication and only returns
jobs that reference the current user's resources (user_pages,
user_exports, viral_reels in the user's recommendation/export scope).
"""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from middleware.auth import get_current_user
from models.job import Job
from models.user import User
from models.user_export import UserExport
from models.user_page import UserPage

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
async def list_jobs(
    job_type: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return jobs whose reference_id belongs to the current user."""
    # Push ownership scoping into SQL: two correlated IN subqueries instead
    # of two round-trips that materialize UUID lists in Python. The
    # user_exports(user_id) and user_pages(user_id, page_type) indexes
    # cover the subqueries.
    own_exports = select(UserExport.id).where(UserExport.user_id == current_user.id)
    own_pages = select(UserPage.id).where(UserPage.user_id == current_user.id)
    ownership = or_(
        Job.reference_id.in_(own_exports),
        Job.reference_id.in_(own_pages),
    )

    stmt = select(Job).where(ownership).order_by(Job.created_at.desc())
    count_stmt = select(func.count()).select_from(Job).where(ownership)
    if job_type:
        stmt = stmt.where(Job.job_type == job_type)
        count_stmt = count_stmt.where(Job.job_type == job_type)
    if status_filter:
        stmt = stmt.where(Job.status == status_filter)
        count_stmt = count_stmt.where(Job.status == status_filter)

    total = (await db.execute(count_stmt)).scalar() or 0
    result = await db.execute(stmt.offset(offset).limit(limit))
    items = [
        {
            "id": str(j.id),
            "celery_task_id": j.celery_task_id,
            "job_type": j.job_type,
            "status": j.status,
            "reference_id": str(j.reference_id) if j.reference_id else None,
            "reference_type": j.reference_type,
            "attempts": j.attempts,
            "started_at": str(j.started_at) if j.started_at else None,
            "finished_at": str(j.finished_at) if j.finished_at else None,
            "created_at": str(j.created_at),
        }
        for j in result.scalars().all()
    ]
    return {"items": items, "total": total}
