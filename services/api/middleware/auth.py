import hashlib
import hmac
import os
import secrets
import warnings
from datetime import datetime, timezone, timedelta
from uuid import UUID

from jose import jwt, JWTError
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db

JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    JWT_SECRET = "dev-only-insecure-secret-do-not-use-in-production"
    warnings.warn("JWT_SECRET not set — using insecure development default", stacklevel=1)

ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "60"))
REFRESH_TOKEN_DAYS = 7
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", None)  # None = current domain
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").lower() == "true"


# ---------------------------------------------------------------------------
# Password hashing (PBKDF2)
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
    return f"{salt.hex()}${key.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, key_hex = stored.split("$")
        salt = bytes.fromhex(salt_hex)
        key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
        return hmac.compare_digest(key.hex(), key_hex)
    except (ValueError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# Access token (short-lived JWT in httpOnly cookie)
# ---------------------------------------------------------------------------

def create_access_token(user_id: UUID, role: str = "user") -> str:
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_MINUTES),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def verify_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        return payload
    except JWTError as exc:
        # jose wraps expiry under JWTError; check message for specifics
        msg = str(exc).lower()
        if "expired" in msg:
            raise HTTPException(status_code=401, detail="Token expired")
        raise HTTPException(status_code=401, detail="Invalid token")


# ---------------------------------------------------------------------------
# Refresh token (long-lived random string, stored hashed in DB)
# ---------------------------------------------------------------------------

def create_refresh_token() -> tuple[str, str, datetime]:
    """Returns (raw_token, hashed_token, expires_at)."""
    raw = secrets.token_hex(32)
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    expires = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_DAYS)
    return raw, hashed, expires


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Password-reset token helpers
# ---------------------------------------------------------------------------

def create_reset_token() -> tuple[str, str]:
    """Return (raw_token_for_email, hashed_token_for_db)."""
    raw = secrets.token_urlsafe(32)
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    return raw, hashed


def hash_reset_token(raw_token: str) -> str:
    """Hash a raw reset token for comparison with the stored hash."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------

def set_auth_cookies(response: Response, access_token: str, refresh_token: str):
    """Set httpOnly cookies for both tokens."""
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        domain=COOKIE_DOMAIN,
        max_age=ACCESS_TOKEN_MINUTES * 60,
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        domain=COOKIE_DOMAIN,
        max_age=REFRESH_TOKEN_DAYS * 86400,
        path="/api/auth",  # Only sent to auth endpoints
    )


def clear_auth_cookies(response: Response):
    response.delete_cookie("access_token", path="/", domain=COOKIE_DOMAIN)
    response.delete_cookie("refresh_token", path="/api/auth", domain=COOKIE_DOMAIN)


# ---------------------------------------------------------------------------
# Auth dependency — reads from httpOnly cookie (or ?token= query param fallback)
# ---------------------------------------------------------------------------

async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Extract the current user from the access_token httpOnly cookie.

    Falls back to a ``?token=`` query param so browser-initiated downloads
    (window.open) still work.

    Uses the request-scoped DB session from ``Depends(get_db)``. FastAPI
    caches dependencies per-request, so a router that also declares
    ``db: AsyncSession = Depends(get_db)`` shares the same session — one
    pool connection per authenticated request instead of two.
    """
    from models.user import User

    token = request.cookies.get("access_token")
    if not token:
        token = request.query_params.get("token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = verify_access_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user
