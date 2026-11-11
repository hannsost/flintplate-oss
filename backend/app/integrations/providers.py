"""Small, explicit adapters for the official Google and Microsoft APIs.

External errors never include response bodies, headers or credential values.
"""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Literal
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, Field, JsonValue, SecretStr, TypeAdapter, ValidationError

Provider = Literal["google", "microsoft"]
JSON = TypeAdapter(dict[str, JsonValue])


class IntegrationError(Exception):
    """Safe, user-facing failure without remote data or credentials."""


@dataclass(frozen=True)
class ProviderConfig:
    client_id: str
    client_secret: str = field(repr=False)
    redirect_uri: str
    authorization_url: str
    token_url: str
    scopes: str


def cipher() -> Fernet:
    value = os.environ.get("INTEGRATIONS_ENCRYPTION_KEY", "")
    try:
        return Fernet(value.encode())
    except (ValueError, TypeError) as exc:
        raise IntegrationError(
            "Die sichere Speicherung der Verbindungen ist noch nicht eingerichtet."
        ) from exc


def seal(value: str) -> str:
    return cipher().encrypt(value.encode()).decode()


def unseal(value: str) -> str:
    try:
        return cipher().decrypt(value.encode()).decode()
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise IntegrationError("Die Verbindung muss erneut hergestellt werden.") from exc


def configuration(provider: Provider) -> ProviderConfig:
    prefix = "GOOGLE" if provider == "google" else "MICROSOFT"
    client_id = os.environ.get(f"{prefix}_OAUTH_CLIENT_ID", "")
    secret = os.environ.get(f"{prefix}_OAUTH_CLIENT_SECRET", "")
    redirect = os.environ.get("INTEGRATIONS_REDIRECT_URI", "")
    if not client_id or not secret or not redirect:
        raise IntegrationError("Diese Verbindung ist für FlintPlate noch nicht eingerichtet.")
    if not redirect.startswith("https://") and not redirect.startswith("http://localhost:"):
        raise IntegrationError("Die Rücksprungadresse der Verbindung ist ungültig.")
    cipher()
    if provider == "google":
        return ProviderConfig(
            client_id,
            secret,
            redirect,
            "https://accounts.google.com/o/oauth2/v2/auth",
            "https://oauth2.googleapis.com/token",
            "openid email https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/calendar.freebusy https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly",
        )
    return ProviderConfig(
        client_id,
        secret,
        redirect,
        "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "offline_access User.Read Calendars.ReadWrite Mail.Send Mail.Read",
    )


def authorization_url(provider: Provider, state: str, verifier: str) -> str:
    config = configuration(provider)
    query = {
        "client_id": config.client_id,
        "redirect_uri": config.redirect_uri,
        "response_type": "code",
        "scope": config.scopes,
        "state": state,
        "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("="),
        "code_challenge_method": "S256",
        "prompt": "consent",
    }
    if provider == "google":
        query["access_type"] = "offline"
    return config.authorization_url + "?" + urlencode(query)


class Tokens(BaseModel):
    access_token: SecretStr
    refresh_token: SecretStr | None = None
    expires_in: int = Field(default=3600, ge=1, le=86400)
    scope: str = ""


async def exchange(
    provider: Provider,
    *,
    code: str | None = None,
    verifier: str | None = None,
    refresh_token: str | None = None,
) -> Tokens:
    config = configuration(provider)
    data = {"client_id": config.client_id, "client_secret": config.client_secret}
    if refresh_token:
        data.update(grant_type="refresh_token", refresh_token=refresh_token)
    else:
        data.update(
            grant_type="authorization_code",
            code=code or "",
            code_verifier=verifier or "",
            redirect_uri=config.redirect_uri,
        )
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(config.token_url, data=data)
            response.raise_for_status()
            tokens = Tokens.model_validate(response.json())
    except (httpx.HTTPError, ValueError) as exc:
        raise IntegrationError(
            "Anmeldung beim Anbieter fehlgeschlagen. Bitte erneut verbinden."
        ) from exc
    if not refresh_token:
        # A partial OAuth grant cannot silently create a broken connection.
        required = set(config.scopes.split()) - {"openid", "email", "offline_access"}
        granted = {
            scope.removeprefix("https://graph.microsoft.com/") for scope in tokens.scope.split()
        }
        if not required.issubset(granted):
            raise IntegrationError(
                "Bitte die angeforderten E-Mail- und Kalenderrechte beim Anbieter freigeben."
            )
    return tokens


