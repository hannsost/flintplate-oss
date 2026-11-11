"""JWT authentication and password hashing for palmscout."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import uuid4

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError as JWTError
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db

settings = get_settings()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ── Password ──────────────────────────────────────────────────────────────────


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── JWT ───────────────────────────────────────────────────────────────────────


def _utc_now() -> datetime:
    return datetime.now(UTC)


def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    expire = _utc_now() + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    payload = {**data, "exp": expire, "type": "access", "jti": uuid4().hex}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def create_refresh_token(data: dict[str, Any]) -> str:
    expire = _utc_now() + timedelta(days=settings.refresh_token_expire_days)
    payload = {**data, "exp": expire, "type": "refresh", "jti": uuid4().hex}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> dict[str, Any]:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token ungültig oder abgelaufen",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload: dict[str, Any] = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
        return payload
    except JWTError:
        raise credentials_error from None


# ── Dependency ────────────────────────────────────────────────────────────────

oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


async def get_current_user_optional(
    token: Annotated[str | None, Depends(oauth2_scheme_optional)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    """Like get_current_user but returns None instead of 401 when unauthenticated."""
    if not token:
        return None
    try:
        from app.users.models import User

        payload = decode_token(token)
        sub = payload.get("sub")
        if not sub or payload.get("type") != "access":
            return None
        result = await db.execute(select(User).where(User.email == sub))
        user = result.scalar_one_or_none()
        return (
            user
            if (user and user.is_active and payload.get("ver", 0) == user.auth_version)
            else None
        )
    except Exception:
        return None


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Any:
    from app.users.models import User  # deferred to avoid circular import

    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentifizierung fehlgeschlagen",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_token(token)
    sub: str | None = payload.get("sub")
    token_type: str | None = payload.get("type")

    if sub is None or token_type != "access":
        raise credentials_error

    result = await db.execute(select(User).where(User.email == sub))
    user: User | None = result.scalar_one_or_none()

    if user is None or not user.is_active or payload.get("ver", 0) != user.auth_version:
        raise credentials_error

    return user


def require_admin(user: Any) -> Any:
    """Raise 403 if user is not admin."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Nur Administratoren haben Zugriff",
        )
    return user


def require_recruiter(user: Any) -> Any:
    """Raise 403 if user is not recruiter or admin."""
    if user.role not in ("recruiter", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Nur Recruiter haben Zugriff",
        )
    return user


def require_worker(user: Any) -> Any:
    """Raise 403 if user is not a worker."""
    if user.role != "worker":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Nur Worker haben Zugriff",
        )
    return user


def require_support(user: Any) -> Any:
    """Raise 403 if user is not a support agent."""
    if user.role != "support":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Nur Support-Agenten haben Zugriff",
        )
    return user
