from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro.models import EmergencyOffer, Membership, Shift
from app.security import create_access_token
from app.users.models import User
from app.worker.models import ALL_MODULES, WorkerSettings
from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site
from tests.utils import auth_headers

pytest_plugins = ["tests.test_flintplate"]


async def setup_request(
    client: AsyncClient, site: Site, db: AsyncSession, workspace: HRWorkspace, mode: str
) -> tuple[dict, list[dict[str, str]], list[str]]:
    start = (datetime.now(UTC) + timedelta(days=14)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    end = start + timedelta(hours=6)
    shift = body(
        await client.post(
            site.path("/shifts"),
            headers=site.headers,
            json={
                "worker_id": str(workspace.worker.id),
                "station": "Küche",
                "starts_at": start.isoformat(),
                "ends_at": end.isoformat(),
                "break_minutes": 30,
            },
        ),
        201,
    )
    body(
        await client.post(
            site.path(f"/shifts/{shift['id']}/status"),
            headers=site.headers,
            json={"version": shift["version"], "status": "published"},
        )
    )
    headers, ids = [], []
    for index in range(2):
        worker = User(
            email=f"replacement-{uuid.uuid4().hex}@example.com",
            hashed_password="unused",
            full_name=f"Replacement {index}",
            role="worker",
            tenant_id=workspace.hr.tenant_id,
        )
        db.add(worker)
        await db.flush()
        db.add_all(
            [
                WorkerSettings(
                    user_id=worker.id,
                    tenant_id=worker.tenant_id,
                    is_active=True,
                    date_of_birth=date(1990, 1, 1),
                    max_weekly_hours=40,
                    active_modules=dict(ALL_MODULES),
                ),
                Membership(
                    venue_id=uuid.UUID(site.venue_id),
                    user_id=worker.id,
                    role="kitchen",
                    stations=["kitchen"],
                    competence=5 - index,
                    emergency_opt_in=True,
                ),
            ]
        )
        await db.flush()
        credential = auth_headers(create_access_token({"sub": worker.email}))
        headers.append(credential)
        ids.append(str(worker.id))
        body(
            await client.post(
                site.path("/my-availability"),
                headers=credential,
                json={"starts_at": start.isoformat(), "ends_at": end.isoformat()},
            ),
            201,
        )
    return (
        {
            "request_key": str(uuid.uuid4()),
            "shift_id": shift["id"],
            "mode": mode,
            "reason": "Synthetic absence",
            "timeout_minutes": 1,
        },
        headers,
        ids,
    )


@pytest.mark.asyncio
async def test_sequential_decline_then_atomic_replacement(
    client: AsyncClient, site: Site, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    request, headers, ids = await setup_request(
        client, site, db_session, hr_workspace, "sequential"
    )
    ranked = body(
        await client.post(site.path("/emergency-preview"), headers=site.headers, json=request)
    )
    assert [r["worker_id"] for r in ranked] == ids
    assert all(r["eligible"] for r in ranked)
    assert (
        await client.post(site.path("/emergency-preview"), headers=headers[0], json=request)
    ).status_code == 403
    search = body(
        await client.post(site.path("/emergencies"), headers=site.headers, json=request), 201
    )
    assert (
        body(await client.post(site.path("/emergencies"), headers=site.headers, json=request), 201)[
            "id"
        ]
        == search["id"]
    )
    first = body(await client.get(site.path("/my-replacement-offers"), headers=headers[0]))
    assert len(first) == 1
    assert body(await client.get(site.path("/my-replacement-offers"), headers=headers[1])) == []
    body(
        await client.post(
            site.path(f"/my-replacement-offers/{first[0]['id']}"),
            headers=headers[0],
            json={"accept": False},
        )
    )
    second = body(await client.get(site.path("/my-replacement-offers"), headers=headers[1]))
    assert len(second) == 1
    path = site.path(f"/my-replacement-offers/{second[0]['id']}")
    body(await client.post(path, headers=headers[1], json={"accept": True}))
    body(await client.post(path, headers=headers[1], json={"accept": True}))
    final = body(await client.get(site.path("/emergencies"), headers=site.headers))[0]
    assert final["status"] == "filled"
    original = (
        await db_session.execute(select(Shift).where(Shift.id == uuid.UUID(request["shift_id"])))
    ).scalar_one()
    assert original.status == "cancelled"
    replacement = (
        await db_session.execute(
            select(Shift).where(Shift.id == uuid.UUID(final["replacement_shift_id"]))
        )
    ).scalar_one()
    assert str(replacement.worker_id) == ids[1] and replacement.status == "published"


@pytest.mark.asyncio
async def test_broadcast_rechecks_qualification_and_closes_other_offer(
    client: AsyncClient, site: Site, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    request, headers, ids = await setup_request(client, site, db_session, hr_workspace, "broadcast")
    body(await client.post(site.path("/emergencies"), headers=site.headers, json=request), 201)
    offers = [
        body(await client.get(site.path("/my-replacement-offers"), headers=h))[0] for h in headers
    ]
    body(
        await client.put(
            site.path(f"/staff-skills/{ids[0]}"),
            headers=site.headers,
            json={"stations": ["service"], "competence": 5},
        )
    )
    assert (
        await client.post(
            site.path(f"/my-replacement-offers/{offers[0]['id']}"),
            headers=headers[0],
            json={"accept": True},
        )
    ).status_code == 409
    body(
        await client.post(
            site.path(f"/my-replacement-offers/{offers[1]['id']}"),
            headers=headers[1],
            json={"accept": True},
        )
    )
    assert (
        await client.post(
            site.path(f"/my-replacement-offers/{offers[0]['id']}"),
            headers=headers[0],
            json={"accept": True},
        )
    ).status_code == 409
    assert body(await client.get(site.path("/my-replacement-offers"), headers=headers[0])) == []


@pytest.mark.asyncio
async def test_expiry_advances_and_opt_out_excludes_candidates(
    client: AsyncClient, site: Site, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    request, headers, ids = await setup_request(
        client, site, db_session, hr_workspace, "sequential"
    )
    body(
        await client.put(
            site.path("/my-emergency-opt-in"), headers=headers[0], json={"enabled": False}
        )
    )
    ranked = body(
        await client.post(site.path("/emergency-preview"), headers=site.headers, json=request)
    )
    assert not next(r for r in ranked if r["worker_id"] == ids[0])["eligible"]
    body(
        await client.put(
            site.path("/my-emergency-opt-in"), headers=headers[0], json={"enabled": True}
        )
    )
    body(await client.post(site.path("/emergencies"), headers=site.headers, json=request), 201)
    offer = (
        await db_session.execute(
            select(EmergencyOffer).where(EmergencyOffer.worker_id == uuid.UUID(ids[0]))
        )
    ).scalar_one()
    offer.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()
    body(await client.get(site.path("/emergencies"), headers=site.headers))
    assert body(await client.get(site.path("/my-replacement-offers"), headers=headers[0])) == []
    assert len(body(await client.get(site.path("/my-replacement-offers"), headers=headers[1]))) == 1
