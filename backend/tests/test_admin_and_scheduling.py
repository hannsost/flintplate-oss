"""Platform administration, tenant boundaries, and employee scheduling."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.observability.models import AITrace
from app.security import create_access_token
from app.users.models import User
from tests.hr_support import HRWorkspace, body
from tests.utils import auth_headers


@pytest.fixture
async def platform_headers(db_session: AsyncSession) -> dict[str, str]:
    user = User(
        email=f"platform-{uuid.uuid4().hex}@example.com",
        hashed_password="unused-fixture",
        role="admin",
    )
    db_session.add(user)
    await db_session.flush()
    return auth_headers(create_access_token({"sub": user.email}))


async def test_platform_customer_and_module_lifecycle(
    client: AsyncClient, platform_headers: dict[str, str]
) -> None:
    headers = platform_headers
    payload = {
        "name": "Synthetic organization",
        "slug": f"synthetic-{uuid.uuid4().hex}",
        "type": "internal_hr",
        "plan": "starter",
        "status": "active",
    }
    customer = body(await client.post("/admin/customers", headers=headers, json=payload), 201)
    path = f'/admin/customers/{customer["id"]}'
    assert (await client.post("/admin/customers", headers=headers, json=payload)).status_code == 409
    assert body(await client.get(path, headers=headers))["name"] == payload["name"]
    assert (
        len(
            (
                await client.get("/admin/customers?status=active&type=internal_hr", headers=headers)
            ).json()
        )
        == 1
    )
    assert (
        body(await client.patch(path, headers=headers, json={"name": "Updated organization"}))[
            "name"
        ]
        == "Updated organization"
    )
    catalogue = (await client.get("/admin/modules", headers=headers)).json()
    key = catalogue[0]["key"]
    module_path = path + f"/modules/{key}"
    module = body(
        await client.put(module_path, headers=headers, json={"enabled": True, "usage_limit": 10})
    )
    assert module["usage_limit"] == 10
    assert (
        body(await client.put(module_path, headers=headers, json={"enabled": False}))["enabled"]
        is False
    )
    assert len((await client.get(path + "/modules", headers=headers)).json()) > 0
    assert (
        await client.put(path + "/modules/unknown", headers=headers, json={"enabled": True})
    ).status_code == 400
    assert body(await client.get("/admin/stats", headers=headers))["total_customers"] == 1
    assert (await client.delete(path, headers=headers)).status_code == 204
    assert body(await client.get(path, headers=headers))["status"] == "churned"


@pytest.mark.parametrize(
    "path", ["/admin/customers", "/admin/stats", "/admin/modules", "/admin/import-runs"]
)
async def test_company_admin_cannot_access_platform_administration(
    client: AsyncClient, db_session: AsyncSession, hr_workspace: HRWorkspace, path: str
) -> None:
    h = hr_workspace
    h.hr.role = "admin"
    await db_session.flush()
    assert (await client.get(path, headers=h.headers())).status_code == 403


@pytest.mark.parametrize(
    "changes", [{"plan": "unlimited"}, {"type": "invalid"}, {"status": "unknown"}, {"name": ""}]
)
async def test_customer_updates_validate_business_values(
    client: AsyncClient, platform_headers: dict[str, str], changes: dict
) -> None:
    headers = platform_headers
    customer = body(
        await client.post(
            "/admin/customers",
            headers=headers,
            json={"name": "Test", "slug": f"test-{uuid.uuid4().hex}"},
        ),
        201,
    )
    assert (
        await client.patch(f'/admin/customers/{customer["id"]}', headers=headers, json=changes)
    ).status_code == 422


async def test_ai_statistics_are_scoped_to_the_requesting_organization(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
    platform_headers: dict[str, str],
) -> None:
    h = hr_workspace
    for user, tokens in [(h.hr, 10), (h.worker, 20), (h.other_hr, 99)]:
        db_session.add(
            AITrace(user_id=user.id, trace_type="synthetic", duration_ms=100, total_tokens=tokens)
        )
    await db_session.flush()
    assert body(await client.get("/ai/traces/stats", headers=h.headers()))["total_tokens"] == 30
    assert (
        body(await client.get("/ai/traces/stats", headers=h.headers("worker")))["total_tokens"]
        == 20
    )
    assert (
        body(await client.get("/ai/traces/stats", headers=platform_headers))["total_tokens"] == 129
    )


@pytest.mark.parametrize("who", ["hr", "worker"])
async def test_billing_access_requires_an_administrator(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, hr_workspace: HRWorkspace, who: str
) -> None:
    checkout = AsyncMock(return_value="https://checkout.stripe.com/synthetic")
    portal = AsyncMock(return_value="https://billing.stripe.com/synthetic")
    monkeypatch.setattr("app.billing.router.create_checkout_session", checkout)
    monkeypatch.setattr("app.billing.router.create_portal_session", portal)
    assert (
        await client.post(
            "/billing/checkout", headers=hr_workspace.headers(who), json={"plan": "professional"}
        )
    ).status_code == 403
    assert (
        await client.get("/billing/portal", headers=hr_workspace.headers(who))
    ).status_code == 403
    checkout.assert_not_called()
    portal.assert_not_called()


async def test_assignment_lifecycle_and_schedule_visibility(
    client: AsyncClient, hr_workspace: HRWorkspace
) -> None:
    h = hr_workspace
    payload = {
        "worker_id": str(h.worker.id),
        "start_date": "2026-09-07",
        "end_date": "2026-09-11",
        "shift_start": "08:00",
        "shift_end": "16:00",
        "customer_company": "Synthetic client",
        "role_description": "Warehouse",
    }
    assignment = body(
        await client.post("/zeitarbeit/assignments", headers=h.headers(), json=payload), 201
    )
    path = f'/zeitarbeit/assignments/{assignment["id"]}'
    assert assignment["shift"] == "08:00 – 16:00"
    assert (
        len(
            (await client.get("/worker/schedule?month=2026-09", headers=h.headers("worker"))).json()
        )
        == 1
    )
    assert (
        await client.get("/worker/schedule?month=2026-10", headers=h.headers("worker"))
    ).json() == []
    assert (await client.get("/worker/schedule", headers=h.headers("other_worker"))).json() == []
    assert (
        len(
            (
                await client.get(
                    "/zeitarbeit/assignments?month=2026-09&status=planned", headers=h.headers()
                )
            ).json()
        )
        == 1
    )
    assert (await client.get(path, headers=h.headers("other_hr"))).status_code == 404
    assert (
        body(await client.patch(path, headers=h.headers(), json={"status": "confirmed"}))["status"]
        == "confirmed"
    )
    assert (
        body(await client.get(f'/worker/schedule/{assignment["id"]}', headers=h.headers("worker")))[
            "status"
        ]
        == "confirmed"
    )
    assert (
        body(
            await client.post(
                "/zeitarbeit/assignments/bulk-status",
                headers=h.headers(),
                json={"assignment_ids": [assignment["id"]], "status": "completed"},
            )
        )["affected"]
        == 1
    )
    assert (await client.delete(path, headers=h.headers())).status_code == 204
    assert (await client.get("/worker/schedule", headers=h.headers("worker"))).json() == []


async def test_assignment_invalid_date_update_does_not_mutate_saved_state(
    client: AsyncClient, hr_workspace: HRWorkspace
) -> None:
    h = hr_workspace
    assignment = body(
        await client.post(
            "/zeitarbeit/assignments",
            headers=h.headers(),
            json={
                "worker_id": str(h.worker.id),
                "start_date": "2026-09-07",
                "end_date": "2026-09-11",
            },
        ),
        201,
    )
    path = f'/zeitarbeit/assignments/{assignment["id"]}'
    assert (
        await client.patch(path, headers=h.headers(), json={"end_date": "2026-09-01"})
    ).status_code == 422
    assert body(await client.get(path, headers=h.headers()))["end_date"] == "2026-09-11"
    assert (
        await client.patch(path, headers=h.headers(), json={"start_date": None})
    ).status_code == 422
