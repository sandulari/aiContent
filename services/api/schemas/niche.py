from uuid import UUID

from pydantic import BaseModel, Field


class NicheCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    icon: str | None = None


class NicheResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    icon: str | None = None
    is_active: bool

    model_config = {"from_attributes": True}
