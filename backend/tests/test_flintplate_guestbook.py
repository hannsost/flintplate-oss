from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro.models import Event, GuestNote
from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site

pytest_plugins = ["tests.test_flintplate"]


async def profile(client: AsyncClient, site: Site, **changes: object) -> dict:
    payload: dict[str, object] = {
        "display_name": "Familie Sommer",
        "reference": "Stammtisch Freitag",
    }
    payload.update(changes)
    return body(await client.post(site.path("/guestbook"), headers=site.headers, json=payload), 201)


async def note(client: AsyncClient, site: Site, profile_id: str, **changes: object) -> dict:
    payload: dict[str, object] = {"text": "Sitzt am liebsten am Fenster.", "category": "vorliebe"}
    payload.update(changes)
    return body(
        await client.post(
            site.path(f"/guestbook/{profile_id}/notes"), headers=site.headers, json=payload
        ),
        201,
    )


@pytest.mark.asyncio
async def test_a_profile_is_searchable_by_name_and_reference(
    client: AsyncClient, site: Site
) -> None:
    created = await profile(client, site)
    await profile(client, site, display_name="Herr Wagner", reference="kommt mittwochs")

    found = body(await client.get(site.path("/guestbook?query=stammtisch"), headers=site.headers))

    assert [row["id"] for row in found] == [created["id"]]
    assert found[0]["consent_special"] is False


@pytest.mark.asyncio
async def test_a_birth_year_is_refused(client: AsyncClient, site: Site) -> None:
    response = await client.post(
        site.path("/guestbook"),
        headers=site.headers,
        json={"display_name": "Herr Wagner", "birthday": "04.05.1979"},
    )

    assert response.status_code == 422

    accepted = await profile(client, site, display_name="Frau Wagner", birthday="04.05")
    assert accepted["birthday"] == "04.05"


@pytest.mark.asyncio
async def test_health_notes_need_recorded_consent(client: AsyncClient, site: Site) -> None:
    person = await profile(client, site)

    refused = await client.post(
        site.path(f"/guestbook/{person['id']}/notes"),
        headers=site.headers,
        json={"text": "Erdnussallergie.", "category": "gesundheit"},
    )
    assert refused.status_code == 409
    assert "Einwilligung" in refused.json()["detail"]

    granted = body(
        await client.put(
            site.path(f"/guestbook/{person['id']}/consent"),
            headers=site.headers,
            json={"version": person["version"], "granted": True},
        )
    )
    assert granted["consent_at"]

    allowed = await note(client, site, person["id"], text="Erdnussallergie.", category="gesundheit")
    assert allowed["sensitive"] is True


@pytest.mark.asyncio
async def test_revoking_consent_removes_exactly_those_notes(
    client: AsyncClient, site: Site
) -> None:
    person = await profile(client, site)
    granted = body(
        await client.put(
            site.path(f"/guestbook/{person['id']}/consent"),
            headers=site.headers,
            json={"version": person["version"], "granted": True},
        )
    )
    await note(client, site, person["id"], text="Erdnussallergie.", category="gesundheit")
    await note(client, site, person["id"])

    body(
        await client.put(
            site.path(f"/guestbook/{person['id']}/consent"),
            headers=site.headers,
            json={"version": granted["version"], "granted": False},
        )
    )

    detail = body(await client.get(site.path(f"/guestbook/{person['id']}"), headers=site.headers))
    assert [entry["category"] for entry in detail["entries"]] == ["vorliebe"]
    assert detail["consent_special"] is False
    assert detail["consent_at"] is None


