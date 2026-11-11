"""Read person-specific mailbox previews without importing a user's entire mailbox."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from email.utils import parseaddr
from html import unescape
from typing import Annotated
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import AwareDatetime, BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.companies.workspace_access import workspace_user
from app.companies.workspace_router import visible_person
from app.database import get_db
from app.integrations import providers
from app.integrations.router import active_connection
from app.users.models import User

router = APIRouter(prefix="/workspace")


class InboxMessage(BaseModel):
    id: str
    subject: str
    sender: str
    preview: str
    received_at: datetime


class InboxRead(BaseModel):
    provider: providers.Provider
    messages: list[InboxMessage]
    limited: bool
    days: int = 90


class Header(BaseModel):
    name: str
    value: str


class GmailPayload(BaseModel):
    headers: list[Header] = Field(default_factory=list)


class GmailMeta(BaseModel):
    id: str = Field(min_length=1, max_length=255)
    snippet: str = Field(default="", max_length=4000)
    internalDate: int = Field(ge=0, le=253402300799000)
    payload: GmailPayload


class MailAddress(BaseModel):
    address: str


class MailSender(BaseModel):
    emailAddress: MailAddress


class MicrosoftMessage(BaseModel):
    id: str = Field(min_length=1, max_length=1000)
    subject: str = Field(default="", max_length=2000)
    bodyPreview: str = Field(default="", max_length=4000)
    receivedDateTime: AwareDatetime
    sender: MailSender = Field(alias="from")


class MicrosoftBatch(BaseModel):
    value: list[MicrosoftMessage]
    next_link: str | None = Field(default=None, alias="@odata.nextLink")


async def mailbox_previews(provider: providers.Provider, token: str, address: str) -> InboxRead:
    since = datetime.now(UTC) - timedelta(days=90)
    try:
        async with asyncio.timeout(25):
            if provider == "microsoft":
                escaped = address.replace("'", "''")
                query = urlencode(
                    {
                        "$select": "id,subject,from,receivedDateTime,bodyPreview",
                        "$filter": f"receivedDateTime ge {since.isoformat()} and from/emailAddress/address eq '{escaped}'",
                        "$orderby": "receivedDateTime desc",
                        "$top": "20",
                    }
                )
                batch = MicrosoftBatch.model_validate(
                    await providers.api(
                        "GET", "https://graph.microsoft.com/v1.0/me/messages?" + query, token
                    )
                )
                return InboxRead(
                    provider=provider,
                    limited=bool(batch.next_link) or len(batch.value) > 20,
                    messages=[
                        InboxMessage(
                            id=item.id,
                            subject=item.subject or "Ohne Betreff",
                            sender=address,
                            preview=item.bodyPreview,
                            received_at=item.receivedDateTime,
                        )
                        for item in batch.value[:20]
                        if item.sender.emailAddress.address.casefold() == address.casefold()
                        and item.receivedDateTime >= since
                    ],
                )
            query = urlencode(
                {
                    "q": f"from:({address}) newer_than:90d",
                    "maxResults": "20",
                    "includeSpamTrash": "false",
                }
            )
            listed = await providers.api(
                "GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages?" + query, token
            )
            raw_ids = listed.get("messages", [])
            if not isinstance(raw_ids, list):
                raise providers.IntegrationError("Der Posteingang konnte nicht gelesen werden.")
            ids = [item.get("id") for item in raw_ids[:20] if isinstance(item, dict)]
            if len(ids) != min(len(raw_ids), 20) or any(
                not isinstance(value, str) or not value for value in ids
            ):
                raise providers.IntegrationError("Der Posteingang konnte nicht gelesen werden.")
            semaphore = asyncio.Semaphore(5)

            async def fetch(message_id: str) -> InboxMessage | None:
                async with semaphore:
                    data = GmailMeta.model_validate(
                        await providers.api(
                            "GET",
                            "https://gmail.googleapis.com/gmail/v1/users/me/messages/"
                            + quote(message_id, safe="")
                            + "?format=metadata&metadataHeaders=From&metadataHeaders=Subject",
                            token,
                        )
                    )
                headers = {header.name.lower(): header.value for header in data.payload.headers}
                if parseaddr(headers.get("from", ""))[1].casefold() != address.casefold():
                    return None
                received = datetime.fromtimestamp(data.internalDate / 1000, UTC)
                if received < since:
                    return None
                return InboxMessage(
                    id=data.id,
                    subject=headers.get("subject", "Ohne Betreff")[:2000],
                    sender=address,
                    preview=unescape(data.snippet),
                    received_at=received,
                )

            messages = await asyncio.gather(
                *(fetch(value) for value in ids if isinstance(value, str))
            )
            return InboxRead(
                provider=provider,
                limited=bool(listed.get("nextPageToken")) or len(raw_ids) > 20,
                messages=sorted(
                    (item for item in messages if item is not None),
                    key=lambda item: item.received_at,
                    reverse=True,
                ),
            )
    except (ValidationError, ValueError, OverflowError, TimeoutError) as exc:
        raise providers.IntegrationError(
            "Der Posteingang konnte nicht vollständig gelesen werden. Bitte später erneut versuchen."
        ) from exc


@router.get(
    "/messages/inbox",
    response_model=InboxRead,
    status_code=200,
    summary="Private Nachrichtenvorschau zur ausgewählten Person aus dem eigenen Postfach",
)
async def inbox(
    person_id: uuid.UUID,
    provider: providers.Provider,
    user: Annotated[User, Depends(workspace_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    response: Response,
) -> InboxRead:
    person = await visible_person(db, user, person_id)
    _, token = await active_connection(db, user, provider)
    try:
        result = await mailbox_previews(provider, token, person.email)
    except providers.IntegrationError as exc:
        raise HTTPException(503, str(exc)) from None
    response.headers["Cache-Control"] = "no-store"
    return result
