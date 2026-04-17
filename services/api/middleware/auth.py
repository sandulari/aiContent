import os
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from models.user import User

SECRET_KEY = os.getenv("JWT_SECRET")
if not SECRET_KEY:
    SECRET_KEY = "dev-only-insecure-secret-do-not-use-in-production"
    import warnings
    warnings.warn("JWT_SECRET not set — using insecure development default", stacklevel=1)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRATION_HOURS", "24")) * 60

security = HTTPBearer()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
    return f"{salt}${h.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        salt, stored_hash = hashed_password.split("$", 1)
        h = hashlib.pbkdf2_hmac("sha256", plain_password.encode(), salt.encode(), 100000)
        return hmac.compare_digest(h.hex(), stored_hash)
    except (ValueError, AttributeError):
        return False


def create_access_token(user_id: UUID) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "iat": now,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = verify_token(credentials.credentials)
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return user


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