@pytest.mark.asyncio
async def test_a_personal_note_stays_with_its_author_but_appears_in_the_export(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    person = await profile(client, site)
    await note(client, site, person["id"], text="Hat vom Umzug erzählt.", visibility="private")
    await note(client, site, person["id"], text="Mag stilles Wasser.", visibility="team")

    mine = body(await client.get(site.path(f"/guestbook/{person['id']}"), headers=site.headers))
    assert len(mine["entries"]) == 2

    colleague = hr_workspace.headers("worker")
    theirs = body(await client.get(site.path(f"/guestbook/{person['id']}"), headers=colleague))
    assert [entry["text"] for entry in theirs["entries"]] == ["Mag stilles Wasser."]

    export = body(
        await client.get(site.path(f"/guestbook/{person['id']}/export"), headers=site.headers)
    )
    assert len(export["entries"]) == 2
    assert "persönlich" in export["hint"]


@pytest.mark.asyncio
async def test_only_the_author_or_the_management_deletes_a_note(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    person = await profile(client, site)
    colleague = hr_workspace.headers("worker")
    theirs = body(
        await client.post(
            site.path(f"/guestbook/{person['id']}/notes"),
            headers=colleague,
            json={"text": "Kommt gern früh.", "category": "hinweis"},
        ),
        201,
    )

    # The service colleague may not remove a note that is not theirs.
    mine = await note(client, site, person["id"])
    refused = await client.delete(
        site.path(f"/guestbook/{person['id']}/notes/{mine['id']}"), headers=colleague
    )
    assert refused.status_code == 403

    allowed = await client.delete(
        site.path(f"/guestbook/{person['id']}/notes/{theirs['id']}"), headers=site.headers
    )
    assert allowed.status_code == 204


@pytest.mark.asyncio
async def test_expired_notes_disappear_and_can_be_purged(
    client: AsyncClient, site: Site, db_session: AsyncSession
) -> None:
    person = await profile(client, site)
    stale = await note(client, site, person["id"], text="Alte Notiz.")
    await db_session.execute(
        update(GuestNote)
        .where(GuestNote.id == uuid.UUID(stale["id"]))
        .values(expires_at=datetime.now(UTC) - timedelta(days=1))
    )

    detail = body(await client.get(site.path(f"/guestbook/{person['id']}"), headers=site.headers))
    assert detail["entries"] == []

    purged = body(await client.post(site.path("/guestbook/purge"), headers=site.headers))
    assert purged["removed"] == 1
    assert (
        await db_session.execute(select(GuestNote).where(GuestNote.id == uuid.UUID(stale["id"])))
    ).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_opening_a_record_is_written_into_the_journal(
    client: AsyncClient, site: Site, db_session: AsyncSession
) -> None:
    person = await profile(client, site)

    body(await client.get(site.path(f"/guestbook/{person['id']}"), headers=site.headers))

    kinds = (
        (
            await db_session.execute(
                select(Event.kind).where(Event.aggregate_id == uuid.UUID(person["id"]))
            )
        )
        .scalars()
        .all()
    )
    assert "guestbook.viewed" in kinds


@pytest.mark.asyncio
async def test_erasing_a_person_takes_the_notes_and_keeps_no_content(
    client: AsyncClient, site: Site, db_session: AsyncSession
) -> None:
    person = await profile(client, site)
    await note(client, site, person["id"], text="Sehr persönlicher Hinweis.")

    assert (
        await client.delete(site.path(f"/guestbook/{person['id']}"), headers=site.headers)
    ).status_code == 204

    assert (
        await client.get(site.path(f"/guestbook/{person['id']}"), headers=site.headers)
    ).status_code == 404
    left = (
        (
            await db_session.execute(
                select(GuestNote).where(GuestNote.profile_id == uuid.UUID(person["id"]))
            )
        )
        .scalars()
        .all()
    )
    assert left == []
    payloads = (
        (
            await db_session.execute(
                select(Event.payload).where(
                    Event.aggregate_id == uuid.UUID(person["id"]), Event.kind == "guestbook.erased"
                )
            )
        )
        .scalars()
        .all()
    )
    assert payloads and "Sehr persönlicher Hinweis" not in str(payloads)


@pytest.mark.asyncio
async def test_retention_is_bounded_and_drives_the_expiry(client: AsyncClient, site: Site) -> None:
    too_short = await client.put(
        site.path("/guestbook-retention"), headers=site.headers, json={"days": 5}
    )
    assert too_short.status_code == 422

    body(
        await client.put(site.path("/guestbook-retention"), headers=site.headers, json={"days": 30})
    )
    person = await profile(client, site)
    entry = await note(client, site, person["id"])

    expires = datetime.fromisoformat(entry["expires_at"])
    assert 29 <= (expires - datetime.now(UTC)).days <= 30
