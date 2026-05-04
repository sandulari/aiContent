"""Instagram API with Instagram Login — OAuth router.

Flow summary:
    /start   -> builds Meta authorize URL with HMAC-signed state
    /callback -> exchanges code for long-lived token, persists encrypted
    /status  -> safe read-only view for the UI (never returns raw token)
    /refresh -> extends long-lived token before expiry
    /disconnect -> clears persisted OAuth state

Long-lived IG tokens live 60 days. The access token is Fernet-encrypted
at rest (see services/crypto.py). Never log or return the raw token —
use redact_token() for anything that touches logs.

State parameter: `b64url(nonce).hex(HMAC_SHA256(nonce, META_APP_SECRET))`.
Nonce also stored in Redis (TTL 10 min) mapped to user_id, so replays
after expiry are 401. Double defense: HMAC verifies we issued the state,
Redis verifies it hasn't been consumed.
"""
from __future__ import annotations

import base64
import hmac
import hashlib
import logging
import os
import secrets
from datetime import datetime, timezone, timedelta
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from middleware.auth import get_current_user
from models.user import User
from services.crypto import encrypt_token, decrypt_token, redact_token, TokenDecryptionError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ig/oauth", tags=["instagram-oauth"])

META_APP_ID = os.getenv("META_APP_ID", "")
META_APP_SECRET = os.getenv("META_APP_SECRET", "")
META_OAUTH_REDIRECT_URI = os.getenv("META_OAUTH_REDIRECT_URI", "")
META_GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v25.0")
APP_URL = os.getenv("APP_URL", "http://localhost:3000")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

# Scopes required for this app: profile basics + publish + read insights.
# Managed comments/messages could be added later without changing the flow.
# NOTE: `instagram_business_manage_insights` was added to power the
# post-publish insights feature on /scheduled. Tokens issued before this
# change do NOT carry the insights permission — those users must re-OAuth
# (click "Reconnect" on /settings/instagram) before insights will load.
OAUTH_SCOPES = "instagram_business_basic,instagram_business_content_publish,instagram_business_manage_insights"

# Account types that can publish through the API. PERSONAL cannot.
PUBLISHABLE_ACCOUNT_TYPES = {"BUSINESS", "CREATOR", "MEDIA_CREATOR"}

# Redis key prefix + TTL for the anti-replay nonce.
_NONCE_KEY_PREFIX = "ig_oauth_nonce:"
_NONCE_TTL_SECONDS = 600  # 10 minutes

# Shared HTTP client not reused across requests — FastAPI spins these up
# per call. Keeping it simple beats lifecycle bugs for a low-volume flow.
_HTTP_TIMEOUT = httpx.Timeout(15.0)


# ---------------------------------------------------------------------------
# State nonce helpers (HMAC + Redis)
# ---------------------------------------------------------------------------

def _assert_configured() -> None:
    """Raise 500 with a clear message if env isn't wired. Beats an opaque
    ``signature is empty`` 500 later in the flow."""
    if not META_APP_ID or not META_APP_SECRET or not META_OAUTH_REDIRECT_URI:
        raise HTTPException(
            status_code=500,
            detail="Instagram OAuth is not configured on the server",
        )


def _sign_state(nonce: str) -> str:
    """Build state = b64url(nonce).hex(HMAC_SHA256(nonce, app_secret))."""
    mac = hmac.new(
        META_APP_SECRET.encode(), nonce.encode(), hashlib.sha256
    ).hexdigest()
    encoded = base64.urlsafe_b64encode(nonce.encode()).rstrip(b"=").decode()
    return f"{encoded}.{mac}"


def _verify_state(state: str) -> str | None:
    """Verify HMAC and return the raw nonce. Returns None on any failure."""
    try:
        encoded, mac = state.split(".", 1)
    except ValueError:
        return None
    # Re-pad base64 — urlsafe_b64decode is strict about padding.
    pad = "=" * (-len(encoded) % 4)
    try:
        nonce = base64.urlsafe_b64decode(encoded + pad).decode()
    except Exception:
        return None
    expected = hmac.new(
        META_APP_SECRET.encode(), nonce.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, mac):
        return None
    return nonce