async def api(
    method: str, url: str, token: str, payload: dict[str, JsonValue] | None = None
) -> dict[str, JsonValue]:
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.request(
                method, url, headers={"Authorization": f"Bearer {token}"}, json=payload
            )
            response.raise_for_status()
            if not response.content:
                return {}
            return JSON.validate_python(response.json())
    except (httpx.HTTPError, ValidationError, ValueError) as exc:
        raise IntegrationError(
            "Der Anbieter konnte die Anfrage nicht bestätigen. Bitte die Verbindung und den Anbieter prüfen."
        ) from exc


async def account_email(provider: Provider, token: str) -> str:
    url = (
        "https://openidconnect.googleapis.com/v1/userinfo"
        if provider == "google"
        else "https://graph.microsoft.com/v1.0/me?$select=mail,userPrincipalName"
    )
    result = await api("GET", url, token)
    value = (
        result.get("email")
        if provider == "google"
        else result.get("mail") or result.get("userPrincipalName")
    )
    if (
        not isinstance(value, str)
        or "@" not in value
        or (provider == "google" and result.get("email_verified") is not True)
    ):
        raise IntegrationError("Der Anbieter hat keine bestätigte E-Mail-Adresse zurückgegeben.")
    return value


def mime_message(sender: str, recipient: str, subject: str, body: str) -> bytes:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    return message.as_bytes()


async def send_email(
    provider: Provider, token: str, sender: str, recipient: str, subject: str, body: str
) -> str | None:
    if provider == "google":
        raw = base64.urlsafe_b64encode(mime_message(sender, recipient, subject, body)).decode()
        result = await api(
            "POST",
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            token,
            {"raw": raw},
        )
        value = result.get("id")
        return value if isinstance(value, str) else None
    await api(
        "POST",
        "https://graph.microsoft.com/v1.0/me/sendMail",
        token,
        {
            "message": {
                "subject": subject,
                "body": {"contentType": "Text", "content": body},
                "toRecipients": [{"emailAddress": {"address": recipient}}],
            },
            "saveToSentItems": True,
        },
    )
    return None


async def create_event(
    provider: Provider, token: str, event_id: str, title: str, start: datetime, end: datetime
) -> str:
    # Personal calendar entry only: external invitations require a separate, reviewed email.
    if provider == "google":
        result = await api(
            "POST",
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            token,
            {
                "id": event_id.replace("-", ""),
                "summary": title,
                "start": {"dateTime": start.isoformat()},
                "end": {"dateTime": end.isoformat()},
            },
        )
    else:
        result = await api(
            "POST",
            "https://graph.microsoft.com/v1.0/me/events",
            token,
            {
                "transactionId": event_id,
                "subject": title,
                "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
                "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
            },
        )
    value = result.get("id")
    if not isinstance(value, str):
        raise IntegrationError("Der Anbieter hat den Kalendereintrag nicht bestätigt.")
    return value


