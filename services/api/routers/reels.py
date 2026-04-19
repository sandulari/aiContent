"""Viral reel detail, source search, download."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from db.session import get_db
from middleware.auth import get_current_user
from models.user import User
from models.viral_reel import ViralReel
from models.video_source import VideoSource
from models.video_file import VideoFile
from models.theme_page import ThemePage
from models.job import Job
from celery_client import trigger_source_search, trigger_download

router = APIRouter(prefix="/api/reels", tags=["reels"])


class ReelDetailResponse(BaseModel):
    id: str
    ig_video_id: str
    ig_url: str
    thumbnail_url: str | None = None
    view_count: int
    like_count: int
    comment_count: int | None = None
    duration_seconds: float | None = None
    caption: str | None = None
    posted_at: str | None = None
    status: str
    source_page: str | None = None
    sources: list = []
    files: list = []

    model_config = {"from_attributes": True}


@router.get("/{reel_id}")
async def get_reel(reel_id: UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ViralReel)
        .options(selectinload(ViralReel.sources), selectinload(ViralReel.files))
        .where(ViralReel.id == reel_id)
    )
    reel = result.scalar_one_or_none()
    if not reel:
        raise HTTPException(status_code=404, detail="Reel not found")

    # Get source page username
    page_result = await db.execute(select(ThemePage.username).where(ThemePage.id == reel.theme_page_id))
    source_page = page_result.scalar_one_or_none()

    return {
        "id": str(reel.id), "ig_video_id": reel.ig_video_id, "ig_url": reel.ig_url,
        "thumbnail_url": reel.thumbnail_url, "view_count": reel.view_count,
        "like_count": reel.like_count, "comment_count": reel.comment_count,
        "duration_seconds": reel.duration_seconds, "caption": reel.caption,
        "posted_at": str(reel.posted_at) if reel.posted_at else None,
        "status": reel.status, "source_page": source_page,
        "sources": [
            {"id": str(s.id), "source_type": s.source_type, "source_url": s.source_url,
             "source_title": s.source_title, "match_confidence": s.match_confidence,
             "is_selected": s.is_selected, "found_at": str(s.found_at)}
            for s in sorted(reel.sources, key=lambda x: x.match_confidence or 0, reverse=True)
        ],
        "files": [
            {"id": str(f.id), "file_type": f.file_type, "resolution": f.resolution,
             "file_size_bytes": f.file_size_bytes, "created_at": str(f.created_at)}
            for f in reel.files
        ],
    }


@router.post("/{reel_id}/find-sources", status_code=status.HTTP_202_ACCEPTED)
async def find_sources(
    reel_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    reel = await db.get(ViralReel, reel_id)
    if not reel:
        raise HTTPException(status_code=404, detail="Reel not found")
    reel.status = "searching_source"
    task_id = trigger_source_search(reel_id)
    job = Job(celery_task_id=task_id, job_type="search_source", status="pending", reference_id=reel_id, reference_type="viral_reel")
    db.add(job)
    await db.flush()
    await db.refresh(job)
    return {"job_id": str(job.id), "status": "searching"}


class DownloadRequest(BaseModel):
    source_id: UUID


@router.post("/{reel_id}/download", status_code=status.HTTP_202_ACCEPTED)
async def download_reel(
    reel_id: UUID, body: DownloadRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    reel = await db.get(ViralReel, reel_id)
    if not reel:
        raise HTTPException(status_code=404, detail="Reel not found")
    source = await db.get(VideoSource, body.source_id)
    if not source or source.viral_reel_id != reel_id:
        raise HTTPException(status_code=404, detail="Source not found")

    source.is_selected = True
    reel.status = "downloading"
    task_id = trigger_download(reel_id, body.source_id)
    job = Job(celery_task_id=task_id, job_type="download", status="pending", reference_id=reel_id, reference_type="viral_reel")
    db.add(job)
    await db.flush()
    await db.refresh(job)
    return {"job_id": str(job.id), "status": "downloading"}


@router.post("/{reel_id}/download-direct", status_code=status.HTTP_202_ACCEPTED)
async def download_reel_direct(
    reel_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Download directly from Instagram — no source search needed.

    Creates an auto-source from the IG URL and triggers the download
    immediately. The student gets the video every time, guaranteed.
    """
    reel = await db.get(ViralReel, reel_id)
    if not reel:
        raise HTTPException(status_code=404, detail="Reel not found")

    # Check if already downloaded
    from sqlalchemy import select as sa_select
    existing_file = await db.execute(
        sa_select(VideoFile).where(VideoFile.viral_reel_id == reel_id).limit(1)
    )
    if existing_file.scalar_one_or_none():
        reel.status = "downloaded"
        return {"status": "already_downloaded", "reel_id": str(reel_id)}

    # Create an Instagram source automatically
    ig_url = reel.ig_url or f"https://www.instagram.com/reel/{reel.ig_video_id}/"
    source = VideoSource(
        viral_reel_id=reel_id,
        source_type="instagram",
        source_url=ig_url,
        source_title=f"Instagram Reel @{reel.ig_video_id}",
        match_confidence=1.0,
        is_selected=True,
    )
    db.add(source)
    await db.flush()
    await db.refresh(source)

    reel.status = "downloading"
    task_id = trigger_download(reel_id, source.id)
    job = Job(
        celery_task_id=task_id, job_type="download", status="pending",
        reference_id=reel_id, reference_type="viral_reel",
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)
    return {"job_id": str(job.id), "status": "downloading"}
