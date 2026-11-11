"""New workspace journeys: company ownership, invitations and tenant privacy."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications.models import Application, ApplicationStatus
from app.companies.models import Company
from app.companies.workspace_models import WorkspaceInvitation
from app.interviews.models import InterviewSchedule, InterviewScorecard
from app.jobs.models import JobPosting
from app.profiles.models import CandidateProfile, Skill
from app.security import create_access_token
from app.users.models import User
from tests.hr_support import HRWorkspace
from tests.utils import auth_headers

BASE = "/companies/workspace"


async def owner(db: AsyncSession, workspace: HRWorkspace) -> dict[str, str]:
    user = workspace.hr
    user.role = "admin"
    company = Company(name="Workspace tests", created_by=user.id)
    db.add(company)
    await db.flush()
    user.company_id = company.id
    await db.flush()
    return workspace.headers()


async def outsider(db: AsyncSession, email: str = "invited@example.com") -> User:
    user = User(email=email, role="candidate", hashed_password="unused")
    db.add(user)
    await db.flush()
    return user


async def invitation(
    client: AsyncClient,
    headers: dict[str, str],
    email: str = "invited@example.com",
    role: str = "recruiter",
) -> dict:
    response = await client.post(
        f"{BASE}/invitations", headers=headers, json={"email": email, "role": role}
    )
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


async def test_invitation_acceptance_rotates_session_and_is_one_use(
    client: AsyncClient, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    headers = await owner(db_session, hr_workspace)
    user = await outsider(db_session)
    old_headers = auth_headers(create_access_token({"sub": user.email}))
    issued = await invitation(client, headers, "INVITED@example.com")
    stored = (await db_session.execute(select(WorkspaceInvitation))).scalar_one()
    assert stored.token_digest == hashlib.sha256(issued["token"].encode()).hexdigest()
    listed = (await client.get(f"{BASE}/members", headers=headers)).json()
    assert "token" not in listed["invitations"][0]
    response = await client.post(
        f"{BASE}/invitations/accept", headers=old_headers, json={"token": issued["token"]}
    )
    assert response.status_code == 200, response.text
    new_headers = auth_headers(response.json()["access_token"])
    me = (await client.get("/users/me", headers=new_headers)).json()
    assert me["tenant_id"] == str(hr_workspace.hr.tenant_id)
    assert me["role"] == "recruiter"
    assert (await client.get("/users/me", headers=old_headers)).status_code == 401
    assert (
        await client.post(
            f"{BASE}/invitations/accept", headers=new_headers, json={"token": issued["token"]}
        )
    ).status_code == 410
    assert (await client.get(f"{BASE}/members", headers=new_headers)).status_code == 403
    assert (
        await client.patch("/companies/mine", headers=new_headers, json={"name": "Hijack"})
    ).status_code == 403
    assert (await client.get("/companies/mine", headers=new_headers)).status_code == 200


@pytest.mark.parametrize("state", ["expired", "revoked", "replaced", "wrong_email", "other_tenant"])
async def test_unusable_invitations_never_move_users(
    client: AsyncClient, db_session: AsyncSession, hr_workspace: HRWorkspace, state: str
) -> None:
    headers = await owner(db_session, hr_workspace)
    user = await outsider(
        db_session, "wrong@example.com" if state == "wrong_email" else "invited@example.com"
    )
    issued = await invitation(client, headers)
    if state == "expired":
        stored = await db_session.get(WorkspaceInvitation, uuid.UUID(issued["id"]))
        assert stored
        stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db_session.flush()
    elif state == "revoked":
        assert (
            await client.delete(f"{BASE}/invitations/{issued['id']}", headers=headers)
        ).status_code == 204
    elif state == "replaced":
        await invitation(client, headers)
    elif state == "other_tenant":
        user.tenant_id = hr_workspace.other_hr.tenant_id
        await db_session.flush()
    previous_tenant = user.tenant_id
    response = await client.post(
        f"{BASE}/invitations/accept",
        headers=auth_headers(create_access_token({"sub": user.email})),
        json={"token": issued["token"]},
    )
    assert response.status_code == {"wrong_email": 403, "other_tenant": 409}.get(state, 410)
    await db_session.refresh(user)
    assert user.tenant_id == previous_tenant


async def test_admin_permissions_and_owner_protection(
    client: AsyncClient, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    headers = await owner(db_session, hr_workspace)
    issued = await invitation(client, headers)
    hr_workspace.other_hr.role = "admin"
    await db_session.flush()
    assert (
        await client.delete(
            f"{BASE}/invitations/{issued['id']}", headers=hr_workspace.headers("other_hr")
        )
    ).status_code == 404
    assert (
        await client.patch(
            f"{BASE}/members/{hr_workspace.hr.id}", headers=headers, json={"role": "recruiter"}
        )
    ).status_code == 409
    assert (
        await client.patch(
            f"{BASE}/members/{hr_workspace.other_hr.id}", headers=headers, json={"role": "admin"}
        )
    ).status_code == 404
    assert (
        await client.post(
            f"{BASE}/invitations", headers=headers, json={"email": hr_workspace.other_hr.email}
        )
    ).status_code == 409
    assert (
        await client.post(
            f"{BASE}/invitations",
            headers=headers,
            json={"email": "new@example.com", "role": "platform_admin"},
        )
    ).status_code == 422
    assert (
        await client.get(f"{BASE}/members", headers=hr_workspace.headers("worker"))
    ).status_code == 403


async def test_owner_can_change_member_role_and_revoke_sessions(
    client: AsyncClient, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    headers = await owner(db_session, hr_workspace)
    user = await outsider(db_session)
    issued = await invitation(client, headers)
    accepted = await client.post(
        f"{BASE}/invitations/accept",
        headers=auth_headers(create_access_token({"sub": user.email})),
        json={"token": issued["token"]},
    )
    token = accepted.json()["access_token"]
    response = await client.patch(
        f"{BASE}/members/{user.id}", headers=headers, json={"role": "admin"}
    )
    assert response.status_code == 200, response.text
    assert (await client.get("/users/me", headers=auth_headers(token))).status_code == 401
    member_headers = auth_headers(create_access_token({"sub": user.email, "ver": 2}))
    assert (
        await client.post(
            f"{BASE}/invitations",
            headers=member_headers,
            json={"email": "admin@example.com", "role": "admin"},
        )
    ).status_code == 403
    assert (
        await client.patch(
            f"{BASE}/members/{hr_workspace.hr.id}",
            headers=member_headers,
            json={"role": "recruiter"},
        )
    ).status_code == 403


async def test_people_search_and_detail_do_not_cross_company_boundaries(
    client: AsyncClient, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    candidate = await outsider(db_session)
    profile = CandidateProfile(
        user_id=candidate.id, headline="Python specialist", location="Berlin"
    )
    db_session.add(profile)
    await db_session.flush()
    db_session.add(Skill(profile_id=profile.id, name="Schweißtechnik", source="cv_page_2"))
    jobs = [
        JobPosting(title=title, company="Test", owner_id=user.id, tenant_id=user.tenant_id)
        for title, user in [("Own role", hr_workspace.hr), ("Secret role", hr_workspace.other_hr)]
    ]
    db_session.add_all(jobs)
    await db_session.flush()
    applications = [
        Application(
            user_id=candidate.id,
            job_id=job.id,
            company="Test",
            position=job.title,
            status=ApplicationStatus.APPLIED,
            notes="Private applicant notes",
        )
        for job in jobs
    ]
    db_session.add_all(applications)
    await db_session.flush()
    headers = hr_workspace.headers()
    result = (await client.get(f"{BASE}/people?q=Schwei%C3%9F", headers=headers)).json()
    assert result["total"] == 1
    assert result["people"][0]["id"] == str(candidate.id)
    detail = await client.get(f"{BASE}/people/{candidate.id}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert [app["position"] for app in detail.json()["applications"]] == ["Own role"]
    assert "Private applicant notes" not in detail.text
    assert "Secret role" not in detail.text
    assert detail.json()["skills"][0]["source"] == "cv_page_2"
    assert (
        await client.get(f"{BASE}/people/{hr_workspace.other_worker.id}", headers=headers)
    ).status_code == 404
    assert (await client.get(f"{BASE}/people?q=%25", headers=headers)).json()["total"] == 0
    assert (await client.get(f"{BASE}/people?role=worker", headers=headers)).json()["total"] == 1
    assert (
        await client.get(f"{BASE}/people", headers=hr_workspace.headers("worker"))
    ).status_code == 403
    today = await client.get(f"{BASE}/today", headers=headers)
    assert today.status_code == 200, today.text
    assert "Secret role" not in today.text
    assert "Own role" in today.text
    # Deep links select a single application through the existing overview.
    deep = await client.get(
        f"/jobs/recruiter/applications?application_id={applications[0].id}", headers=headers
    )
    assert deep.status_code == 200, deep.text
    assert deep.json()["total"] == 1
    assert (
        await client.get(
            f"/jobs/recruiter/applications?application_id={applications[1].id}", headers=headers
        )
    ).json()["total"] == 0


async def test_today_feedback_disappears_after_scorecard(
    client: AsyncClient, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    job = JobPosting(
        title="Local interview",
        company="Test",
        owner_id=hr_workspace.hr.id,
        tenant_id=hr_workspace.hr.tenant_id,
    )
    db_session.add(job)
    await db_session.flush()
    application = Application(
        user_id=hr_workspace.worker.id,
        job_id=job.id,
        company="Test",
        position=job.title,
        status=ApplicationStatus.INTERVIEW,
    )
    db_session.add(application)
    await db_session.flush()
    db_session.add(
        InterviewSchedule(
            application_id=application.id,
            scheduled_at=datetime.now(UTC) - timedelta(days=1),
            status="confirmed",
        )
    )
    await db_session.flush()
    response = await client.get(f"{BASE}/today", headers=hr_workspace.headers())
    assert response.status_code == 200, response.text
    assert response.json()["actions"][0]["kind"] == "feedback"
    db_session.add(
        InterviewScorecard(
            application_id=application.id, recruiter_id=hr_workspace.hr.id, overall_rating=4
        )
    )
    await db_session.flush()
    assert (await client.get(f"{BASE}/today", headers=hr_workspace.headers())).json()[
        "actions"
    ] == []
