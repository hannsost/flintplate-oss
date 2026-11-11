"""Auth endpoints: register, login, refresh, password reset."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import RefreshRequest, TokenResponse
from app.auth.service import (
    authenticate_user,
    register_user,
    request_email_verification,
    request_password_reset,
    reset_password,
    rotate_refresh_token,
    verify_email_token,
)
from app.database import get_db
from app.users.schemas import Password, UserCreate

router = APIRouter()


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: Password


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=201,
    summary="Neuen Account registrieren",
)
async def register(
    user_in: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    access_token, refresh_token = await register_user(db, user_in)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login mit E-Mail und Passwort",
)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    user = await authenticate_user(db, email=form.username, password=form.password)
    token_data = {
        "sub": user.email,
        "ver": user.auth_version,
        "role": user.role,
        "tenant_id": str(user.tenant_id) if user.tenant_id else None,
    }
    from app.security import create_access_token, create_refresh_token

    return TokenResponse(
        access_token=create_access_token(token_data),
        refresh_token=create_refresh_token(token_data),
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Access-Token mit Refresh-Token erneuern",
)
async def refresh(
    body: RefreshRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    access_token, refresh_token = await rotate_refresh_token(db, body.refresh_token)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post(
    "/forgot-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Passwort-Reset anfordern – sendet E-Mail wenn Adresse bekannt",
)
async def forgot_password(
    body: ForgotPasswordRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Always returns 204 – does not reveal whether the email exists."""
    await request_password_reset(db, body.email)


@router.post(
    "/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Neues Passwort mit Reset-Token setzen",
)
async def reset_password_endpoint(
    body: ResetPasswordRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await reset_password(db, token=body.token, new_password=body.new_password)


class SendVerificationRequest(BaseModel):
    email: EmailStr


@router.post(
    "/send-verification",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Verifikations-E-Mail erneut anfordern",
)
async def send_verification(
    body: SendVerificationRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Always returns 204 – does not reveal whether the email exists."""
    await request_email_verification(db, body.email)


@router.get(
    "/verify-email",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="E-Mail-Adresse mit Token bestätigen",
)
async def verify_email_endpoint(
    token: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await verify_email_token(db, token)