def _redis_client() -> Redis:
    return Redis.from_url(REDIS_URL, decode_responses=True)


# Required scope for content publishing — without it, /scheduled-reels
# will fail at Graph API time. Validated at OAuth completion so a user
# who deselects the publish scope sees the error immediately, not later.
_REQUIRED_PUBLISH_SCOPE = "instagram_business_content_publish"


async def _consume_nonce(state: str | None) -> None:
    """Best-effort delete of the Redis nonce — for error / abandon paths.

    Returning early on error without consuming would leave the nonce live
    for 10 min; harmless but messy.
    """
    if not state:
        return
    nonce = _verify_state(state)
    if not nonce:
        return
    redis = _redis_client()
    try:
        await redis.delete(_NONCE_KEY_PREFIX + nonce)
    except Exception:  # noqa: BLE001 — Redis can fail; nonce will TTL out.
        pass
    finally:
        await redis.aclose()


# ---------------------------------------------------------------------------
# Meta API calls (all isolated in helpers for testability)
# ---------------------------------------------------------------------------

async def _exchange_code_for_short_lived(code: str) -> dict[str, Any]:
    """POST to api.instagram.com/oauth/access_token — returns short-lived token."""
    url = "https://api.instagram.com/oauth/access_token"
    data = {
        "client_id": META_APP_ID,
        "client_secret": META_APP_SECRET,
        "grant_type": "authorization_code",
        "redirect_uri": META_OAUTH_REDIRECT_URI,
        "code": code,
    }
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(url, data=data)

    if resp.status_code != 200:
        body = _safe_error_body(resp)
        logger.warning("IG short-lived exchange failed: %s %s", resp.status_code, body)
        # IG returns error_type=OAuthException for reused/expired codes.
        detail = (body.get("error_message") or body.get("error_description")
                  or "Authorization code could not be exchanged")
        raise HTTPException(status_code=400, detail=detail)

    payload = resp.json()
    if "access_token" not in payload:
        raise HTTPException(status_code=502, detail="Malformed IG response")
    return payload


async def _exchange_for_long_lived(short_token: str) -> dict[str, Any]:
    """GET graph.instagram.com/.../access_token?grant_type=ig_exchange_token."""
    url = f"https://graph.instagram.com/{META_GRAPH_VERSION}/access_token"
    params = {
        "grant_type": "ig_exchange_token",
        "client_secret": META_APP_SECRET,
        "access_token": short_token,
    }
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(url, params=params)

    if resp.status_code != 200:
        body = _safe_error_body(resp)
        logger.warning("IG long-lived exchange failed: %s %s", resp.status_code, body)
        raise HTTPException(status_code=502, detail="Failed to obtain long-lived token")

    payload = resp.json()
    if "access_token" not in payload or "expires_in" not in payload:
        raise HTTPException(status_code=502, detail="Malformed long-lived response")
    return payload


async def _fetch_profile(access_token: str) -> dict[str, Any]:
    """GET /me?fields=id,username,account_type,profile_picture_url."""
    url = f"https://graph.instagram.com/{META_GRAPH_VERSION}/me"
    params = {
        "fields": "id,username,account_type,profile_picture_url",
        "access_token": access_token,
    }
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(url, params=params)

    if resp.status_code != 200:
        body = _safe_error_body(resp)
        logger.warning("IG profile fetch failed: %s %s", resp.status_code, body)
        raise HTTPException(status_code=502, detail="Failed to fetch IG profile")

    return resp.json()


async def _refresh_long_lived(access_token: str) -> dict[str, Any]:
    """GET /refresh_access_token?grant_type=ig_refresh_token&access_token=..."""
    url = f"https://graph.instagram.com/{META_GRAPH_VERSION}/refresh_access_token"
    params = {"grant_type": "ig_refresh_token", "access_token": access_token}
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(url, params=params)

    if resp.status_code != 200:
        body = _safe_error_body(resp)
        logger.warning("IG token refresh failed: %s %s", resp.status_code, body)
        raise HTTPException(status_code=502, detail="Failed to refresh IG token")

    payload = resp.json()
    if "access_token" not in payload or "expires_in" not in payload:
        raise HTTPException(status_code=502, detail="Malformed refresh response")
    return payload


