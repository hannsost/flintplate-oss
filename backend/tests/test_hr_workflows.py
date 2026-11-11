"""End-to-end HR operations with isolated synthetic organizations."""

from datetime import date

import pytest
from httpx import AsyncClient

from tests.hr_support import HRWorkspace, body


async def test_absence_request_review_and_summary(
    client: AsyncClient, hr_workspace: HRWorkspace
) -> None:
    h = hr_workspace
    item = body(
        await client.post(
            "/worker/absences",
            headers=h.headers("worker"),
            json={
                "absence_type": "vacation",
                "start_date": "2026-09-07",
                "end_date": "2026-09-11",
                "worker_note": "Test holiday",
            },
        ),
        201,
    )
    assert item["working_days"] == 5
    path = f'/zeitarbeit/absences/{item["id"]}'
    assert (await client.get(path, headers=h.headers("other_hr"))).status_code == 404
    assert (
        len(
            (
                await client.get(
                    "/zeitarbeit/absences?status=pending&year=2026", headers=h.headers()
                )
            ).json()
        )
        == 1
    )
    reviewed = body(
        await client.post(
            path + "/review",
            headers=h.headers(),
            json={"action": "approve", "reviewer_note": "Approved"},
        )
    )
    assert reviewed["status"] == "approved"
    summary = body(
        await client.get("/worker/absences/summary?year=2026", headers=h.headers("worker"))
    )
    assert summary["vacation_days_approved"] == 5
    assert (
        await client.post(path + "/review", headers=h.headers(), json={"action": "approve"})
    ).status_code == 409
    assert (
        await client.delete(f'/worker/absences/{item["id"]}', headers=h.headers("worker"))
    ).status_code == 409
    assert (await client.delete(path, headers=h.headers())).status_code == 204
    assert (
        body(await client.get("/worker/absences/summary?year=2026", headers=h.headers("worker")))[
            "vacation_days_approved"
        ]
        == 0
    )


async def test_tasks_from_assignment_through_completion(
    client: AsyncClient, hr_workspace: HRWorkspace
) -> None:
    h = hr_workspace
    item = body(
        await client.post(
            "/zeitarbeit/tasks",
            headers=h.headers(),
            json={
                "assigned_to": str(h.worker.id),
                "title": "Sicherheitseinweisung",
                "priority": "high",
            },
        ),
        201,
    )
    path = f'/zeitarbeit/tasks/{item["id"]}'
    assert (await client.get(path, headers=h.headers("other_hr"))).status_code == 404
    assert (await client.get("/worker/tasks", headers=h.headers("other_worker"))).json() == []
    assert (
        len((await client.get("/worker/tasks?status=open", headers=h.headers("worker"))).json())
        == 1
    )
    item = body(
        await client.patch(
            f'/worker/tasks/{item["id"]}',
            headers=h.headers("worker"),
            json={"status": "done", "worker_note": "Erledigt"},
        )
    )
    assert item["completed_at"]
    item = body(await client.patch(path, headers=h.headers(), json={"status": "open"}))
    assert item["completed_at"] is None
    assert (await client.delete(path, headers=h.headers())).status_code == 204


async def test_task_cannot_be_assigned_to_another_company(
    client: AsyncClient, hr_workspace: HRWorkspace
) -> None:
    h = hr_workspace
    response = await client.post(
        "/zeitarbeit/tasks",
        headers=h.headers(),
        json={"assigned_to": str(h.other_worker.id), "title": "Private HR task"},
    )
    assert response.status_code == 404
    assert (await client.get("/worker/tasks", headers=h.headers("other_worker"))).json() == []


async def test_equipment_assignment_return_and_tenant_boundaries(
    client: AsyncClient, hr_workspace: HRWorkspace
) -> None:
    h = hr_workspace
    item = body(
        await client.post(
            "/zeitarbeit/equipment",
            headers=h.headers(),
            json={"name": "Test laptop", "category": "other"},
        ),
        201,
    )
    path = f'/zeitarbeit/equipment/{item["id"]}'
    assigned = body(
        await client.post(
            path + "/assign",
            headers=h.headers(),
            json={"worker_id": str(h.worker.id), "assigned_at": "2026-09-06"},
        ),
        201,
    )
    assert assigned["worker_id"] == str(h.worker.id)
    assert len((await client.get("/worker/equipment", headers=h.headers("worker"))).json()) == 1
    assert (await client.delete(path, headers=h.headers())).status_code == 409
    assert (
        await client.post(
            path + "/assign",
            headers=h.headers(),
            json={"worker_id": str(h.worker.id), "assigned_at": "2026-09-06"},
        )
    ).status_code == 409
    assert (
        await client.post(
            path + "/return", headers=h.headers("other_hr"), json={"returned_at": "2026-09-07"}
        )
    ).status_code == 404
    returned = body(
        await client.post(
            path + "/return",
            headers=h.headers(),
            json={"returned_at": "2026-09-07", "notes": "Alles vollständig"},
        )
    )
    assert returned["returned_at"] == "2026-09-07"
    assert body(await client.get(path, headers=h.headers()))["status"] == "available"
    assert (await client.delete(path, headers=h.headers())).status_code == 204


