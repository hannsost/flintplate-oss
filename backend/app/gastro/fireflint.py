from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from sqlalchemy import select

from app.config import get_settings
from app.gastro import service as svc
from app.gastro.models import FireFlintLink, Venue
from app.gastro.router import DB, Actor, private_response
from app.gastro.schemas import FireFlintInput, FireFlintRead, MenuPublic, VersionInput

router = APIRouter(dependencies=[Depends(private_response)])


class MenuSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    source_system: Literal["flintplate"] = "flintplate"
    venue_id: uuid.UUID
    menu_id: uuid.UUID
    menu_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    currency: Literal["EUR"] = "EUR"
    timezone: str
    published_at: datetime
    items: list[MenuPublic]


class LinkInput(FireFlintInput):
    access_token: SecretStr = Field(min_length=10, max_length=16000)
    refresh_token: SecretStr | None = Field(default=None, min_length=10, max_length=16000)


class RemoteContent(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    revision: int = Field(ge=1)
    status: str
    data: MenuSnapshot


class RefreshResponse(BaseModel):
    access_token: str = Field(min_length=10, max_length=16000)


def cipher() -> Fernet:
    key = get_settings().flintplate_connector_key
    if not key:
        raise HTTPException(
            503, "Der Connector-Schlüssel ist serverseitig noch nicht eingerichtet."
        )
    try:
        return Fernet(key.encode())
    except ValueError as exc:
        raise HTTPException(503, "Der Connector-Schlüssel ist ungültig konfiguriert.") from exc


def server_url() -> str:
    settings = get_settings()
    value = settings.fireflint_base_url.rstrip("/")
    parsed = urlsplit(value)
    if (
        not value
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not parsed.hostname
    ):
        raise HTTPException(503, "Die FireFlint-Serveradresse ist noch nicht korrekt eingerichtet.")
    if parsed.scheme != "https" and not (
        settings.app_env in {"development", "test"} and parsed.scheme == "http"
    ):
        raise HTTPException(503, "FireFlint benötigt eine HTTPS-Serveradresse.")
    # This is an operator-provisioned URL, never a URL supplied by a tenant/client.
    return value


async def snapshot(db: DB, venue: Venue) -> MenuSnapshot:
    # Stable ASCII SKU order, independent of the database collation.
    items = sorted(await svc.catalog(db, venue.id), key=lambda item: item.sku)
    canonical = json.dumps(
        [i.model_dump(mode="json") for i in items], sort_keys=True, separators=(",", ":")
    )
    return MenuSnapshot(
        venue_id=venue.id,
        menu_id=venue.id,
        menu_revision=hashlib.sha256(canonical.encode()).hexdigest(),
        timezone=venue.timezone,
        published_at=datetime.now(UTC),
        items=items,
    )


async def get_link(db: DB, venue_id: uuid.UUID, *, lock: bool = False) -> FireFlintLink | None:
    query = (
        select(FireFlintLink)
        .where(FireFlintLink.venue_id == venue_id)
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    return (await db.execute(query)).scalar_one_or_none()


@router.get(
    "/venues/{venue_id}/fireflint",
    response_model=FireFlintRead | None,
    status_code=200,
    summary="FireFlint-Verbindungsstand ohne Credentials",
)
async def link_status(venue_id: uuid.UUID, user: Actor, db: DB) -> FireFlintLink | None:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    return await get_link(db, venue_id)


@router.get(
    "/venues/{venue_id}/fireflint/snapshot",
    response_model=MenuSnapshot,
    status_code=200,
    summary="Validierter öffentlicher Karten-Snapshot v1",
)
async def export_snapshot(venue_id: uuid.UUID, user: Actor, db: DB) -> MenuSnapshot:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    return await snapshot(db, venue)


@router.put(
    "/venues/{venue_id}/fireflint",
    response_model=FireFlintRead,
    status_code=200,
    summary="Vorbereitetes FireFlint-Objekt und verschlüsselte Konto-Session zuordnen",
)
async def configure(venue_id: uuid.UUID, data: LinkInput, user: Actor, db: DB) -> FireFlintLink:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    server_url()
    encryptor = cipher()
    link = await get_link(db, venue_id, lock=True)
    if link:
        svc.check_version(link.version, data.version)
        link.version += 1
    else:
        if data.version != 0:
            raise HTTPException(409, "Verbindung existiert noch nicht.")
        link = FireFlintLink(venue_id=venue_id)
        db.add(link)
    for field in ("org_id", "content_id", "type_key", "expected_revision"):
        setattr(link, field, getattr(data, field))
    link.access_ciphertext = encryptor.encrypt(
        data.access_token.get_secret_value().encode()
    ).decode()
    link.refresh_ciphertext = (
        encryptor.encrypt(data.refresh_token.get_secret_value().encode()).decode()
        if data.refresh_token
        else None
    )
    link.status = "configured"
    link.last_error = None
    link.snapshot_data = None
    await db.flush()
    svc.event(
        db,
        venue_id,
        "fireflint.configured",
        link.id,
        {
            "org_id": str(link.org_id),
            "content_id": str(link.content_id),
            "expected_revision": link.expected_revision,
        },
        user.id,
    )
    return link


async def transfer(
    db: DB, venue: Venue, link: FireFlintLink, *, publish: bool, actor_id: uuid.UUID
) -> FireFlintLink:
    base = server_url()
    encryptor = cipher()
    if not link.access_ciphertext:
        raise HTTPException(422, "Bitte zuerst eine berechtigte FireFlint-Session hinterlegen.")
    if link.status in {"uncertain", "conflict"}:
        raise HTTPException(
            409,
            "Den FireFlint-Stand zuerst bewusst abgleichen und die Verbindung mit geprüfter Revision neu konfigurieren.",
        )
    if publish and (link.status != "draft_synced" or not link.snapshot_data):
        raise HTTPException(409, "Zuerst einen geprüften Kartenentwurf übertragen.")
    data = MenuSnapshot.model_validate(link.snapshot_data) if publish else await snapshot(db, venue)
    payload = data.model_dump(mode="json")
    endpoint = f"/api/orgs/{link.org_id}/content/{link.type_key}/{link.content_id}" + (
        "/publish" if publish else ""
    )
    body = (
        {"expected_revision": link.expected_revision}
        if publish
        else {"expected_revision": link.expected_revision, "data": payload}
    )
    try:
        token = encryptor.decrypt(link.access_ciphertext.encode()).decode()
        async with httpx.AsyncClient(
            base_url=base, timeout=15, follow_redirects=False, trust_env=False
        ) as client:
            result = await client.request(
                "POST" if publish else "PUT",
                endpoint,
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
            if result.status_code == 401 and link.refresh_ciphertext:
                refreshed = await client.post(
                    "/auth/refresh",
                    json={
                        "refresh_token": encryptor.decrypt(
                            link.refresh_ciphertext.encode()
                        ).decode()
                    },
                )
                if refreshed.status_code == 200:
                    token = RefreshResponse.model_validate(refreshed.json()).access_token
                    link.access_ciphertext = encryptor.encrypt(token.encode()).decode()
                    # A 401 from this API is rejected by auth before the write. Only this
                    # case is retried, once; stale revision or unknown outcomes never are.
                    result = await client.request(
                        "POST" if publish else "PUT",
                        endpoint,
                        json=body,
                        headers={"Authorization": f"Bearer {token}"},
                    )
            if result.status_code in {409, 428}:
                link.status = "conflict"
                link.last_error = "FireFlint-Revision geändert. Entwurf erhalten; bewusster Abgleich erforderlich."
            elif result.status_code in {401, 403}:
                link.status = "authentication_required"
                link.last_error = (
                    "FireFlint-Session oder Membership reicht nicht aus. Integrationskonto prüfen."
                )
            elif result.status_code != 200:
                link.status = "uncertain" if result.status_code >= 500 else "rejected"
                link.last_error = (
                    f"FireFlint meldet HTTP {result.status_code}. Keine automatische Wiederholung."
                )
            else:
                remote = RemoteContent.model_validate(result.json())
                if (
                    remote.id != link.content_id
                    or remote.org_id != link.org_id
                    or remote.data.model_dump(mode="json") != payload
                ):
                    link.status = "uncertain"
                    link.last_error = (
                        "FireFlint-Antwort entspricht nicht dem übertragenen Objekt. Bitte prüfen."
                    )
                elif publish and remote.status != "published":
                    link.status = "uncertain"
                    link.last_error = "FireFlint hat den Veröffentlichungsstatus nicht bestätigt."
                else:
                    link.expected_revision = remote.revision
                    link.status = "published" if publish else "draft_synced"
                    link.snapshot_data = payload
                    link.last_synced_at = datetime.now(UTC)
                    link.last_error = None
    except (httpx.RequestError, ValidationError, ValueError, InvalidToken):
        link.status = "uncertain"
        link.last_error = "Übertragung oder Antwort unklar. Lokalen und FireFlint-Stand abgleichen; keine automatische Wiederholung."
    link.version += 1
    svc.event(
        db,
        venue.id,
        "fireflint.transfer_finished",
        link.id,
        {
            "status": link.status,
            "publish": publish,
            "remote_revision": link.expected_revision,
            "menu_revision": data.menu_revision,
        },
        actor_id,
    )
    await db.flush()
    # Returning the persisted state keeps failure evidence. Raising after mutation
    # would cause get_db to roll back the conflict/uncertain marker.
    return link


@router.post(
    "/venues/{venue_id}/fireflint/sync",
    response_model=FireFlintRead,
    status_code=200,
    summary="Karte als versionsgeprüften FireFlint-Entwurf übertragen",
)
async def sync(venue_id: uuid.UUID, data: VersionInput, user: Actor, db: DB) -> FireFlintLink:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    link = await get_link(db, venue_id, lock=True)
    if link is None:
        raise HTTPException(404, "Verbindung fehlt.")
    svc.check_version(link.version, data.version)
    return await transfer(db, venue, link, publish=False, actor_id=user.id)


@router.post(
    "/venues/{venue_id}/fireflint/publish",
    response_model=FireFlintRead,
    status_code=200,
    summary="Den bereits übertragenen FireFlint-Stand ausdrücklich veröffentlichen",
)
async def publish(venue_id: uuid.UUID, data: VersionInput, user: Actor, db: DB) -> FireFlintLink:
    venue, _ = await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    link = await get_link(db, venue_id, lock=True)
    if link is None:
        raise HTTPException(404, "Verbindung fehlt.")
    svc.check_version(link.version, data.version)
    return await transfer(db, venue, link, publish=True, actor_id=user.id)
