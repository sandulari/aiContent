"""Rotating refresh tokens with reuse detection (Task 2.4).

The session lifecycle:

  - **login / register**   creates a new family_id, inserts a fresh
                           ``refresh_tokens`` row keyed by the SHA-256
                           hash of the cookie value.
  - **/refresh (rotate)**   looks up the presented token's hash. On a
                           valid row, mark it revoked and insert a
                           successor in the SAME family. On a row
                           that is already ``revoked_at IS NOT NULL``,
                           treat it as a REUSE and delete every row in
                           the family — both attacker and victim
                           re-login, and the chain can't continue to
                           rotate forward.
  - **/logout**             revoke the current row. The family is left
                           in place (audit trail), but no token in it
                           can be used to refresh.

The result code returned from :func:`rotate_refresh_token` is what the
router branches on. It deliberately distinguishes ``unknown`` (no row
in DB — replayed an old token after a purge, or someone forged one)
from ``reuse`` (we still have the row, it was rotated past, and now
someone presented it again — almost certainly a stolen token). Both
end in 401 to the client, but only ``reuse`` purges the family.
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from middleware.auth import REFRESH_TOKEN_DAYS
from models.refresh_token import RefreshToken


class RotationResult(str, Enum):
    """What happened on a /refresh attempt. Drives router branching."""

    ROTATED = "rotated"  # success — new tokens issued
    UNKNOWN = "unknown"  # no row matched the presented hash
    EXPIRED = "expired"  # row matched but past expires_at
    REUSE = "reuse"      # row matched but was already revoked


@dataclass
class RotationOutcome:
    result: RotationResult
    user_id: Optional[UUID] = None
    family_id: Optional[UUID] = None
    new_raw_token: Optional[str] = None
    new_expires_at: Optional[datetime] = None


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _new_raw_token() -> str:
    """64 hex chars — the same format the legacy helper used so the
    cookie shape doesn't change. The format is opaque to clients."""
    return secrets.token_hex(32)


async def issue_new_family(
    db: AsyncSession, user_id: UUID
) -> tuple[str, datetime, UUID]:
    """Start a fresh refresh-token family — called on login / register.

    Returns ``(raw_token, expires_at, family_id)`` so the caller can
    set the cookie. The raw token is NEVER stored — only its SHA-256
    hash lands in the DB.
    """
    raw = _new_raw_token()
    family_id = uuid4()
    expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_DAYS)
    row = RefreshToken(
        user_id=user_id,
        family_id=family_id,
        token_hash=_hash(raw),
        expires_at=expires_at,
    )
    db.add(row)
    await db.flush()
    return raw, expires_at, family_id


async def rotate_refresh_token(db: AsyncSession, raw_token: str) -> RotationOutcome:
    """Validate + rotate. See module docstring for the state machine.

    On success the returned outcome carries ``new_raw_token`` for the
    response cookie; the caller doesn't need to know anything else
    about the row.
    """
    token_hash = _hash(raw_token)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    row = result.scalar_one_or_none()

    if row is None:
        # Unknown hash — either forged, or this hash was already purged
        # by a prior reuse-detection family wipe. Either way: 401, no
        # state change.
        return RotationOutcome(result=RotationResult.UNKNOWN)

    now = datetime.now(timezone.utc)

    if row.revoked_at is not None:
        # REUSE — someone presented a token we already rotated past.
        # Wipe the whole family so neither attacker nor victim can
        # continue. They both have to log in fresh.
        await db.execute(
            delete(RefreshToken).where(RefreshToken.family_id == row.family_id)
        )
        # COMMIT explicitly here: the auth router will raise HTTPException
        # on REUSE to return 401, which trips the get_db dependency's
        # `except Exception -> rollback` and would silently undo the
        # family deletion. Committing inside this function makes the
        # purge survive the HTTPException path. (This is the whole
        # point of reuse-detection — if rollback wins, the attacker's
        # successor token stays valid and we'd ship Task 2.4 broken.)
        await db.commit()
        return RotationOutcome(
            result=RotationResult.REUSE,
            user_id=row.user_id,
            family_id=row.family_id,
        )

    if row.expires_at < now:
        # Past expiry — mark it revoked so a future replay would still
        # be caught as REUSE, then refuse. Same commit-before-raise
        # reasoning as the REUSE branch above: the handler will raise
        # HTTPException(401) and the dependency rollback would undo
        # the revoked_at write otherwise.
        row.revoked_at = now
        await db.commit()
        return RotationOutcome(
            result=RotationResult.EXPIRED,
            user_id=row.user_id,
            family_id=row.family_id,
        )

    # Happy path: rotate. Old row revoked, successor inserted in same
    # family.
    row.revoked_at = now
    raw_new = _new_raw_token()
    expires_at = now + timedelta(days=REFRESH_TOKEN_DAYS)
    successor = RefreshToken(
        user_id=row.user_id,
        family_id=row.family_id,
        token_hash=_hash(raw_new),
        expires_at=expires_at,
    )
    db.add(successor)
    await db.flush()
    return RotationOutcome(
        result=RotationResult.ROTATED,
        user_id=row.user_id,
        family_id=row.family_id,
        new_raw_token=raw_new,
        new_expires_at=expires_at,
    )


async def revoke_token(db: AsyncSession, raw_token: str) -> bool:
    """Mark the row matching ``raw_token`` as revoked. Called on logout.

    Best-effort: returns False if there's no row to revoke (already
    purged / never existed) so the caller can still clear cookies.
    """
    token_hash = _hash(raw_token)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        await db.flush()
    return True