def _safe_error_body(resp: httpx.Response) -> dict[str, Any]:
    """Parse Meta's error JSON without risking another exception in a log line."""
    try:
        payload = resp.json()
    except Exception:
        return {"raw": resp.text[:500]}
    if isinstance(payload, dict) and "error" in payload and isinstance(payload["error"], dict):
        return payload["error"]
    return payload if isinstance(payload, dict) else {"body": payload}


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _safe_status(user: User) -> dict[str, Any]:
    """Build the public-safe payload — NEVER includes the raw or encrypted token."""
    connected = bool(user.ig_access_token and user.ig_user_id)
    expires_at = user.ig_token_expires_at
    now = datetime.now(timezone.utc)

    # Normalize tz-naive datetimes (shouldn't happen in prod, but defensive).
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    token_valid = bool(expires_at and expires_at > now)
    can_publish = bool(
        connected
        and token_valid
        and (user.ig_account_type or "").upper() in PUBLISHABLE_ACCOUNT_TYPES
    )

    return {
        "connected": connected,
        "ig_user_id": user.ig_user_id,
        "ig_username": user.ig_username,
        "ig_account_type": user.ig_account_type,
        "ig_profile_picture_url": user.ig_profile_picture_url,
        "ig_token_expires_at": expires_at.isoformat() if expires_at else None,
        "ig_connected_at": user.ig_connected_at.isoformat() if user.ig_connected_at else None,
        "can_publish": can_publish,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/start")
async def oauth_start(current_user: User = Depends(get_current_user)):
    """Return the Meta authorize URL the frontend should redirect to."""
    _assert_configured()

    nonce = secrets.token_urlsafe(24)
    state = _sign_state(nonce)

    redis = _redis_client()
    try:
        await redis.set(
            _NONCE_KEY_PREFIX + nonce,
            str(current_user.id),
            ex=_NONCE_TTL_SECONDS,
        )
    finally:
        await redis.aclose()

    authorize_url = (
        "https://www.instagram.com/oauth/authorize"
        f"?force_reauth=true"
        f"&client_id={META_APP_ID}"
        f"&redirect_uri={META_OAUTH_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={OAUTH_SCOPES}"
        f"&state={state}"
    )
    return {"authorize_url": authorize_url}


@router.get("/callback")
async def oauth_callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Meta redirects here after the user approves or denies."""
    _assert_configured()

    # Case 1: user denied or Meta returned an error.
    if error:
        logger.info("IG OAuth denied or errored: %s — %s", error, error_description)
        await _consume_nonce(state)
        return RedirectResponse(
            url=f"{APP_URL}/settings/instagram?error={quote(error, safe='')}",
            status_code=302,
        )

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    # Verify HMAC signature on state.
    nonce = _verify_state(state)
    if not nonce:
        logger.warning("IG OAuth state signature invalid")
        raise HTTPException(status_code=400, detail="Invalid state")

    # Pop the nonce from Redis — single-use. If missing, it was already
    # consumed (replay) or expired past the 10-min window.
    redis = _redis_client()
    try:
        raw_user_id = await redis.getdel(_NONCE_KEY_PREFIX + nonce)
    finally:
        await redis.aclose()

    if not raw_user_id:
        logger.warning("IG OAuth nonce missing — replay or expiry")
        raise HTTPException(status_code=401, detail="State expired or replayed")

    try:
        user_uuid = UUID(raw_user_id)
    except ValueError:
        raise HTTPException(status_code=500, detail="Invalid user id in state store")

    # Exchange short-lived -> long-lived -> profile.
    short = await _exchange_code_for_short_lived(code)
    short_token = short["access_token"]
    permissions = short.get("permissions") or []

    long_lived = await _exchange_for_long_lived(short_token)
    long_token = long_lived["access_token"]
    expires_in = int(long_lived["expires_in"])

    profile = await _fetch_profile(long_token)
    account_type = (profile.get("account_type") or "").upper()

    # Lock the user row and update.
    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Hard stop on PERSONAL — we can't publish from those accounts.
    if account_type == "PERSONAL":
        logger.info(
            "IG OAuth rejected PERSONAL account for user=%s ig=%s",
            user.id, profile.get("username"),
        )
        return RedirectResponse(
            url=f"{APP_URL}/settings/instagram?error=personal_account_not_supported",
            status_code=302,
        )

    # Hard stop if the user deselected the publish scope on Meta's consent
    # screen. Without it, every /scheduled-reels publish would fail at
    # Graph API time and `can_publish` would lie to the UI.
    granted_scopes = (
        {p.lower() for p in permissions}
        if isinstance(permissions, list)
        else {p.strip().lower() for p in str(permissions).split(",") if p.strip()}
    )
    if _REQUIRED_PUBLISH_SCOPE not in granted_scopes:
        logger.info(
            "IG OAuth missing publish scope for user=%s ig=%s granted=%s",
            user.id, profile.get("username"), sorted(granted_scopes),
        )
        return RedirectResponse(
            url=f"{APP_URL}/settings/instagram?error=missing_publish_scope",
            status_code=302,
        )

    now = datetime.now(timezone.utc)
    scope_str = ",".join(permissions) if isinstance(permissions, list) else str(permissions)

    user.ig_user_id = str(profile.get("id") or "") or None
    user.ig_username = profile.get("username") or user.ig_username
    user.ig_account_type = account_type or None
    user.ig_access_token = encrypt_token(long_token)
    user.ig_token_expires_at = now + timedelta(seconds=expires_in)
    user.ig_token_scope = scope_str or None
    user.ig_profile_picture_url = profile.get("profile_picture_url") or None
    user.ig_connected_at = now
    user.ig_auth_method = "oauth"
    await db.flush()

    logger.info(
        "IG OAuth connected user=%s ig=%s type=%s token=%s",
        user.id, profile.get("username"), account_type, redact_token(long_token),
    )

    return RedirectResponse(
        url=f"{APP_URL}/settings/instagram?connected=1",
        status_code=302,
    )


@router.get("/status")
async def oauth_status(current_user: User = Depends(get_current_user)):
    return _safe_status(current_user)


@router.post("/refresh")
async def oauth_refresh(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Extend an existing long-lived token (IG docs: 60 days max after refresh)."""
    if not current_user.ig_access_token:
        raise HTTPException(status_code=400, detail="Instagram is not connected")

    try:
        plain = decrypt_token(current_user.ig_access_token)
    except TokenDecryptionError:
        # Key rotated or copied from another env — force reconnect.
        current_user.ig_access_token = None
        current_user.ig_token_expires_at = None
        await db.flush()
        raise HTTPException(
            status_code=401,
            detail="Stored token is unreadable — please reconnect Instagram",
        )

    payload = await _refresh_long_lived(plain)
    new_token = payload["access_token"]
    expires_in = int(payload["expires_in"])
    now = datetime.now(timezone.utc)

    current_user.ig_access_token = encrypt_token(new_token)
    current_user.ig_token_expires_at = now + timedelta(seconds=expires_in)
    await db.flush()

    logger.info(
        "IG token refreshed user=%s ig=%s token=%s",
        current_user.id, current_user.ig_username, redact_token(new_token),
    )
    return {
        "expires_at": current_user.ig_token_expires_at.isoformat(),
    }


@router.post("/disconnect")
async def oauth_disconnect(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Clear all IG OAuth state. Leaves the legacy ig_username /
    ig_session_data alone since the RapidAPI scraper still uses them."""
    current_user.ig_user_id = None
    current_user.ig_account_type = None
    current_user.ig_access_token = None
    current_user.ig_token_expires_at = None
    current_user.ig_token_scope = None
    current_user.ig_profile_picture_url = None
    current_user.ig_connected_at = None
    current_user.ig_auth_method = "username_only"
    await db.flush()

    logger.info("IG disconnected user=%s", current_user.id)
    return {"disconnected": True}