async def test_equipment_cannot_be_assigned_across_companies(
    client: AsyncClient, hr_workspace: HRWorkspace
) -> None:
    h = hr_workspace
    item = body(
        await client.post(
            "/zeitarbeit/equipment", headers=h.headers(), json={"name": "Test phone"}
        ),
        201,
    )
    response = await client.post(
        f'/zeitarbeit/equipment/{item["id"]}/assign',
        headers=h.headers(),
        json={"worker_id": str(h.other_worker.id), "assigned_at": str(date.today())},
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/worker/absences",
        "/worker/tasks",
        "/worker/equipment",
        "/worker/payroll",
        "/worker/time",
        "/worker/profile",
    ],
)
async def test_deactivated_worker_loses_portal_access(
    client: AsyncClient, hr_workspace: HRWorkspace, path: str
) -> None:
    h = hr_workspace
    assert (
        await client.delete(f"/zeitarbeit/workers/{h.worker.id}", headers=h.headers())
    ).status_code == 204
    response = await client.get(path, headers=h.headers("worker"))
    assert response.status_code == 403


async def test_time_entry_to_approval_correction_and_export(
    client: AsyncClient, hr_workspace: HRWorkspace
) -> None:
    h = hr_workspace
    entry = body(
        await client.post(
            "/worker/time",
            headers=h.headers("worker"),
            json={"entry_date": "2026-09-06", "clock_in": "2026-09-06T08:00:00+02:00"},
        ),
        201,
    )
    path = f'/worker/time/{entry["id"]}'
    assert (
        await client.post("/worker/time", headers=h.headers("worker"), json={})
    ).status_code == 409
    assert (await client.post(path + "/submit", headers=h.headers("worker"))).status_code == 422
    assert (await client.get(path, headers=h.headers("other_worker"))).status_code == 404
    entry = body(
        await client.patch(
            path,
            headers=h.headers("worker"),
            json={"clock_out": "2026-09-06T16:30:00+02:00", "break_minutes": 30},
        )
    )
    assert entry["net_minutes"] == 480
    assert (
        body(await client.post(path + "/submit", headers=h.headers("worker")))["status"]
        == "submitted"
    )
    pending = (await client.get("/zeitarbeit/time-entries/pending", headers=h.headers())).json()
    assert pending[0]["net_minutes"] == 480
    assert (
        await client.get("/zeitarbeit/time-entries/pending", headers=h.headers("other_hr"))
    ).json() == []
    decision_path = f'/zeitarbeit/time-entries/{entry["id"]}/decision'
    assert (
        await client.post(decision_path, headers=h.headers("other_hr"), json={"action": "approve"})
    ).status_code == 404
    assert (
        body(await client.post(decision_path, headers=h.headers(), json={"action": "approve"}))[
            "status"
        ]
        == "approved"
    )
    correction = body(
        await client.post(
            path + "/correction",
            headers=h.headers("worker"),
            json={
                "new_clock_out": "2026-09-06T17:00:00+02:00",
                "reason": "Zeiterfassung korrigieren",
            },
        ),
        201,
    )
    assert correction["status"] == "pending"
    response = body(
        await client.post(
            "/zeitarbeit/time-entries/bulk-decision",
            headers=h.headers(),
            json={"entry_ids": [entry["id"]], "action": "approve"},
        )
    )
    assert response["affected"] == 1
    assert body(await client.get(path, headers=h.headers("worker")))["net_minutes"] == 510
    assert (
        await client.get("/zeitarbeit/time-entries/corrections/pending", headers=h.headers())
    ).json() == []
    summary = body(
        await client.get("/worker/time/summary?month=2026-09", headers=h.headers("worker"))
    )
    assert summary["approved_minutes"] == 510
    exported = body(
        await client.get("/zeitarbeit/time-entries/export?month=2026-09", headers=h.headers())
    )
    assert exported["rows"][0]["net_hours"] == 8.5


@pytest.mark.parametrize(
    "changes",
    [
        {"clock_out": "2026-09-06T07:00:00Z"},
        {"clock_out": "2026-09-06T09:00:00Z", "break_minutes": 90},
    ],
)
async def test_invalid_working_times_do_not_change_entry(
    client: AsyncClient, hr_workspace: HRWorkspace, changes: dict
) -> None:
    h = hr_workspace
    entry = body(
        await client.post(
            "/worker/time", headers=h.headers("worker"), json={"clock_in": "2026-09-06T08:00:00Z"}
        ),
        201,
    )
    path = f'/worker/time/{entry["id"]}'
    assert (await client.patch(path, headers=h.headers("worker"), json=changes)).status_code == 422
    assert body(await client.get(path, headers=h.headers("worker")))["clock_out"] is None


@pytest.mark.parametrize("month", ["2026-00", "2026-13", "0000-01", "invalid"])
async def test_invalid_months_are_validation_errors(
    client: AsyncClient, hr_workspace: HRWorkspace, month: str
) -> None:
    h = hr_workspace
    for route, who in [
        ("/worker/time", "worker"),
        ("/worker/time/summary", "worker"),
        ("/zeitarbeit/time-entries/all", "hr"),
        ("/zeitarbeit/time-entries/export", "hr"),
    ]:
        response = await client.get(route, params={"month": month}, headers=h.headers(who))
        assert response.status_code == 422
