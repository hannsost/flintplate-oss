from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site

pytest_plugins = ["tests.test_flintplate"]


async def template(client: AsyncClient, site: Site, **changes: object) -> dict:
    payload: dict[str, object] = {
        "name": "Service erfahren",
        "description": "Getränke, Gastkontakt, Einarbeitung neuer Kräfte.",
        "stations": ["service", "bar"],
        "competence": 4,
    }
    payload.update(changes)
    return body(
        await client.post(site.path("/profile-templates"), headers=site.headers, json=payload), 201
    )


async def profile(client: AsyncClient, site: Site, worker_id: str) -> dict:
    rows = body(await client.get(site.path("/staff-profiles"), headers=site.headers))
    return next(row for row in rows if row["worker_id"] == worker_id)


async def assign(client: AsyncClient, site: Site, worker_id: str, **payload: object) -> dict:
    return body(
        await client.put(
            site.path(f"/staff-profiles/{worker_id}"), headers=site.headers, json=payload
        )
    )


@pytest.mark.asyncio
async def test_template_names_stay_unique_per_venue(client: AsyncClient, site: Site) -> None:
    first = await template(client, site)
    assert first["members"] == 0

    duplicate = await client.post(
        site.path("/profile-templates"),
        headers=site.headers,
        json={"name": "Service erfahren", "stations": ["service"], "competence": 2},
    )

    assert duplicate.status_code == 409


@pytest.mark.asyncio
async def test_assigned_profile_inherits_and_shows_its_origin(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    row = await template(client, site)
    worker = str(hr_workspace.worker.id)

    await assign(client, site, worker, template_id=row["id"])
    result = await profile(client, site, worker)

    assert result["stations"] == ["bar", "service"]
    assert result["competence"] == 4
    assert result["stations_source"] == "Vorlage"
    assert result["competence_source"] == "Vorlage"
    assert result["template_name"] == "Service erfahren"


@pytest.mark.asyncio
async def test_inherited_values_reach_the_existing_qualification_view(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    row = await template(client, site)
    worker = str(hr_workspace.worker.id)
    await assign(client, site, worker, template_id=row["id"])

    skills = body(await client.get(site.path("/staff-skills"), headers=site.headers))

    entry = next(item for item in skills if item["user_id"] == worker)
    assert entry["stations"] == ["bar", "service"]
    assert entry["competence"] == 4


@pytest.mark.asyncio
async def test_preview_names_every_change_before_anything_is_written(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    row = await template(client, site)
    worker = str(hr_workspace.worker.id)
    await assign(client, site, worker, template_id=row["id"])

    preview = body(
        await client.post(
            site.path(f"/profile-templates/{row['id']}/impact"),
            headers=site.headers,
            json={"name": row["name"], "stations": ["kitchen"], "competence": 2},
        )
    )

    fields = {change["field"] for change in preview["changes"]}
    assert fields == {"stations", "competence"}
    assert preview["affected_members"] == 1
    assert preview["shielded"] == []
    competence = next(c for c in preview["changes"] if c["field"] == "competence")
    assert (competence["before"], competence["after"]) == (4, 2)
    # Nothing is written by a preview.
    assert (await profile(client, site, worker))["competence"] == 4


@pytest.mark.asyncio
async def test_an_override_shields_the_person_from_later_template_changes(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    row = await template(client, site)
    worker = str(hr_workspace.worker.id)
    await assign(client, site, worker, template_id=row["id"])
    await assign(
        client, site, worker, template_id=row["id"], overrides=["competence"], competence=5
    )

    preview = body(
        await client.post(
            site.path(f"/profile-templates/{row['id']}/impact"),
            headers=site.headers,
            json={"name": row["name"], "stations": ["kitchen"], "competence": 1},
        )
    )
    assert preview["shielded"][0]["fields"] == ["competence"]

    body(
        await client.put(
            site.path(f"/profile-templates/{row['id']}"),
            headers=site.headers,
            json={
                "name": row["name"],
                "stations": ["kitchen"],
                "competence": 1,
                "version": row["version"],
            },
        )
    )
    result = await profile(client, site, worker)

    assert result["competence"] == 5
    assert result["competence_source"] == "eigen"
    assert result["stations"] == ["kitchen"]
    assert result["stations_source"] == "Vorlage"


@pytest.mark.asyncio
async def test_clearing_an_override_lets_the_field_follow_again(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    row = await template(client, site)
    worker = str(hr_workspace.worker.id)
    await assign(
        client, site, worker, template_id=row["id"], overrides=["competence"], competence=2
    )

    result = await assign(client, site, worker, template_id=row["id"], overrides=[])

    assert result["competence"] == 4
    assert result["competence_source"] == "Vorlage"


@pytest.mark.asyncio
async def test_unlinking_keeps_the_values_the_person_last_had(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    row = await template(client, site)
    worker = str(hr_workspace.worker.id)
    await assign(client, site, worker, template_id=row["id"])

    result = await assign(client, site, worker, template_id=None)

    assert result["template_id"] is None
    assert result["competence"] == 4
    assert result["competence_source"] == "eigen"


@pytest.mark.asyncio
async def test_copying_a_person_leaves_role_and_voluntary_opt_in_alone(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    row = await template(client, site)
    worker = str(hr_workspace.worker.id)
    manager = str(hr_workspace.hr.id)
    await assign(
        client, site, worker, template_id=row["id"], overrides=["stations"], stations=["kitchen"]
    )
    before = await profile(client, site, manager)

    result = body(
        await client.post(
            site.path(f"/staff-profiles/{manager}/copy-from"),
            headers=site.headers,
            json={"source_worker_id": worker},
        )
    )

    assert result["stations"] == ["kitchen"]
    assert result["competence"] == 4
    assert result["template_name"] == "Service erfahren"
    assert result["stations_source"] == "eigen"
    assert result["role"] == before["role"] == "manager"
    assert result["emergency_opt_in"] == before["emergency_opt_in"]


@pytest.mark.asyncio
async def test_copying_onto_the_same_person_is_refused(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    worker = str(hr_workspace.worker.id)

    response = await client.post(
        site.path(f"/staff-profiles/{worker}/copy-from"),
        headers=site.headers,
        json={"source_worker_id": worker},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_a_template_in_use_cannot_be_deleted(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    row = await template(client, site)
    worker = str(hr_workspace.worker.id)
    await assign(client, site, worker, template_id=row["id"])

    blocked = await client.delete(
        site.path(f"/profile-templates/{row['id']}"), headers=site.headers
    )
    assert blocked.status_code == 409

    await assign(client, site, worker, template_id=None)
    freed = await client.delete(site.path(f"/profile-templates/{row['id']}"), headers=site.headers)
    assert freed.status_code == 204


@pytest.mark.asyncio
async def test_a_stale_template_version_is_rejected(client: AsyncClient, site: Site) -> None:
    row = await template(client, site)

    response = await client.put(
        site.path(f"/profile-templates/{row['id']}"),
        headers=site.headers,
        json={"name": row["name"], "stations": ["bar"], "competence": 3, "version": 99},
    )

    assert response.status_code == 409
