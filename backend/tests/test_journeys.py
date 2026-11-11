"""Offer review, candidate privacy, onboarding ownership and identity continuity."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.journeys.models import HiringOffer
from app.security import create_access_token
from app.users.models import User
from app.worker.models import WorkerSettings
from tests.hr_support import HRWorkspace
from tests.test_communication import application
from tests.utils import auth_headers

BASE = "/companies/workspace"


@pytest.fixture
async def journey_people(db_session: AsyncSession, hr_workspace: HRWorkspace) -> tuple[User, User]:
    reviewer = User(
        email=f"reviewer-{uuid.uuid4().hex}@example.com",
        hashed_password="unused",
        full_name="Review Admin",
        role="admin",
        tenant_id=hr_workspace.hr.tenant_id,
    )
    candidate = User(
        email=f"candidate-{uuid.uuid4().hex}@example.com",
        hashed_password="unused",
        full_name="Future Colleague",
        role="candidate",
    )
    db_session.add_all([reviewer, candidate])
    await db_session.flush()
    return reviewer, candidate


def headers(user: User) -> dict[str, str]:
    return auth_headers(create_access_token({"sub": user.email, "ver": user.auth_version}))


async def draft(client: AsyncClient, db: AsyncSession, hr: HRWorkspace, candidate: User) -> dict:
    app = await application(db, hr.hr, candidate)
    today = datetime.now(UTC).date()
    response = await client.post(
        f"{BASE}/offers",
        headers=hr.headers(),
        json={
            "application_id": str(app.id),
            "title": "Willkommen im Team",
            "terms": "Vollzeit, Berlin, vereinbarte Vergütung 60.000 EUR brutto pro Jahr.",
            "start_date": (today + timedelta(days=20)).isoformat(),
            "expires_on": (today + timedelta(days=10)).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def action(
    client: AsyncClient, offer: dict, who: dict[str, str], name: str, **kwargs: object
) -> dict:
    response = await client.post(
        f"{BASE}/offers/{offer['id']}/actions",
        headers=who,
        json={"action": name, "version": offer["version"], **kwargs},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def accepted(
    client: AsyncClient, db: AsyncSession, hr: HRWorkspace, reviewer: User, candidate: User
) -> dict:
    offer = await draft(client, db, hr, candidate)
    offer = await action(client, offer, hr.headers(), "submit", approver_id=str(reviewer.id))
    offer = await action(
        client, offer, headers(reviewer), "approve", note="INTERNAL compensation review"
    )
    offer = await action(client, offer, hr.headers(), "share")
    response = await client.post(
        f"{BASE}/offers/{offer['id']}/decision",
        headers=headers(candidate),
        json={"version": offer["version"], "decision": "accepted"},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_offer_review_versions_privacy_and_today(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
    journey_people: tuple[User, User],
) -> None:
    reviewer, candidate = journey_people
    offer = await draft(client, db_session, hr_workspace, candidate)
    assert (await client.get(f"{BASE}/offers/mine", headers=headers(candidate))).json() == []
    assert (
        await client.get(f"{BASE}/offers", headers=hr_workspace.headers("other_hr"))
    ).json() == []
    assert (
        await client.post(
            f"{BASE}/offers/{offer['id']}/actions",
            headers=hr_workspace.headers("other_hr"),
            json={"action": "withdraw", "version": offer["version"]},
        )
    ).status_code == 404
    assert (
        await client.post(
            f"{BASE}/offers/{offer['id']}/actions",
            headers=hr_workspace.headers(),
            json={"action": "share", "version": offer["version"]},
        )
    ).status_code == 409
    offer = await action(
        client, offer, hr_workspace.headers(), "submit", approver_id=str(reviewer.id)
    )
    today = (await client.get(f"{BASE}/today", headers=headers(reviewer))).json()["actions"]
    assert any(item["id"] == f"offer:{offer['id']}" for item in today)
    assert (
        await client.post(
            f"{BASE}/offers/{offer['id']}/actions",
            headers=hr_workspace.headers(),
            json={"action": "approve", "version": offer["version"]},
        )
    ).status_code == 403
    offer = await action(client, offer, headers(reviewer), "changes", note="INTERNAL needs changes")
    content = {key: offer[key] for key in ["title", "terms", "start_date", "expires_on", "version"]}
    edited = await client.patch(
        f"{BASE}/offers/{offer['id']}",
        headers=hr_workspace.headers(),
        json={**content, "terms": "Updated final terms for review"},
    )
    assert edited.status_code == 200, edited.text
    assert (
        await client.patch(
            f"{BASE}/offers/{offer['id']}", headers=hr_workspace.headers(), json=content
        )
    ).status_code == 409
    offer = await action(
        client, edited.json(), hr_workspace.headers(), "submit", approver_id=str(reviewer.id)
    )
    offer = await action(client, offer, headers(reviewer), "approve", note="INTERNAL approved")
    offer = await action(client, offer, hr_workspace.headers(), "share")
    public = await client.get(f"{BASE}/offers/mine", headers=headers(candidate))
    assert (
        "INTERNAL" not in public.text
        and "events" not in public.text
        and "approver_id" not in public.text
    )
    assert public.json()[0]["terms"] == "Updated final terms for review"
    assert (
        await client.post(
            f"{BASE}/offers/{offer['id']}/decision",
            headers=hr_workspace.headers("other_worker"),
            json={"version": offer["version"], "decision": "accepted"},
        )
    ).status_code == 404
    assert (
        await client.post(
            f"{BASE}/offers/{offer['id']}/decision",
            headers=headers(candidate),
            json={"version": offer["version"] - 1, "decision": "accepted"},
        )
    ).status_code == 409
    decision = await client.post(
        f"{BASE}/offers/{offer['id']}/decision",
        headers=headers(candidate),
        json={"version": offer["version"], "decision": "accepted"},
    )
    assert decision.status_code == 200
    assert (
        await client.post(
            f"{BASE}/offers/{offer['id']}/decision",
            headers=headers(candidate),
            json={"version": decision.json()["version"], "decision": "declined"},
        )
    ).status_code == 409


@pytest.mark.parametrize("template", ["internal_hr", "agency", "staffing"])
async def test_onboarding_templates_visibility_completion_and_activation(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
    journey_people: tuple[User, User],
    template: str,
) -> None:
    reviewer, candidate = journey_people
    candidate_id = candidate.id
    candidate_headers = headers(candidate)
    offer = await accepted(client, db_session, hr_workspace, reviewer, candidate)
    data = {"offer_id": offer["id"], "owner_id": str(hr_workspace.hr.id), "template": template}
    response = await client.post(f"{BASE}/onboarding", headers=hr_workspace.headers(), json=data)
    assert response.status_code == 201, response.text
    case = response.json()
    repeated = await client.post(f"{BASE}/onboarding", headers=hr_workspace.headers(), json=data)
    assert repeated.json()["id"] == case["id"] and repeated.json()["total"] == case["total"]
    assert (
        await client.get(f"{BASE}/onboarding", headers=hr_workspace.headers("other_hr"))
    ).json() == []
    personal = (await client.get(f"{BASE}/onboarding/mine", headers=candidate_headers)).json()[0]
    assert personal["total"] < case["total"]
    assert all(step["audience"] == "person" for step in personal["steps"])
    internal = next(step for step in case["steps"] if step["audience"] == "hr")
    url = f"{BASE}/onboarding/{case['id']}/steps/{internal['id']}"
    assert (
        await client.post(url + "/completion", headers=candidate_headers, json={"completed": True})
    ).status_code == 404
    assert (
        await client.post(
            url + "/completion", headers=hr_workspace.headers("other_hr"), json={"completed": True}
        )
    ).status_code == 404
    person_step = personal["steps"][0]
    done = await client.post(
        f"{BASE}/onboarding/{case['id']}/steps/{person_step['id']}/completion",
        headers=candidate_headers,
        json={"completed": True},
    )
    assert done.status_code == 200 and done.json()["completed_at"]
    # HR can adjust individual tasks and dates, but cannot assign another tenant's staff.
    step_data = {
        "title": "Prepare the workspace",
        "audience": "hr",
        "due_on": datetime.now(UTC).date().isoformat(),
        "assignee_id": str(hr_workspace.other_hr.id),
    }
    assert (
        await client.patch(url, headers=hr_workspace.headers(), json=step_data)
    ).status_code == 422
    step_data["assignee_id"] = str(reviewer.id)
    assert (
        await client.patch(url, headers=hr_workspace.headers(), json=step_data)
    ).status_code == 200
    today = (await client.get(f"{BASE}/today", headers=headers(reviewer))).json()["actions"]
    assert any(item["id"] == f"onboarding:{internal['id']}" for item in today)
    assert (
        await client.post(url + "/completion", headers=headers(reviewer), json={"completed": True})
    ).status_code == 200
    assert (
        await client.patch(url, headers=hr_workspace.headers(), json=step_data)
    ).status_code == 409
    assert (
        await client.post(url + "/completion", headers=headers(reviewer), json={"completed": False})
    ).json()["completed_at"] is None
    assert (
        await client.post(
            f"{BASE}/onboarding/{case['id']}/steps", headers=hr_workspace.headers(), json=step_data
        )
    ).status_code == 201
    assert (
        await client.get(f"{BASE}/onboarding/templates", headers=hr_workspace.headers())
    ).status_code == 200
    assert (
        await client.get(f"{BASE}/journeys/team", headers=hr_workspace.headers())
    ).status_code == 200
    activation = await client.post(
        f"{BASE}/onboarding/{case['id']}/activate",
        headers=hr_workspace.headers(),
        json={"confirmed": True, "employment_type": "fulltime"},
    )
    if template == "agency":
        assert activation.status_code == 409
    else:
        assert activation.status_code == 200, activation.text
        assert activation.json()["person_id"] == str(candidate_id)
        setting = (
            await db_session.execute(
                select(WorkerSettings).where(WorkerSettings.user_id == candidate_id)
            )
        ).scalar_one()
        assert setting.tenant_id == hr_workspace.hr.tenant_id
        assert (await client.get("/users/me", headers=candidate_headers)).status_code == 401
        assert (
            await client.get(f"{BASE}/onboarding/mine", headers=headers(candidate))
        ).status_code == 200
        assert (
            await client.post(
                f"{BASE}/onboarding/{case['id']}/activate",
                headers=hr_workspace.headers(),
                json={"confirmed": True, "employment_type": "fulltime"},
            )
        ).status_code == 200


async def test_expiry_withdrawal_self_approval_and_invalid_assignments(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
    journey_people: tuple[User, User],
) -> None:
    reviewer, candidate = journey_people
    offer = await draft(client, db_session, hr_workspace, candidate)
    assert (
        await client.post(
            f"{BASE}/onboarding",
            headers=hr_workspace.headers(),
            json={
                "offer_id": offer["id"],
                "owner_id": str(hr_workspace.hr.id),
                "template": "staffing",
            },
        )
    ).status_code == 409
    assert (
        await client.post(
            f"{BASE}/offers/{offer['id']}/actions",
            headers=hr_workspace.headers(),
            json={
                "action": "submit",
                "version": offer["version"],
                "approver_id": str(hr_workspace.other_hr.id),
            },
        )
    ).status_code == 422
    hr_workspace.hr.role = "admin"
    await db_session.flush()
    assert (
        await client.post(
            f"{BASE}/offers/{offer['id']}/actions",
            headers=hr_workspace.headers(),
            json={
                "action": "submit",
                "version": offer["version"],
                "approver_id": str(hr_workspace.hr.id),
            },
        )
    ).status_code == 422
    offer = await action(
        client, offer, hr_workspace.headers(), "submit", approver_id=str(reviewer.id)
    )
    offer = await action(client, offer, headers(reviewer), "approve")
    model = await db_session.get(HiringOffer, uuid.UUID(offer["id"]))
    assert model
    original_expiry = model.expires_on
    model.expires_on = datetime.now(UTC).date() - timedelta(days=1)
    await db_session.flush()
    assert (
        await client.post(
            f"{BASE}/offers/{offer['id']}/actions",
            headers=hr_workspace.headers(),
            json={"action": "share", "version": offer["version"]},
        )
    ).status_code == 409
    model.expires_on = original_expiry
    await db_session.flush()
    offer = await action(client, offer, hr_workspace.headers(), "share")
    offer = await action(client, offer, hr_workspace.headers(), "withdraw")
    assert (
        await client.post(
            f"{BASE}/offers/{offer['id']}/decision",
            headers=headers(candidate),
            json={"version": offer["version"], "decision": "accepted"},
        )
    ).status_code == 409
    assert (await client.get(f"{BASE}/offers/mine", headers=headers(candidate))).json()[0][
        "status"
    ] == "withdrawn"


async def test_declined_offer_can_be_replaced_without_losing_history(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
    journey_people: tuple[User, User],
) -> None:
    reviewer, candidate = journey_people
    offer = await draft(client, db_session, hr_workspace, candidate)
    original_terms = offer["terms"]
    content = {
        key: offer[key] for key in ["application_id", "title", "terms", "start_date", "expires_on"]
    }
    assert (
        await client.post(f"{BASE}/offers", headers=hr_workspace.headers(), json=content)
    ).status_code == 409
    offer = await action(
        client, offer, hr_workspace.headers(), "submit", approver_id=str(reviewer.id)
    )
    offer = await action(client, offer, headers(reviewer), "approve")
    offer = await action(client, offer, hr_workspace.headers(), "share")
    response = await client.post(
        f"{BASE}/offers/{offer['id']}/decision",
        headers=headers(candidate),
        json={"version": offer["version"], "decision": "declined"},
    )
    assert response.status_code == 200, response.text
    replacement = await client.post(
        f"{BASE}/offers",
        headers=hr_workspace.headers(),
        json={**content, "terms": "New terms to be separately reviewed"},
    )
    assert replacement.status_code == 201, replacement.text
    assert replacement.json()["id"] != offer["id"]
    visible = (await client.get(f"{BASE}/offers/mine", headers=headers(candidate))).json()
    assert len(visible) == 1 and visible[0]["terms"] == original_terms
    records = (await client.get(f"{BASE}/offers", headers=hr_workspace.headers())).json()
    old = next(item for item in records if item["id"] == offer["id"])
    assert all(event["terms"] == original_terms for event in old["events"])


async def test_onboarding_does_not_take_people_from_other_companies(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
    journey_people: tuple[User, User],
) -> None:
    reviewer, candidate = journey_people
    offer = await accepted(client, db_session, hr_workspace, reviewer, candidate)
    invalid = {
        "offer_id": offer["id"],
        "owner_id": str(hr_workspace.other_hr.id),
        "template": "internal_hr",
    }
    assert (
        await client.post(f"{BASE}/onboarding", headers=hr_workspace.headers(), json=invalid)
    ).status_code == 422
    case = (
        await client.post(
            f"{BASE}/onboarding",
            headers=hr_workspace.headers(),
            json={**invalid, "owner_id": str(hr_workspace.hr.id)},
        )
    ).json()
    candidate.tenant_id = hr_workspace.other_hr.tenant_id
    await db_session.flush()
    result = await client.post(
        f"{BASE}/onboarding/{case['id']}/activate",
        headers=hr_workspace.headers(),
        json={"employment_type": "fulltime", "confirmed": True},
    )
    assert result.status_code == 409
    assert candidate.role == "candidate"


async def test_solo_company_owner_can_explicitly_approve_their_own_offer(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
    journey_people: tuple[User, User],
) -> None:
    from app.admin.models import Customer
    from app.companies.models import Company

    reviewer, candidate = journey_people
    tenant = await db_session.get(Customer, hr_workspace.hr.tenant_id)
    assert tenant
    tenant.type = "solo_recruiter"
    company = Company(name="Solo recruiting", created_by=hr_workspace.hr.id)
    db_session.add(company)
    await db_session.flush()
    hr_workspace.hr.role = "admin"
    hr_workspace.hr.company_id = company.id
    reviewer.company_id = company.id
    await db_session.flush()
    policy = await client.get(f"{BASE}/journeys/approval-policy", headers=hr_workspace.headers())
    assert policy.json()["self_approval_allowed"] is True
    assert (await client.get(f"{BASE}/journeys/approval-policy", headers=headers(reviewer))).json()[
        "self_approval_allowed"
    ] is False
    offer = await draft(client, db_session, hr_workspace, candidate)
    offer = await action(
        client, offer, hr_workspace.headers(), "submit", approver_id=str(hr_workspace.hr.id)
    )
    assert offer["status"] == "approved"
    assert "Firmeninhaber" in offer["events"][-1]["note"]
    offer = await action(client, offer, hr_workspace.headers(), "share")
    assert offer["status"] == "shared"
