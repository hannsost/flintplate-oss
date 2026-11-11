from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro.models import ChatMessage
from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site

pytest_plugins = ["tests.test_flintplate"]


async def channels(client: AsyncClient, site: Site, headers: dict[str, str] | None = None) -> list:
    return body(await client.get(site.path("/chat/channels"), headers=headers or site.headers))


async def say(
    client: AsyncClient, site: Site, channel: str, text: str, headers: dict[str, str] | None = None
) -> dict:
    return body(
        await client.post(
            site.path(f"/chat/channels/{channel}/messages"),
            headers=headers or site.headers,
            json={"text": text},
        ),
        201,
    )


@pytest.mark.asyncio
async def test_the_first_visit_opens_a_team_channel(client: AsyncClient, site: Site) -> None:
    rows = await channels(client, site)

    assert [row["name"] for row in rows] == ["Team"]
    assert rows[0]["unread"] == 0
    assert rows[0]["last_message_at"] is None


@pytest.mark.asyncio
async def test_messages_arrive_in_order_and_belong_to_their_author(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    channel = (await channels(client, site))[0]["id"]
    await say(client, site, channel, "Kaffeemaschine ist wieder da.")
    colleague = hr_workspace.headers("worker")
    await say(client, site, channel, "Danke, gut zu wissen.", colleague)

    mine = body(
        await client.get(site.path(f"/chat/channels/{channel}/messages"), headers=site.headers)
    )

    assert [row["text"] for row in mine] == [
        "Kaffeemaschine ist wieder da.",
        "Danke, gut zu wissen.",
    ]
    assert [row["mine"] for row in mine] == [True, False]
    assert mine[0]["author_name"]


@pytest.mark.asyncio
async def test_unread_counts_only_what_others_wrote(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    channel = (await channels(client, site))[0]["id"]
    colleague = hr_workspace.headers("worker")
    await say(client, site, channel, "Eigene Nachricht zählt nicht.")
    await say(client, site, channel, "Erste fremde.", colleague)
    await say(client, site, channel, "Zweite fremde.", colleague)

    assert (await channels(client, site))[0]["unread"] == 2

    marked = await client.post(site.path(f"/chat/channels/{channel}/read"), headers=site.headers)
    assert marked.status_code == 204
    assert (await channels(client, site))[0]["unread"] == 0

    await say(client, site, channel, "Noch eine.", colleague)
    assert (await channels(client, site))[0]["unread"] == 1


@pytest.mark.asyncio
async def test_only_the_author_or_the_management_deletes(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    channel = (await channels(client, site))[0]["id"]
    colleague = hr_workspace.headers("worker")
    theirs = await say(client, site, channel, "Bitte nicht löschen.", colleague)
    mine = await say(client, site, channel, "Meine eigene.")

    refused = await client.delete(
        site.path(f"/chat/channels/{channel}/messages/{mine['id']}"), headers=colleague
    )
    assert refused.status_code == 403

    own = await client.delete(
        site.path(f"/chat/channels/{channel}/messages/{mine['id']}"), headers=site.headers
    )
    assert own.status_code == 204

    by_manager = await client.delete(
        site.path(f"/chat/channels/{channel}/messages/{theirs['id']}"), headers=site.headers
    )
    assert by_manager.status_code == 204


@pytest.mark.asyncio
async def test_expired_messages_disappear_and_can_be_purged(
    client: AsyncClient, site: Site, db_session: AsyncSession
) -> None:
    channel = (await channels(client, site))[0]["id"]
    stale = await say(client, site, channel, "Von letzter Saison.")
    await say(client, site, channel, "Aktuell.")
    await db_session.execute(
        update(ChatMessage)
        .where(ChatMessage.id == uuid.UUID(stale["id"]))
        .values(expires_at=datetime.now(UTC) - timedelta(days=1))
    )

    visible = body(
        await client.get(site.path(f"/chat/channels/{channel}/messages"), headers=site.headers)
    )
    assert [row["text"] for row in visible] == ["Aktuell."]

    purged = body(await client.post(site.path("/chat/purge"), headers=site.headers))
    assert purged["removed"] == 1
    assert (
        await db_session.execute(
            select(ChatMessage).where(ChatMessage.id == uuid.UUID(stale["id"]))
        )
    ).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_retention_drives_the_expiry_and_stays_bounded(
    client: AsyncClient, site: Site
) -> None:
    too_short = await client.put(
        site.path("/chat-retention"), headers=site.headers, json={"days": 3}
    )
    assert too_short.status_code == 422

    body(await client.put(site.path("/chat-retention"), headers=site.headers, json={"days": 14}))
    channel = (await channels(client, site))[0]["id"]
    message = await say(client, site, channel, "Läuft in zwei Wochen ab.")

    expires = datetime.fromisoformat(message["expires_at"])
    assert 13 <= (expires - datetime.now(UTC)).days <= 14


@pytest.mark.asyncio
async def test_a_second_channel_needs_a_free_name(client: AsyncClient, site: Site) -> None:
    created = body(
        await client.post(
            site.path("/chat/channels"),
            headers=site.headers,
            json={"name": "Küche", "topic": "Absprachen am Pass."},
        ),
        201,
    )
    assert created["name"] == "Küche"

    duplicate = await client.post(
        site.path("/chat/channels"), headers=site.headers, json={"name": "Küche"}
    )
    assert duplicate.status_code == 409
    # The default channel only appears when a venue has none at all.
    assert [row["name"] for row in await channels(client, site)] == ["Küche"]


@pytest.mark.asyncio
async def test_a_stranger_sees_no_channel(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    outsider = hr_workspace.headers("other_worker")

    response = await client.get(site.path("/chat/channels"), headers=outsider)

    assert response.status_code == 404
