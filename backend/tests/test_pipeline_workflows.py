"""Recruiting pipeline isolation, progression, and notifications."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications.models import Application
from app.jobs.models import JobPosting
from app.pipeline.models import ApplicationStageAssignment, PipelineStage, PipelineTemplate
from app.pipeline.service import check_sla_breaches
from tests.hr_support import HRWorkspace, body


@dataclass
class PipelineData:
    own_application: uuid.UUID
    other_application: uuid.UUID
    system_template: uuid.UUID
    system_stage: uuid.UUID


@pytest.fixture
async def pipeline_data(db_session: AsyncSession, hr_workspace: HRWorkspace) -> PipelineData:
    apps = []
    h = hr_workspace
    for hr, candidate in [(h.hr, h.worker), (h.other_hr, h.other_worker)]:
        job = JobPosting(
            title="Synthetic vacancy",
            company="Synthetic company",
            owner_id=hr.id,
            tenant_id=hr.tenant_id,
        )
        db_session.add(job)
        await db_session.flush()
        application = Application(
            user_id=candidate.id, job_id=job.id, company=job.company, position=job.title
        )
        db_session.add(application)
        await db_session.flush()
        apps.append(application.id)
    template = PipelineTemplate(name="System pipeline")
    db_session.add(template)
    await db_session.flush()
    stage = PipelineStage(template_id=template.id, name="System incoming", position=0)
    db_session.add(stage)
    await db_session.flush()
    return PipelineData(*apps, template.id, stage.id)


async def test_pipeline_progression_history_notifications_and_cleanup(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
    pipeline_data: PipelineData,
) -> None:
    h = hr_workspace
    p = pipeline_data
    template = body(
        await client.post(
            "/pipeline/templates",
            headers=h.headers(),
            json={
                "name": "Engineering",
                "stages": [
                    {"name": "Eingang", "position": 0},
                    {
                        "name": "Interview",
                        "position": 1,
                        "sla_hours": 24,
                        "on_enter_actions": [
                            {
                                "type": "notification",
                                "title": "Interview vorbereiten",
                                "body": "Neue Bewerbung im Interview",
                            }
                        ],
                    },
                ],
            },
        ),
        201,
    )
    path = f'/pipeline/templates/{template["id"]}'
    app_path = f"/pipeline/applications/{p.own_application}"
    assert (await client.get(app_path + "/stage", headers=h.headers())).json() is None
    assert len((await client.get("/pipeline/templates", headers=h.headers())).json()) == 2
    first, second = [stage["id"] for stage in template["stages"]]
    for stage_id in (first, second):
        assert (
            body(
                await client.post(
                    "/pipeline/transitions",
                    headers=h.headers(),
                    json={
                        "application_id": str(p.own_application),
                        "to_stage_id": stage_id,
                        "note": "Geprüft",
                    },
                )
            )["stage"]["id"]
            == stage_id
        )
    assert body(await client.get(app_path + "/stage", headers=h.headers()))["name"] == "Interview"
    assert len((await client.get(app_path + "/history", headers=h.headers())).json()) == 2
    board = body(await client.get(f'/pipeline/kanban/{template["id"]}', headers=h.headers()))
    assert board["columns"][1]["cards"][0]["candidate_email"] == h.worker.email
    notifications = body(await client.get("/notifications/", headers=h.headers()))
    assert notifications["unread_count"] == 1
    note_id = notifications["notifications"][0]["id"]
    assert (
        await client.patch(f"/notifications/{note_id}/read", headers=h.headers("other_hr"))
    ).status_code == 404
    body(await client.patch(f"/notifications/{note_id}/read", headers=h.headers()))
    assert body(await client.get("/notifications/", headers=h.headers()))["unread_count"] == 0
    assignment = await db_session.scalar(
        select(ApplicationStageAssignment).where(
            ApplicationStageAssignment.application_id == p.own_application
        )
    )
    assert assignment is not None
    assignment.entered_at = datetime.now(UTC) - timedelta(hours=25)
    await db_session.flush()
    assert await check_sla_breaches(db_session) == [p.own_application]
    assert body(await client.get("/notifications/", headers=h.headers()))["unread_count"] == 1
    assert (
        body(await client.post("/notifications/read-all", headers=h.headers()))["marked_read"] == 1
    )
    assert (
        await client.delete(f"/pipeline/stages/{second}", headers=h.headers())
    ).status_code == 409
    assert (await client.delete(path, headers=h.headers())).status_code == 409
    extra = body(
        await client.post(
            path + "/stages", headers=h.headers(), json={"name": "Reserve", "position": 2}
        ),
        201,
    )
    assert (
        body(
            await client.patch(
                f'/pipeline/stages/{extra["id"]}', headers=h.headers(), json={"name": "Später"}
            )
        )["name"]
        == "Später"
    )
    assert (
        await client.delete(f'/pipeline/stages/{extra["id"]}', headers=h.headers())
    ).status_code == 204
    assert (
        body(
            await client.patch(
                path, headers=h.headers(), json={"name": "Engineering Team", "is_default": True}
            )
        )["is_default"]
        is True
    )


@pytest.mark.parametrize(
    "operation", ["read", "update", "delete", "add_stage", "update_stage", "delete_stage", "kanban"]
)
async def test_foreign_pipeline_templates_are_inaccessible(
    client: AsyncClient, hr_workspace: HRWorkspace, operation: str
) -> None:
    h = hr_workspace
    template = body(
        await client.post(
            "/pipeline/templates",
            headers=h.headers(),
            json={"name": "Private workflow", "stages": [{"name": "Private stage", "position": 0}]},
        ),
        201,
    )
    path = f'/pipeline/templates/{template["id"]}'
    stage = template["stages"][0]["id"]
    method, endpoint, data = {
        "read": ("GET", path, None),
        "update": ("PATCH", path, {"name": "Unauthorized"}),
        "delete": ("DELETE", path, None),
        "add_stage": ("POST", path + "/stages", {"name": "Unauthorized", "position": 1}),
        "update_stage": ("PATCH", f"/pipeline/stages/{stage}", {"name": "Unauthorized"}),
        "delete_stage": ("DELETE", f"/pipeline/stages/{stage}", None),
        "kanban": ("GET", f'/pipeline/kanban/{template["id"]}', None),
    }[operation]
    assert (
        await client.request(method, endpoint, headers=h.headers("other_hr"), json=data)
    ).status_code == 404
    assert body(await client.get(path, headers=h.headers()))["name"] == "Private workflow"


async def test_shared_system_board_contains_only_company_applications(
    client: AsyncClient, hr_workspace: HRWorkspace, pipeline_data: PipelineData
) -> None:
    h = hr_workspace
    p = pipeline_data
    for who, application in [("hr", p.own_application), ("other_hr", p.other_application)]:
        body(
            await client.post(
                "/pipeline/transitions",
                headers=h.headers(who),
                json={"application_id": str(application), "to_stage_id": str(p.system_stage)},
            )
        )
    board = body(await client.get(f"/pipeline/kanban/{p.system_template}", headers=h.headers()))
    assert [c["application_id"] for col in board["columns"] for c in col["cards"]] == [
        str(p.own_application)
    ]
    for suffix in ("stage", "history"):
        assert (
            await client.get(
                f"/pipeline/applications/{p.other_application}/{suffix}", headers=h.headers()
            )
        ).status_code == 404
    assert (
        await client.post(
            "/pipeline/transitions",
            headers=h.headers(),
            json={"application_id": str(p.other_application), "to_stage_id": str(p.system_stage)},
        )
    ).status_code == 404
    assert (
        await client.patch(
            f"/pipeline/stages/{p.system_stage}", headers=h.headers(), json={"name": "Changed"}
        )
    ).status_code == 403


async def test_pipeline_missing_target_and_duplicate_position_are_client_errors(
    client: AsyncClient, hr_workspace: HRWorkspace, pipeline_data: PipelineData
) -> None:
    h = hr_workspace
    p = pipeline_data
    assert (
        await client.post(
            "/pipeline/transitions",
            headers=h.headers(),
            json={"application_id": str(p.own_application), "to_stage_id": str(uuid.uuid4())},
        )
    ).status_code == 404
    assert (
        await client.get(f"/pipeline/applications/{p.own_application}/history", headers=h.headers())
    ).json() == []
    template = body(
        await client.post(
            "/pipeline/templates",
            headers=h.headers(),
            json={"name": "Unique positions", "stages": [{"name": "One", "position": 0}]},
        ),
        201,
    )
    path = f'/pipeline/templates/{template["id"]}'
    assert (
        await client.post(
            path + "/stages", headers=h.headers(), json={"name": "Duplicate", "position": 0}
        )
    ).status_code == 409
    assert (await client.delete(path, headers=h.headers())).status_code == 204
