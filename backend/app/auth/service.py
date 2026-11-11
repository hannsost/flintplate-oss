"""Auth business logic – register, login, token rotation, password reset."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.users.models import PrivacyConsent, User
from app.users.schemas import UserCreate

_RESET_TTL = 3600  # 1 hour
_RESET_KEY_PREFIX = "pwd_reset:"

_VERIFY_TTL = 86400  # 24 hours
_VERIFY_KEY_PREFIX = "email_verify:"


async def register_user(db: AsyncSession, user_in: UserCreate) -> tuple[str, str]:
    """Create a new user + blank consent record. Returns (access_token, refresh_token)."""
    # Uniqueness check
    existing = await db.execute(select(User).where(User.email == user_in.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="E-Mail-Adresse ist bereits registriert",
        )

    user = User(
        email=user_in.email,
        hashed_password=hash_password(user_in.password),
        full_name=user_in.full_name,
    )
    db.add(user)
    await db.flush()  # populate user.id

    consent = PrivacyConsent(user_id=user.id)
    db.add(consent)
    await db.flush()

    # Fire-and-forget verification email
    import asyncio

    asyncio.ensure_future(_send_verification(user.email))

    token_data = {"sub": user.email, "ver": user.auth_version, "role": user.role, "tenant_id": None}
    return create_access_token(token_data), create_refresh_token(token_data)


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User:
    """Verify credentials. Raises 401 on failure."""
    result = await db.execute(select(User).where(User.email == email.lower()))
    user: User | None = result.scalar_one_or_none()

    if user is None or not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ungültige E-Mail oder Passwort",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Konto ist deaktiviert",
        )

    return user


async def request_password_reset(db: AsyncSession, email: str) -> None:
    """Generate a reset token, store in Redis, send email. Silent if user not found."""
    result = await db.execute(select(User).where(User.email == email.lower()))
    user = result.scalar_one_or_none()
    if not user:
        return  # Don't reveal whether the email exists

    token = secrets.token_urlsafe(32)
    try:
        import redis.asyncio as aioredis

        from app.config import get_settings

        r = aioredis.from_url(get_settings().redis_url, decode_responses=True)
        async with r:
            await r.set(f"{_RESET_KEY_PREFIX}{token}", user.email, ex=_RESET_TTL)
    except Exception:
        pass  # Redis unavailable → token is lost, but we won't raise

    from app.email.sender import send_password_reset_email

    await send_password_reset_email(email=user.email, token=token)


async def reset_password(db: AsyncSession, token: str, new_password: str) -> None:
    """Validate reset token from Redis, update password, invalidate token."""
    email: str | None = None
    try:
        import redis.asyncio as aioredis

        from app.config import get_settings

        r = aioredis.from_url(get_settings().redis_url, decode_responses=True)
        async with r:
            key = f"{_RESET_KEY_PREFIX}{token}"
            value = await r.getdel(key)
            email = value.decode() if isinstance(value, bytes) else value
    except Exception:
        pass

    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ungültiger oder abgelaufener Reset-Link.",
        )

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden.")

    user.hashed_password = hash_password(new_password)
    user.auth_version += 1
    await db.flush()


async def _send_verification(email: str) -> None:
    """Internal helper: generate verification token and send email."""
    token = secrets.token_urlsafe(32)
    try:
        import redis.asyncio as aioredis

        from app.config import get_settings

        r = aioredis.from_url(get_settings().redis_url, decode_responses=True)
        async with r:
            await r.set(f"{_VERIFY_KEY_PREFIX}{token}", email, ex=_VERIFY_TTL)
    except Exception:
        pass

    from app.email.sender import send_verification_email

    await send_verification_email(email=email, token=token)


async def request_email_verification(db: AsyncSession, user_email: str) -> None:
    """Re-send verification email for an existing unverified user. Silent on unknown email."""
    result = await db.execute(select(User).where(User.email == user_email.lower()))
    user = result.scalar_one_or_none()
    if not user or user.is_verified:
        return
    await _send_verification(user.email)


async def verify_email_token(db: AsyncSession, token: str) -> None:
    """Validate email verification token from Redis and mark user as verified."""
    email: str | None = None
    try:
        import redis.asyncio as aioredis

        from app.config import get_settings

        r = aioredis.from_url(get_settings().redis_url, decode_responses=True)
        async with r:
            key = f"{_VERIFY_KEY_PREFIX}{token}"
            value = await r.getdel(key)
            email = value.decode() if isinstance(value, bytes) else value
    except Exception:
        pass

    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ungültiger oder abgelaufener Bestätigungslink.",
        )

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user and not user.is_verified:
        user.is_verified = True
        await db.flush()


async def rotate_refresh_token(db: AsyncSession, old_token: str) -> tuple[str, str]:
    """Validate a refresh token and return a fresh (access, refresh) pair."""
    payload = decode_token(old_token)

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Kein gültiger Refresh-Token",
        )

    sub: str | None = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token enthält kein Subjekt",
        )

    user = await db.scalar(select(User).where(User.email == sub))
    if user is None or not user.is_active or payload.get("ver", 0) != user.auth_version:
        raise HTTPException(status_code=401, detail="Konto ist nicht verfügbar")
    # Atomically consume the previous token, including legacy tokens without jti.
    import redis.asyncio as aioredis
    from redis.exceptions import RedisError

    from app.config import get_settings

    ttl = max(1, int(payload["exp"] - datetime.now(UTC).timestamp()))
    key = "used_refresh:" + hashlib.sha256(old_token.encode()).hexdigest()
    try:
        async with aioredis.from_url(get_settings().redis_url) as cache:
            consumed = await cache.set(key, "1", ex=ttl, nx=True)
    except RedisError as exc:
        raise HTTPException(
            status_code=503,
            detail="Sitzung kann gerade nicht erneuert werden. Bitte erneut versuchen.",
        ) from exc
    if not consumed:
        raise HTTPException(status_code=401, detail="Refresh-Token wurde bereits verwendet.")

    # Read current authorization from the database: role and tenant can change
    # during a session, and the browser needs both after refreshing its token.
    token_data = {
        "sub": user.email,
        "ver": user.auth_version,
        "role": user.role,
        "tenant_id": str(user.tenant_id) if user.tenant_id else None,
    }
    return create_access_token(token_data), create_refresh_token(token_data)