async def busy_intervals(
    provider: Provider, token: str, start: datetime, end: datetime
) -> list[tuple[datetime, datetime]]:
    if provider == "google":
        response = await api(
            "POST",
            "https://www.googleapis.com/calendar/v3/freeBusy",
            token,
            {
                "timeMin": start.isoformat(),
                "timeMax": end.isoformat(),
                "items": [{"id": "primary"}],
            },
        )
        calendars = response.get("calendars")
        primary = calendars.get("primary") if isinstance(calendars, dict) else None
        if not isinstance(primary, dict) or primary.get("errors"):
            raise IntegrationError("Die Kalenderverfügbarkeit konnte nicht geprüft werden.")
        intervals = primary.get("busy")
        if not isinstance(intervals, list):
            raise IntegrationError("Der Kalender hat eine ungültige Antwort geliefert.")
        result = []
        for item in intervals:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("start"), str)
                or not isinstance(item.get("end"), str)
            ):
                raise IntegrationError("Der Kalender hat eine ungültige Antwort geliefert.")
            result.append(calendar_interval(item["start"], item["end"]))
        return result
    query = urlencode(
        {
            "startDateTime": start.isoformat(),
            "endDateTime": end.isoformat(),
            "$select": "start,end,showAs",
            "$top": "1000",
        }
    )
    response = await api("GET", "https://graph.microsoft.com/v1.0/me/calendarView?" + query, token)
    if response.get("@odata.nextLink"):
        raise IntegrationError(
            "Bitte einen kleineren Zeitraum für die Verfügbarkeitsprüfung wählen."
        )
    values = response.get("value")
    if not isinstance(values, list):
        raise IntegrationError("Die Kalenderverfügbarkeit konnte nicht geprüft werden.")
    result = []
    for item in values:
        if not isinstance(item, dict):
            raise IntegrationError("Der Kalender hat eine ungültige Antwort geliefert.")
        if item.get("showAs") == "free":
            continue
        begin, finish = item.get("start"), item.get("end")
        if (
            not isinstance(begin, dict)
            or not isinstance(finish, dict)
            or begin.get("timeZone") != "UTC"
            or finish.get("timeZone") != "UTC"
        ):
            raise IntegrationError("Die Zeitzone des Kalenders konnte nicht geprüft werden.")
        result.append(calendar_interval(begin.get("dateTime"), finish.get("dateTime"), utc=True))
    return result


def calendar_interval(
    begin: JsonValue, finish: JsonValue, *, utc: bool = False
) -> tuple[datetime, datetime]:
    """Never interpret incomplete provider data as available time."""
    if not isinstance(begin, str) or not isinstance(finish, str):
        raise IntegrationError("Die Kalenderzeiten konnten nicht geprüft werden.")
    try:
        start, end = datetime.fromisoformat(begin), datetime.fromisoformat(finish)
    except ValueError as exc:
        raise IntegrationError("Die Kalenderzeiten konnten nicht geprüft werden.") from exc
    if utc:
        start = start.replace(tzinfo=UTC) if start.tzinfo is None else start.astimezone(UTC)
        end = end.replace(tzinfo=UTC) if end.tzinfo is None else end.astimezone(UTC)
    if start.utcoffset() is None or end.utcoffset() is None or end <= start:
        raise IntegrationError("Die Kalenderzeiten konnten nicht geprüft werden.")
    return start, end


def event_url(provider: Provider, event_id: str) -> str:
    from urllib.parse import quote

    root = (
        "https://www.googleapis.com/calendar/v3/calendars/primary/events/"
        if provider == "google"
        else "https://graph.microsoft.com/v1.0/me/events/"
    )
    return root + quote(event_id, safe="") + ("?sendUpdates=none" if provider == "google" else "")


async def update_event(
    provider: Provider, token: str, event_id: str, title: str, start: datetime, end: datetime
) -> None:
    payload: dict[str, JsonValue]
    if provider == "google":
        payload = {
            "summary": title,
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": end.isoformat()},
        }
    else:
        payload = {
            "subject": title,
            "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
        }
    await api("PATCH", event_url(provider, event_id), token, payload)


async def delete_event(provider: Provider, token: str, event_id: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.delete(
                event_url(provider, event_id), headers={"Authorization": f"Bearer {token}"}
            )
            if response.status_code not in {404, 410}:
                response.raise_for_status()
    except httpx.HTTPError as exc:
        raise IntegrationError(
            "Die Entfernung des Kalendereintrags konnte nicht bestätigt werden."
        ) from exc
