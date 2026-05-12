from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from services.sanitizer import clean_text


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=100)

    @field_validator("display_name")
    @classmethod
    def _strip_html(cls, v: str) -> str:
        """Strip any HTML tags. ``display_name`` is plain-text only and
        flows into HTML email templates — no markup allowed."""
        cleaned = clean_text(v) or ""
        if not cleaned:
            raise ValueError("display_name must contain non-empty text")
        return cleaned


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: UUID
    email: str
    display_name: str
    role: str = "user"
    created_at: datetime

    model_config = {"from_attributes": True}


class AuthUserResponse(BaseModel):
    """Returned inside the { user: ... } wrapper from auth endpoints."""
    id: UUID
    email: str
    display_name: str
    role: str


class TokenResponse(BaseModel):
    """Legacy — kept for schema compatibility but no longer used by new auth."""
    access_token: str
    token_type: str = "bearer"
