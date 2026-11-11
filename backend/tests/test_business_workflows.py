"""Business workflows exercised through the API, including cross-company failures."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.teams.models import Team
from app.users.models import User
from tests.hr_support import HRWorkspace, body


async def test_payroll_draft_publication_and_worker_visibility(
    client: AsyncClient, hr_workspace: HRWorkspace
) -> None:
    h = hr_workspace
    payload = {
        "worker_id": str(h.worker.id),
        "period_year": 2026,
        "period_month": 9,
        "gross_cents": 300000,
        "net_cents": 210000,
        "hours_worked": "160",
    }
    stub = body(await client.post("/zeitarbeit/payroll", headers=h.headers(), json=payload), 201)
    path = f'/zeitarbeit/payroll/{stub["id"]}'
    worker_path = f'/worker/payroll/{stub["id"]}'
    assert stub["period_label"] == "September 2026"
    assert body(await client.get(path, headers=h.headers()))["status"] == "draft"
    assert (await client.get("/worker/payroll", headers=h.headers("worker"))).json() == []
    assert (await client.get(worker_path, headers=h.headers("worker"))).status_code == 404
    assert (
        await client.post("/zeitarbeit/payroll", headers=h.headers(), json=payload)
    ).status_code == 409
    updated = body(
        await client.patch(
            path, headers=h.headers(), json={"notes": "Geprüft", "net_cents": 220000}
        )
    )
    assert updated["net_cents"] == 220000
    assert (
        len(
            (
                await client.get("/zeitarbeit/payroll?year=2026&status=draft", headers=h.headers())
            ).json()
        )
        == 1
    )
    assert body(await client.post(path + "/publish", headers=h.headers()))["published_at"]
    assert body(await client.get(worker_path, headers=h.headers("worker")))["net_cents"] == 220000
    assert (
        len((await client.get("/worker/payroll?year=2026", headers=h.headers("worker"))).json())
        == 1
    )
    assert (await client.get("/worker/payroll?year=2025", headers=h.headers("worker"))).json() == []
    assert (await client.get(worker_path, headers=h.headers("other_worker"))).status_code == 404
    assert (await client.get(path, headers=h.headers("other_hr"))).status_code == 404
    assert (await client.post(path + "/publish", headers=h.headers())).status_code == 409
    assert (await client.patch(path, headers=h.headers(), json={"net_cents": 1})).status_code == 409
    assert (await client.delete(path, headers=h.headers())).status_code == 409


@pytest.mark.parametrize(
    "changes", [{"net_cents": 300001}, {"gross_cents": 1}, {"tax_cents": -1}, {"hours_worked": -1}]
)
async def test_invalid_payroll_update_is_atomic(
    client: AsyncClient, hr_workspace: HRWorkspace, changes: dict
) -> None:
    h = hr_workspace
    stub = body(
        await client.post(
            "/zeitarbeit/payroll",
            headers=h.headers(),
            json={
                "worker_id": str(h.worker.id),
                "period_year": 2026,
                "period_month": 9,
                "gross_cents": 300000,
                "net_cents": 200000,
            },
        ),
        201,
    )
    path = f'/zeitarbeit/payroll/{stub["id"]}'
    assert (await client.patch(path, headers=h.headers(), json=changes)).status_code == 422
    assert body(await client.get(path, headers=h.headers()))["net_cents"] == 200000
    assert (await client.delete(path, headers=h.headers())).status_code == 204


async def test_payroll_cannot_target_a_foreign_worker(
    client: AsyncClient, hr_workspace: HRWorkspace
) -> None:
    h = hr_workspace
    assert (
        await client.post(
            "/zeitarbeit/payroll",
            headers=h.headers(),
            json={
                "worker_id": str(h.other_worker.id),
                "period_year": 2026,
                "period_month": 9,
                "gross_cents": 300000,
                "net_cents": 200000,
            },
        )
    ).status_code == 404


async def test_team_membership_lifecycle_and_tenant_boundaries(
    client: AsyncClient, hr_workspace: HRWorkspace, db_session: AsyncSession
) -> None:
    h = hr_workspace
    h.hr.role = h.other_hr.role = "admin"
    await db_session.flush()
    team = body(
        await client.post("/teams", headers=h.headers(), json={"name": "Personalbetreuung"}), 201
    )
    path = f'/teams/{team["id"]}'
    member_path = path + f"/members/{h.hr.id}"
    member = body(
        await client.post(
            path + "/members", headers=h.headers(), json={"user_id": str(h.hr.id), "role": "lead"}
        ),
        201,
    )
    assert member["full_name"] == h.hr.full_name
    assert (
        await client.post(path + "/members", headers=h.headers(), json={"user_id": str(h.hr.id)})
    ).status_code == 409
    assert (
        await client.post(
            path + "/members", headers=h.headers(), json={"user_id": str(h.other_worker.id)}
        )
    ).status_code == 404
    assert (
        await client.patch(member_path, headers=h.headers("other_hr"), json={"role": "viewer"})
    ).status_code == 404
    assert (await client.delete(member_path, headers=h.headers("other_hr"))).status_code == 404
    assert (
        body(await client.patch(member_path, headers=h.headers(), json={"role": "member"}))["role"]
        == "member"
    )
    assert (await client.get("/teams/mine", headers=h.headers())).json()[0]["member_count"] == 1
    assert (await client.get("/teams", headers=h.headers())).json()[0]["member_count"] == 1
    assert (await client.get("/teams", headers=h.headers("other_hr"))).json() == []
    assert (
        body(await client.patch(path, headers=h.headers(), json={"name": "HR Service"}))["name"]
        == "HR Service"
    )
    assert (await client.delete(member_path, headers=h.headers())).status_code == 204
    assert (await client.get("/teams/mine", headers=h.headers())).json() == []
    assert (await client.delete(path, headers=h.headers())).status_code == 204
    assert (await client.get("/teams", headers=h.headers())).json() == []


async def test_team_hierarchy_rejects_foreign_parent_and_cycles(
    client: AsyncClient, hr_workspace: HRWorkspace, db_session: AsyncSession
) -> None:
    h = hr_workspace
    h.hr.role = h.other_hr.role = "admin"
    await db_session.flush()
    parent = body(await client.post("/teams", headers=h.headers(), json={"name": "Parent"}), 201)
    child = body(
        await client.post(
            "/teams", headers=h.headers(), json={"name": "Child", "parent_team_id": parent["id"]}
        ),
        201,
    )
    foreign = body(
        await client.post("/teams", headers=h.headers("other_hr"), json={"name": "Foreign"}), 201
    )
    path = f'/teams/{parent["id"]}'
    assert (
        await client.patch(path, headers=h.headers(), json={"parent_team_id": foreign["id"]})
    ).status_code == 404
    assert (
        await client.patch(path, headers=h.headers(), json={"parent_team_id": parent["id"]})
    ).status_code == 422
    assert (
        await client.patch(path, headers=h.headers(), json={"parent_team_id": child["id"]})
    ).status_code == 422
    assert body(await client.get(path, headers=h.headers()))["parent_team_id"] is None


async def test_message_thread_lifecycle_keeps_internal_notes_private(
    client: AsyncClient, hr_workspace: HRWorkspace
) -> None:
    h = hr_workspace
    thread = body(
        await client.post(
            "/worker/messages",
            headers=h.headers("worker"),
            json={"subject": "Dienstplan", "body": "Ist der neue Plan verfügbar?"},
        ),
        201,
    )
    path = f'/zeitarbeit/messages/{thread["id"]}'
    worker_path = f'/worker/messages/{thread["id"]}'
    assert thread["unread_hr"] == 1
    assert (
        len((await client.get("/zeitarbeit/messages?unread_only=true", headers=h.headers())).json())
        == 1
    )
    assert body(await client.get(path, headers=h.headers()))["unread_hr"] == 0
    assert (await client.get(path, headers=h.headers("other_hr"))).status_code == 404
    assert (await client.get(worker_path, headers=h.headers("other_worker"))).status_code == 404
    assert body(await client.post(path + "/claim", headers=h.headers()))["claimed_by"] == str(
        h.hr.id
    )
    body(
        await client.post(
            path + "/reply",
            headers=h.headers(),
            json={"body": "Interne Abstimmung", "is_internal_note": True},
        ),
        201,
    )
    visible = body(await client.get(worker_path, headers=h.headers("worker")))
    assert len(visible["messages"]) == 1
    assert "Interne Abstimmung" not in str(visible)
    body(
        await client.post(path + "/reply", headers=h.headers(), json={"body": "Ja, ab Montag."}),
        201,
    )
    assert (await client.get("/worker/messages", headers=h.headers("worker"))).json()[0][
        "unread_worker"
    ] == 1
    visible = body(await client.get(worker_path, headers=h.headers("worker")))
    assert len(visible["messages"]) == 2
    assert visible["unread_worker"] == 0
    assert len(body(await client.get(path, headers=h.headers()))["messages"]) == 3
    assert body(await client.post(path + "/resolve", headers=h.headers()))["status"] == "resolved"
    body(
        await client.post(
            worker_path + "/reply",
            headers=h.headers("worker"),
            json={"body": "Danke, noch eine Rückfrage."},
        ),
        201,
    )
    assert body(await client.get(path, headers=h.headers()))["status"] == "open"
    assert body(await client.post(path + "/unclaim", headers=h.headers()))["claimed_by"] is None
    assert body(await client.post(path + "/reopen", headers=h.headers()))["status"] == "open"


async def test_message_team_assignment_stays_in_company(
    client: AsyncClient, hr_workspace: HRWorkspace, db_session: AsyncSession
) -> None:
    h = hr_workspace
    own = Team(tenant_id=h.hr.tenant_id, name="HR")
    foreign = Team(tenant_id=h.other_hr.tenant_id, name="Confidential other team")
    db_session.add_all([own, foreign])
    await db_session.flush()
    response = await client.post(
        "/worker/messages",
        headers=h.headers("worker"),
        json={"subject": "Team", "body": "Frage", "assigned_team_id": str(foreign.id)},
    )
    assert response.status_code == 404
    thread = body(
        await client.post(
            "/worker/messages",
            headers=h.headers("worker"),
            json={"subject": "Team", "body": "Frage", "assigned_team_id": str(own.id)},
        ),
        201,
    )
    path = f'/zeitarbeit/messages/{thread["id"]}/assign-team'
    assert (
        await client.patch(path, headers=h.headers(), json={"team_id": str(foreign.id)})
    ).status_code == 404
    assert (
        body(await client.patch(path, headers=h.headers(), json={"team_id": None}))[
            "assigned_team_id"
        ]
        is None
    )
    assert (
        body(await client.patch(path, headers=h.headers(), json={"team_id": str(own.id)}))[
            "assigned_team_name"
        ]
        == "HR"
    )


@pytest.mark.parametrize("target", ["hr", "other_hr", "other_worker"])
async def test_worker_activation_cannot_demote_hr_or_take_over_foreign_accounts(
    client: AsyncClient, hr_workspace: HRWorkspace, target: str
) -> None:
    h = hr_workspace
    assert (
        await client.post(
            "/zeitarbeit/workers/activate",
            headers=h.headers(),
            json={"user_id": str(getattr(h, target).id)},
        )
    ).status_code == 403


async def test_worker_activation_and_bulk_management(
    client: AsyncClient, hr_workspace: HRWorkspace, db_session: AsyncSession
) -> None:
    h = hr_workspace
    candidate = User(
        email=f"new-{uuid.uuid4().hex}@example.com",
        hashed_password="unused-fixture",
        full_name="New colleague",
        role="candidate",
    )
    db_session.add(candidate)
    await db_session.flush()
    assert (
        await client.post(
            "/zeitarbeit/workers/activate",
            headers=h.headers(),
            json={"user_id": str(candidate.id), "assigned_manager_id": str(h.other_hr.id)},
        )
    ).status_code == 404
    activated = body(
        await client.post(
            "/zeitarbeit/workers/activate",
            headers=h.headers(),
            json={"user_id": str(candidate.id), "employment_type": "fulltime"},
        ),
        201,
    )
    assert activated["settings"]["tenant_id"] == str(h.hr.tenant_id)
    assert activated["manager"]["id"] == str(h.hr.id)
    assert (
        await client.post(
            "/zeitarbeit/workers/activate", headers=h.headers(), json={"user_id": str(candidate.id)}
        )
    ).status_code == 409
    assert len((await client.get("/zeitarbeit/workers", headers=h.headers())).json()) == 2
    path = f"/zeitarbeit/workers/{candidate.id}/settings"
    assert (
        await client.patch(
            path, headers=h.headers(), json={"assigned_manager_id": str(h.other_hr.id)}
        )
    ).status_code == 404
    assert (
        body(await client.patch(path, headers=h.headers(), json={"max_weekly_hours": 38}))[
            "max_weekly_hours"
        ]
        == 38
    )
    assert (
        body(
            await client.post(
                "/zeitarbeit/workers/bulk",
                headers=h.headers(),
                json={
                    "user_ids": [str(candidate.id), str(h.other_worker.id)],
                    "action": "deactivate",
                },
            )
        )["affected"]
        == 1
    )
    assert (
        body(await client.get(f"/zeitarbeit/workers/{candidate.id}", headers=h.headers()))[
            "settings"
        ]["is_active"]
        is False
    )
    assert (
        body(
            await client.get(
                f"/zeitarbeit/workers/{h.other_worker.id}", headers=h.headers("other_hr")
            )
        )["settings"]["is_active"]
        is True
    )
    assert (
        body(
            await client.post(
                "/zeitarbeit/workers/bulk",
                headers=h.headers(),
                json={"user_ids": [str(candidate.id)], "action": "activate"},
            )
        )["affected"]
        == 1
    )
