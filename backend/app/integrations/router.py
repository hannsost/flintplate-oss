"""Per-user connection setup and reviewed, permission-scoped email drafts."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.companies.workspace_access import workspace_user
from app.companies.workspace_router import visible_person
from app.database import get_db
from app.integrations import providers
from app.integrations.models import AuthorizationRequest, RecruitingMessage, WorkspaceConnection
from app.users.models import User

router = APIRouter(prefix="/workspace")
HR = Annotated[User, Depends(workspace_user)]
DB = Annotated[AsyncSession, Depends(get_db)]


class ConnectionRead(BaseModel):
    provider: str
    configured: bool
    connected: bool
    email: str | None = None
    detail: str | None = None


class AuthorizeRead(BaseModel):
    url: str


class CallbackRequest(BaseModel):
    state: str = Field(min_length=32, max_length=128)
    code: str = Field(min_length=1, max_length=4096)


class DraftCreate(BaseModel):
    person_id: uuid.UUID
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=10000)

    @field_validator("subject")
    @classmethod
    def subject_line(cls, value: str) -> str:
        if "\r" in value or "\n" in value or not value.strip():
            raise ValueError("Bitte einen Betreff in einer Zeile eingeben.")
        return value.strip()


class SendRequest(BaseModel):
    provider: providers.Provider
    confirmed: Literal[True]


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    person_id: uuid.UUID
    author_id: uuid.UUID | None
    recipient: str
    subject: str
    body: str
    status: str
    provider: str | None
    sent_at: datetime | None
    created_at: datetime


async def active_connection(
    db: AsyncSession, user: User, provider: providers.Provider
) -> tuple[WorkspaceConnection, str]:
    # Rotated OAuth credentials must survive a later failure of the business operation.
    # A separate engine-backed transaction also avoids holding the credential lock
    # throughout a mailbox/calendar request. Tests may supply an existing connection.
    async with AsyncSession(
        bind=db.bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
    ) as credentials:
        result = await connection_credentials(credentials, user, provider)
        await credentials.commit()
        return result


async def connection_credentials(
    db: AsyncSession, user: User, provider: providers.Provider
) -> tuple[WorkspaceConnection, str]:
    connection = (
        await db.execute(
            select(WorkspaceConnection)
            .where(
                WorkspaceConnection.user_id == user.id,
                WorkspaceConnection.tenant_id == user.tenant_id,
                WorkspaceConnection.provider == provider,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if connection is None:
        raise HTTPException(409, "Bitte zuerst dein E-Mail- und Kalenderkonto verbinden.")
    try:
        if connection.expires_at <= datetime.now(UTC) + timedelta(minutes=2):
            tokens = await providers.exchange(
                provider, refresh_token=providers.unseal(connection.refresh_cipher)
            )
            connection.access_cipher = providers.seal(tokens.access_token.get_secret_value())
            if tokens.refresh_token:
                connection.refresh_cipher = providers.seal(tokens.refresh_token.get_secret_value())
            connection.expires_at = datetime.now(UTC) + timedelta(seconds=tokens.expires_in)
            await db.flush()
        token = providers.unseal(connection.access_cipher)
    except providers.IntegrationError as exc:
        raise HTTPException(503, str(exc)) from None
    return connection, token


@router.get(
    "/connections",
    response_model=list[ConnectionRead],
    status_code=200,
    summary="Eigene E-Mail- und Kalenderverbindungen",
)
async def connections(user: HR, db: DB) -> list[ConnectionRead]:
    stored = (
        (
            await db.execute(
                select(WorkspaceConnection).where(
                    WorkspaceConnection.user_id == user.id,
                    WorkspaceConnection.tenant_id == user.tenant_id,
                )
            )
        )
        .scalars()
        .all()
    )
    result = []
    for provider in ("google", "microsoft"):
        connection = next((item for item in stored if item.provider == provider), None)
        detail = None
        try:
            providers.configuration(provider)
        except providers.IntegrationError as exc:
            detail = str(exc)
        result.append(
            ConnectionRead(
                provider=provider,
                configured=detail is None,
                connected=connection is not None,
                email=connection.email if connection else None,
                detail=detail,
            )
        )
    return result


@router.post(
    "/connections/{provider}/authorize",
    response_model=AuthorizeRead,
    status_code=200,
    summary="Verbindung beim Anbieter freigeben",
)
async def authorize(
    provider: providers.Provider, user: HR, db: DB, response: Response
) -> AuthorizeRead:
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    try:
        url = providers.authorization_url(provider, state, verifier)
        encrypted = providers.seal(verifier)
    except providers.IntegrationError as exc:
        raise HTTPException(503, str(exc)) from None
    db.add(
        AuthorizationRequest(
            user_id=user.id,
            tenant_id=user.tenant_id,
            provider=provider,
            state_digest=hashlib.sha256(state.encode()).hexdigest(),
            verifier_cipher=encrypted,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
    )
    await db.flush()
    response.headers["Cache-Control"] = "no-store"
    return AuthorizeRead(url=url)


@router.post(
    "/connections/callback",
    response_model=ConnectionRead,
    status_code=200,
    summary="Einmalige Anbieterfreigabe abschließen",
)
async def callback(data: CallbackRequest, user: HR, db: DB) -> ConnectionRead:
    # Serialize changes to this user's credentials, including concurrent reconnects.
    await db.execute(select(User.id).where(User.id == user.id).with_for_update())
    request = (
        await db.execute(
            select(AuthorizationRequest)
            .where(
                AuthorizationRequest.state_digest
                == hashlib.sha256(data.state.encode()).hexdigest(),
                AuthorizationRequest.user_id == user.id,
                AuthorizationRequest.tenant_id == user.tenant_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if request is None or request.used_at or request.expires_at <= datetime.now(UTC):
        raise HTTPException(
            410, "Die Verbindungsfreigabe ist ungültig oder abgelaufen. Bitte neu starten."
        )
    provider = cast(providers.Provider, request.provider)
    request.used_at = datetime.now(UTC)
    await db.commit()
    try:
        tokens = await providers.exchange(
            provider, code=data.code, verifier=providers.unseal(request.verifier_cipher)
        )
        if tokens.refresh_token is None:
            raise providers.IntegrationError(
                "Bitte beim Anbieter den dauerhaften Zugriff erneut freigeben."
            )
        email = await providers.account_email(provider, tokens.access_token.get_secret_value())
        access_cipher = providers.seal(tokens.access_token.get_secret_value())
        refresh_cipher = providers.seal(tokens.refresh_token.get_secret_value())
    except providers.IntegrationError as exc:
        raise HTTPException(503, str(exc)) from None
    refreshed_user = (
        await db.execute(
            select(User)
            .where(User.id == user.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    await db.refresh(request)
    if request.expires_at <= datetime.now(UTC):
        raise HTTPException(
            410, "Die Verbindung wurde inzwischen zurückgezogen. Bitte neu starten."
        )
    if (
        refreshed_user.tenant_id != request.tenant_id
        or refreshed_user.role not in {"admin", "recruiter"}
        or not refreshed_user.is_active
    ):
        raise HTTPException(403, "Der Arbeitsbereich ist nicht mehr verfügbar.")
    connection = (
        await db.execute(
            select(WorkspaceConnection).where(
                WorkspaceConnection.user_id == user.id, WorkspaceConnection.provider == provider
            )
        )
    ).scalar_one_or_none()
    if connection is None:
        connection = WorkspaceConnection(
            user_id=user.id, tenant_id=user.tenant_id, provider=provider
        )
        db.add(connection)
    connection.tenant_id = request.tenant_id
    connection.email = email
    connection.access_cipher = access_cipher
    connection.refresh_cipher = refresh_cipher
    connection.expires_at = datetime.now(UTC) + timedelta(seconds=tokens.expires_in)
    await db.flush()
    return ConnectionRead(provider=provider, configured=True, connected=True, email=email)


@router.delete(
    "/connections/{provider}",
    response_model=None,
    status_code=204,
    summary="Eigene Verbindung aus FlintPlate entfernen",
)
async def disconnect(provider: providers.Provider, user: HR, db: DB) -> None:
    await db.execute(select(User.id).where(User.id == user.id).with_for_update())
    connection = (
        await db.execute(
            select(WorkspaceConnection)
            .where(
                WorkspaceConnection.user_id == user.id,
                WorkspaceConnection.tenant_id == user.tenant_id,
                WorkspaceConnection.provider == provider,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if connection:
        await db.delete(connection)
    # Pending callbacks cannot silently restore a disconnected account.
    pending = (
        await db.execute(
            select(AuthorizationRequest).where(
                AuthorizationRequest.user_id == user.id,
                AuthorizationRequest.provider == provider,
            )
        )
    ).scalars()
    for request in pending:
        request.used_at = datetime.now(UTC)
        request.expires_at = datetime.now(UTC)
    await db.flush()


@router.get(
    "/messages",
    response_model=list[MessageRead],
    status_code=200,
    summary="Nachrichten zu einer Person im Arbeitsbereich",
)
async def messages(person_id: uuid.UUID, user: HR, db: DB) -> list[MessageRead]:
    await visible_person(db, user, person_id)
    records = (
        await db.execute(
            select(RecruitingMessage)
            .where(
                RecruitingMessage.tenant_id == user.tenant_id,
                RecruitingMessage.person_id == person_id,
                or_(RecruitingMessage.author_id == user.id, RecruitingMessage.status == "accepted"),
            )
            .order_by(RecruitingMessage.created_at.desc())
            .limit(100)
        )
    ).scalars()
    return [MessageRead.model_validate(message) for message in records]


@router.post(
    "/messages",
    response_model=MessageRead,
    status_code=201,
    summary="Prüfbaren Nachrichtenentwurf speichern",
)
async def create_draft(data: DraftCreate, user: HR, db: DB) -> MessageRead:
    person = await visible_person(db, user, data.person_id)
    message = RecruitingMessage(
        tenant_id=user.tenant_id,
        person_id=person.id,
        author_id=user.id,
        recipient=person.email,
        subject=data.subject,
        body=data.body,
        status="draft",
    )
    db.add(message)
    await db.flush()
    return MessageRead.model_validate(message)


async def own_draft(db: AsyncSession, user: User, message_id: uuid.UUID) -> RecruitingMessage:
    message = (
        await db.execute(
            select(RecruitingMessage)
            .where(
                RecruitingMessage.id == message_id,
                RecruitingMessage.tenant_id == user.tenant_id,
                RecruitingMessage.author_id == user.id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if message is None:
        raise HTTPException(404, "Nachricht nicht gefunden.")
    await visible_person(db, user, message.person_id)
    if message.status != "draft":
        raise HTTPException(
            409,
            "Diese Nachricht wurde bereits übergeben oder ihr Versandstatus muss beim Anbieter geprüft werden.",
        )
    return message


@router.patch(
    "/messages/{message_id}",
    response_model=MessageRead,
    status_code=200,
    summary="Eigenen Nachrichtenentwurf bearbeiten",
)
async def update_draft(message_id: uuid.UUID, data: DraftCreate, user: HR, db: DB) -> MessageRead:
    message = await own_draft(db, user, message_id)
    if data.person_id != message.person_id:
        raise HTTPException(409, "Der Empfänger eines Entwurfs kann nicht gewechselt werden.")
    message.subject, message.body = data.subject, data.body
    await db.flush()
    return MessageRead.model_validate(message)


@router.delete(
    "/messages/{message_id}",
    response_model=None,
    status_code=204,
    summary="Eigenen Entwurf verwerfen",
)
async def delete_draft(message_id: uuid.UUID, user: HR, db: DB) -> None:
    message = await own_draft(db, user, message_id)
    await db.delete(message)
    await db.flush()


@router.post(
    "/messages/{message_id}/send",
    response_model=MessageRead,
    status_code=200,
    summary="Geprüften Entwurf ausdrücklich zum Versand übergeben",
)
async def send(message_id: uuid.UUID, data: SendRequest, user: HR, db: DB) -> MessageRead:
    message = await own_draft(db, user, message_id)
    person = await visible_person(db, user, message.person_id)
    if person.email != message.recipient:
        raise HTTPException(
            409, "Die E-Mail-Adresse hat sich geändert. Bitte einen neuen Entwurf erstellen."
        )
    connection, token = await active_connection(db, user, data.provider)
    message.status, message.provider = "sending", data.provider
    # Persist before the external side effect. Never automatically retry an ambiguous send.
    await db.commit()
    try:
        external_id = await providers.send_email(
            data.provider, token, connection.email, message.recipient, message.subject, message.body
        )
    except providers.IntegrationError:
        message.status = "unknown"
    else:
        message.external_id = external_id
        message.status = "accepted"
        message.sent_at = datetime.now(UTC)
    await db.commit()
    return MessageRead.model_validate(message)


@router.get(
    "/messages/{message_id}/eml",
    response_model=None,
    status_code=200,
    summary="Eigenen Entwurf für das E-Mail-Programm herunterladen",
)
async def eml(message_id: uuid.UUID, user: HR, db: DB) -> Response:
    message = await own_draft(db, user, message_id)
    content = providers.mime_message(user.email, message.recipient, message.subject, message.body)
    return Response(
        content,
        media_type="message/rfc822",
        headers={
            "Content-Disposition": 'attachment; filename="FlintPlate-entwurf.eml"',
            "Cache-Control": "no-store",
        },
    )
