import hmac
import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from middleware.auth import (
    clear_auth_cookies,
    create_access_token,
    create_refresh_token,
    create_reset_token,
    get_current_user,
    hash_password,
    hash_reset_token,
    hash_token,
    set_auth_cookies,
    verify_password,
)
from models.user import User
from schemas.user import UserCreate, UserLogin, UserResponse
from services.email_service import send_email
from services.email_templates import password_reset_email, welcome_email

logger = logging.getLogger(__name__)

APP_URL = os.getenv("APP_URL", "http://localhost:8080")

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ---------------------------------------------------------------------------
# In-memory per-IP rate limiter for unauthenticated auth endpoints.
# Keyed by the trusted client IP — caps brute-force login attempts and
# /forgot-password email floods. Per-IP rather than per-email so an
# attacker can't lock a victim out by submitting their email repeatedly.
# ---------------------------------------------------------------------------

_AUTH_RL: dict[str, list[float]] = defaultdict(list)
_AUTH_RL_WINDOW = 60        # seconds
_AUTH_RL_LOGIN_MAX = 8      # /login attempts / IP / window
_AUTH_RL_RESET_MAX = 5      # /forgot-password requests / IP / window
_AUTH_RL_REGISTER_MAX = 5   # /register attempts / IP / window — caps signup spam


def _client_ip(request: Request) -> str:
    """Best-effort caller IP. Falls back to a constant key if unavailable
    so the limiter never silently disables (e.g. behind a misconfigured
    proxy that strips the client address)."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return getattr(request.client, "host", None) or "unknown"


def _check_auth_rate_limit(request: Request, bucket: str, max_per_window: int) -> None:
    key = f"{bucket}:{_client_ip(request)}"
    now = time.time()
    hits = [t for t in _AUTH_RL[key] if now - t < _AUTH_RL_WINDOW]
    if len(hits) >= max_per_window:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please wait a minute and try again.",
        )
    hits.append(now)
    _AUTH_RL[key] = hits


# ---------------------------------------------------------------------------
# Request schemas specific to these endpoints
# ---------------------------------------------------------------------------

class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    token: str
    new_password: str = Field(..., min_length=8)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user_dict(user: User) -> dict:
    """Return the public user payload for auth responses."""
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
    }


async def _issue_tokens(user: User, db: AsyncSession, response: Response) -> dict:
    """Generate access + refresh tokens, persist refresh hash, set cookies."""
    access = create_access_token(user.id, role=user.role)
    raw_refresh, hashed_refresh, refresh_expires = create_refresh_token()

    user.refresh_token = hashed_refresh
    user.refresh_token_expires = refresh_expires
    await db.flush()

    set_auth_cookies(response, access, raw_refresh)
    return {"user": _user_dict(user)}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: UserCreate,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    _check_auth_rate_limit(request, "register", _AUTH_RL_REGISTER_MAX)
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        role="user",
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        # Race: another request inserted the same email between our
        # existence check and INSERT. The DB UNIQUE constraint won the
        # race; surface it as 409 instead of bubbling a 500.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    payload = await _issue_tokens(user, db, response)

    # Seed the AiModernTimes default template so the editor is never empty.
    # Non-blocking: registration succeeds even if Celery is unreachable.
    try:
        from celery_client import trigger_seed_default_template
        trigger_seed_default_template(user.id)
    except Exception:
        logger.warning("Default-template seed failed to queue for %s — continuing", user.email, exc_info=True)

    # Send welcome email (non-blocking — registration succeeds even if email fails)
    try:
        subject, html = welcome_email(user.display_name or user.email)
        await send_email(user.email, subject, html)
    except Exception:
        logger.warning("Welcome email failed for %s — continuing", user.email, exc_info=True)

    return payload


@router.post("/login")
async def login(
    body: UserLogin,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    _check_auth_rate_limit(request, "login", _AUTH_RL_LOGIN_MAX)
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    return await _issue_tokens(user, db, response)


@router.post("/refresh")
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """Exchange a valid refresh token cookie for new access + refresh tokens."""
    raw_refresh = request.cookies.get("refresh_token")
    if not raw_refresh:
        raise HTTPException(status_code=401, detail="No refresh token")

    hashed = hash_token(raw_refresh)
    result = await db.execute(select(User).where(User.refresh_token == hashed))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if user.refresh_token_expires and user.refresh_token_expires < datetime.now(timezone.utc):
        # Expired — clear everything
        user.refresh_token = None
        user.refresh_token_expires = None
        await db.flush()
        clear_auth_cookies(response)
        raise HTTPException(status_code=401, detail="Refresh token expired")

    # Rotate: issue new pair
    return await _issue_tokens(user, db, response)


@router.post("/logout")
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """Clear auth cookies and invalidate the refresh token in DB."""
    # Try to find user from access token to clear their refresh token
    token = request.cookies.get("access_token")
    if token:
        try:
            from middleware.auth import verify_access_token
            payload = verify_access_token(token)
            user_id = payload.get("sub")
            if user_id:
                from uuid import UUID
                result = await db.execute(select(User).where(User.id == UUID(user_id)))
                user = result.scalar_one_or_none()
                if user:
                    user.refresh_token = None
                    user.refresh_token_expires = None
                    await db.flush()
        except Exception:
            pass  # Best-effort — always clear cookies regardless

    clear_auth_cookies(response)
    return {"message": "Logged out"}


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return current_user


# ---------------------------------------------------------------------------
# Password reset (unchanged)
# ---------------------------------------------------------------------------

@router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Request a password-reset link. Always returns 200 to avoid leaking user existence."""
    _check_auth_rate_limit(request, "forgot", _AUTH_RL_RESET_MAX)
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if user:
        raw_token, hashed_token = create_reset_token()
        user.password_reset_token = hashed_token
        user.password_reset_expires = datetime.now(timezone.utc) + timedelta(hours=1)
        await db.flush()

        reset_url = f"{APP_URL}/auth/reset-password?token={raw_token}&email={user.email}"
        subject, html = password_reset_email(user.display_name or user.email, reset_url)
        await send_email(user.email, subject, html)

    return {"message": "If that email exists, a reset link has been sent."}


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Consume a reset token and set a new password."""
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user or not user.password_reset_token:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")

    if user.password_reset_expires and user.password_reset_expires < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Reset link has expired. Please request a new one.")

    hashed = hash_reset_token(body.token)
    # Constant-time comparison so a side channel can't differentiate
    # "wrong-token" from "no-such-user" via response timing.
    if not hmac.compare_digest(hashed, user.password_reset_token):
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")

    user.password_hash = hash_password(body.new_password)
    user.password_reset_token = None
    user.password_reset_expires = None

    return {"message": "Password updated successfully. You can now log in."}
