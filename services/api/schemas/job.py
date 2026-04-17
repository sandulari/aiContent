from datetime import datetime
from typing import Any, Dict, List
from uuid import UUID

from pydantic import BaseModel


class JobResponse(BaseModel):
    id: UUID
    video_id: UUID | None = None
    instagram_page_id: UUID | None = None
    celery_task_id: str
    job_type: str
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    attempts: int
    logs: Dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobListResponse(BaseModel):
    items: List[JobResponse]
    total: int
