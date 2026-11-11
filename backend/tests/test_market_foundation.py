"""Public rebranding and supervised tenant processes, including adversarial paths."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Customer
from app.automation.models import ProcessRun
from app.jobs.models import JobPosting
from app.notifications.models import Notification
from tests.hr_support import HRWorkspace, body


async def admin(db: AsyncSession, ws: HRWorkspace) -> None:
    ws.hr.role = "admin"
    await db.flush()


async def job(db: AsyncSession, ws: HRWorkspace) -> JobPosting:
    row = JobPosting(
        title="Lagerfachkraft",
        company="Synthetic GmbH",
        tenant_id=ws.hr.tenant_id,
        owner_id=ws.hr.id,
        source="recruiter",
        publication_status="published",
        published_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=30),
        required_skills=["Stapler"],
        description="Kommissionierung und Wareneingang",
        location="Berlin",
        salary_min=35000,
        salary_max=42000,
    )
    db.add(row)
    await db.flush()
    return row


def definition(*, four_eyes: bool = False, enabled: bool = True) -> dict:
    return {
        "name": "Stelle vorbereiten",
        "four_eyes": four_eyes,
        "enabled": enabled,
        "steps": [
            {"action": "job_check", "title": "Prüfen", "mode": "automatic"},
            {
                "action": "message_draft",
                "title": "Entwurf",
                "text": "Stelle {title} bei {company}",
                "mode": "review",
            },
            {
                "action": "internal_notification",
                "title": "Vorbereitung fertig",
                "text": "{title} vorbereitet",
                "mode": "automatic",
            },
        ],
    }


async def template(client: AsyncClient, ws: HRWorkspace, data: dict | None = None) -> dict:
    return body(
        await client.post("/processes/templates", headers=ws.headers(), json=data or definition()),
        201,
    )


def start_data(j: JobPosting, version: int = 1) -> dict:
    return {"job_id": str(j.id), "request_key": str(uuid.uuid4()), "template_version": version}


@pytest.mark.asyncio
async def test_branding_permissions_versions_and_public_projection(
    client: AsyncClient, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    ws = hr_workspace
    read = body(await client.get("/companies/workspace/branding", headers=ws.headers()))
    data = {
        "version": read["version"],
        "brand_name": "Testmarke",
        "primary_color": "#ffff00",
        "logo_url": "https://example.com/logo.svg",
    }
    assert (
        await client.put("/companies/workspace/branding", headers=ws.headers(), json=data)
    ).status_code == 403
    await admin(db_session, ws)
    saved = body(await client.put("/companies/workspace/branding", headers=ws.headers(), json=data))
    assert saved["version"] == 2 and saved["brand_name"] == "Testmarke"
    assert body(await client.get(f'/public/branding/slug/{saved["slug"]}'))["name"] == "Testmarke"
    assert (
        body(await client.get("/companies/workspace/branding", headers=ws.headers("worker")))[
            "can_manage"
        ]
        is False
    )
    other = body(await client.get("/companies/workspace/branding", headers=ws.headers("other_hr")))
    assert other["brand_name"] is None
    assert (
        await client.put("/companies/workspace/branding", headers=ws.headers(), json=data)
    ).status_code == 409
    for patch in (
        {"logo_url": "javascript:alert(1)"},
        {"logo_url": "https://name:secret@example.com/a"},
        {"primary_color": "red"},
        {"tenant_id": str(ws.other_hr.tenant_id)},
    ):
        assert (
            await client.put(
                "/companies/workspace/branding",
                headers=ws.headers(),
                json={**data, "version": 2, **patch},
            )
        ).status_code == 422
    cleared = body(
        await client.put(
            "/companies/workspace/branding",
            headers=ws.headers(),
            json={**data, "version": 2, "brand_name": None, "logo_url": None},
        )
    )
    assert cleared["brand_name"] is None and cleared["logo_url"] is None


@pytest.mark.asyncio
async def test_public_job_cannot_use_foreign_brand_or_suspended_company(
    client: AsyncClient, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    ws = hr_workspace
    j = await job(db_session, ws)
    a = await db_session.get(Customer, ws.hr.tenant_id)
    b = await db_session.get(Customer, ws.other_hr.tenant_id)
    assert a and b
    assert (await client.get(f"/public/jobs/{j.id}?slug={a.slug}")).status_code == 200
    assert (await client.get(f"/public/jobs/{j.id}?slug={b.slug}")).status_code == 404
    a.status = "suspended"
    await db_session.flush()
    assert (await client.get(f"/public/jobs/{j.id}")).status_code == 404
    assert (
        await client.get("/companies/workspace/branding", headers=ws.headers())
    ).status_code == 403


@pytest.mark.asyncio
async def test_process_roundtrip_stops_at_review_and_is_idempotent(
    client: AsyncClient, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    ws = hr_workspace
    await admin(db_session, ws)
    j = await job(db_session, ws)
    t = await template(client, ws)
    data = start_data(j)
    run = body(
        await client.post(f'/processes/templates/{t["id"]}/runs', headers=ws.headers(), json=data),
        201,
    )
    assert run["status"] == "awaiting_review" and run["cursor"] == 1
    assert len(run["results"]) == 2
    assert run["results"][1]["output"] == "Stelle Lagerfachkraft bei Synthetic GmbH"
    assert not (
        await db_session.scalars(select(Notification).where(Notification.type == "process"))
    ).all()
    duplicate = body(
        await client.post(f'/processes/templates/{t["id"]}/runs', headers=ws.headers(), json=data)
    )
    assert duplicate["id"] == run["id"]
    assert len((await db_session.scalars(select(ProcessRun))).all()) == 1
    reviewed = body(
        await client.post(
            f'/processes/runs/{run["id"]}/review',
            headers=ws.headers(),
            json={"version": run["version"], "decision": "approve", "note": "Stellendaten geprüft"},
        )
    )
    assert reviewed["status"] == "completed" and len(reviewed["results"]) == 3
    notifications = (
        await db_session.scalars(select(Notification).where(Notification.type == "process"))
    ).all()
    assert len(notifications) == 1 and notifications[0].user_id == ws.hr.id
    assert [e["action"] for e in reviewed["events"]] == [
        "started",
        "prepared",
        "prepared",
        "approved",
        "prepared",
        "completed",
    ]
    assert (
        await client.post(
            f'/processes/runs/{run["id"]}/review',
            headers=ws.headers(),
            json={"version": 1, "decision": "approve", "note": "Doppelter Klick"},
        )
    ).status_code == 409
    assert len(body(await client.get("/processes/runs", headers=ws.headers()))) == 1
    assert (
        body(await client.get(f'/processes/runs/{run["id"]}', headers=ws.headers()))["status"]
        == "completed"
    )


@pytest.mark.asyncio
async def test_process_authorization_validation_and_four_eyes(
    client: AsyncClient, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    ws = hr_workspace
    assert (
        await client.post("/processes/templates", headers=ws.headers(), json=definition())
    ).status_code == 403
    await admin(db_session, ws)
    j = await job(db_session, ws)
    for steps in (
        [{"action": "send_email", "title": "Forbidden"}],
        [{"action": "message_draft", "title": "Bypass", "text": "x", "mode": "automatic"}],
        [{"action": "internal_notification", "title": "Empty"}],
        [{"action": "ai_job_brief", "title": "AI"}] * 2,
    ):
        assert (
            await client.post(
                "/processes/templates", headers=ws.headers(), json={**definition(), "steps": steps}
            )
        ).status_code == 422
    t = await template(client, ws, definition(four_eyes=True))
    run = body(
        await client.post(
            f'/processes/templates/{t["id"]}/runs', headers=ws.headers(), json=start_data(j)
        ),
        201,
    )
    review = {"version": 1, "decision": "approve", "note": "Geprüft"}
    assert (
        await client.post(f'/processes/runs/{run["id"]}/review', headers=ws.headers(), json=review)
    ).status_code == 403
    assert (
        await client.get(f'/processes/runs/{run["id"]}', headers=ws.headers("other_hr"))
    ).status_code == 404
    assert (
        await client.get("/processes/templates", headers=ws.headers("worker"))
    ).status_code == 403
    assert body(await client.get("/processes/templates", headers=ws.headers("other_hr"))) == []
    assert (
        await client.put(
            f'/processes/templates/{t["id"]}',
            headers=ws.headers("other_hr"),
            json={**definition(), "version": 1},
        )
    ).status_code == 403
    # Second HR account in the SAME tenant can review. Foreign HR cannot.
    ws.other_hr.tenant_id = ws.hr.tenant_id
    await db_session.flush()
    assert (
        body(
            await client.post(
                f'/processes/runs/{run["id"]}/review', headers=ws.headers("other_hr"), json=review
            )
        )["status"]
        == "completed"
    )


@pytest.mark.asyncio
async def test_process_pause_stale_sources_and_request_collision(
    client: AsyncClient, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    ws = hr_workspace
    await admin(db_session, ws)
    j = await job(db_session, ws)
    t = await template(client, ws)
    payload = start_data(j)
    run = body(
        await client.post(
            f'/processes/templates/{t["id"]}/runs', headers=ws.headers(), json=payload
        ),
        201,
    )
    assert (
        await client.post(
            f'/processes/templates/{t["id"]}/runs',
            headers=ws.headers(),
            json={**payload, "authorize_ai": True},
        )
    ).status_code == 409
    paused = body(
        await client.put(
            f'/processes/templates/{t["id"]}',
            headers=ws.headers(),
            json={**definition(enabled=False), "version": 1},
        )
    )
    assert paused["version"] == 2
    assert (
        await client.put(
            f'/processes/templates/{t["id"]}',
            headers=ws.headers(),
            json={**definition(), "version": 1},
        )
    ).status_code == 409
    review = {"version": 1, "decision": "approve", "note": "Geprüft"}
    assert (
        await client.post(f'/processes/runs/{run["id"]}/review', headers=ws.headers(), json=review)
    ).status_code == 409
    assert (
        await client.post(
            f'/processes/templates/{t["id"]}/runs', headers=ws.headers(), json=start_data(j, 2)
        )
    ).status_code == 409
    await client.put(
        f'/processes/templates/{t["id"]}', headers=ws.headers(), json={**definition(), "version": 2}
    )
    j.title = "Geänderte Stelle"
    await db_session.flush()
    assert (
        await client.post(f'/processes/runs/{run["id"]}/review', headers=ws.headers(), json=review)
    ).status_code == 409
    cancelled = body(
        await client.post(
            f'/processes/runs/{run["id"]}/review',
            headers=ws.headers(),
            json={**review, "decision": "cancel"},
        )
    )
    assert cancelled["status"] == "cancelled"
    denied = await client.post(
        f'/processes/templates/{t["id"]}/runs',
        headers=ws.headers("other_hr"),
        json=start_data(j, 3),
    )
    assert denied.status_code == 404


@pytest.mark.asyncio
async def test_process_foreign_job_and_rejection(
    client: AsyncClient, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    ws = hr_workspace
    await admin(db_session, ws)
    j = await job(db_session, ws)
    t = await template(client, ws)
    j.tenant_id = ws.other_hr.tenant_id
    await db_session.flush()
    assert (
        await client.post(
            f'/processes/templates/{t["id"]}/runs', headers=ws.headers(), json=start_data(j)
        )
    ).status_code == 404
    j.tenant_id = ws.hr.tenant_id
    await db_session.flush()
    run = body(
        await client.post(
            f'/processes/templates/{t["id"]}/runs', headers=ws.headers(), json=start_data(j)
        ),
        201,
    )
    result = body(
        await client.post(
            f'/processes/runs/{run["id"]}/review',
            headers=ws.headers(),
            json={"version": 1, "decision": "reject", "note": "Entwurf bitte überarbeiten"},
        )
    )
    assert result["status"] == "rejected" and result["results"][-1]["status"] == "rejected"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["missing", "working", "empty", "timeout", "no_consent"])
async def test_ai_step_truthful_provider_states(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> None:
    ws = hr_workspace
    await admin(db_session, ws)
    j = await job(db_session, ws)
    llm = SimpleNamespace(
        ainvoke=AsyncMock(
            return_value=SimpleNamespace(
                content="Sachliches Stellenbriefing" if provider == "working" else []
            )
        )
    )
    if provider == "timeout":
        llm.ainvoke.side_effect = TimeoutError()
    factory = AsyncMock(return_value=None if provider == "missing" else llm)
    monkeypatch.setattr("app.automation.service.get_llm", factory)
    t = await template(
        client,
        ws,
        {**definition(), "steps": [{"action": "ai_job_brief", "title": "Stellenbriefing"}]},
    )
    run = body(
        await client.post(
            f'/processes/templates/{t["id"]}/runs',
            headers=ws.headers(),
            json={**start_data(j), "authorize_ai": provider != "no_consent"},
        ),
        201,
    )
    if provider == "working":
        assert run["status"] == "awaiting_review" and run["results"][0]["origin"] == "ai"
        assert "candidate" not in str(llm.ainvoke.call_args)
    else:
        assert run["status"] == "blocked" and run["results"] == []
        assert (
            await client.post(
                f'/processes/runs/{run["id"]}/review',
                headers=ws.headers(),
                json={"version": 1, "decision": "approve", "note": "Nicht zulässig"},
            )
        ).status_code == 409
        assert (
            body(
                await client.post(
                    f'/processes/runs/{run["id"]}/review',
                    headers=ws.headers(),
                    json={"version": 1, "decision": "cancel", "note": "Später erneut starten"},
                )
            )["status"]
            == "cancelled"
        )
    if provider == "no_consent":
        factory.assert_not_called()


@pytest.mark.asyncio
async def test_platform_branding_change_invalidates_workspace_version(
    client: AsyncClient, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    from app.security import create_access_token
    from app.users.models import User
    from tests.utils import auth_headers

    ws = hr_workspace
    await admin(db_session, ws)
    platform = User(
        email=f"platform-{uuid.uuid4().hex}@example.com",
        role="admin",
        tenant_id=None,
        hashed_password="fixture",
    )
    db_session.add(platform)
    await db_session.flush()
    headers = auth_headers(create_access_token({"sub": platform.email}))
    response = await client.patch(
        f"/admin/customers/{ws.hr.tenant_id}/branding",
        headers=headers,
        json={"primary_color": "#112233"},
    )
    assert response.status_code == 200, response.text
    current = body(await client.get("/companies/workspace/branding", headers=ws.headers()))
    assert current["version"] == 2 and current["primary_color"] == "#112233"
    assert (
        await client.put(
            "/companies/workspace/branding",
            headers=ws.headers(),
            json={"version": 1, "primary_color": "#ffffff"},
        )
    ).status_code == 409
