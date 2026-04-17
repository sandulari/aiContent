from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=100)


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
