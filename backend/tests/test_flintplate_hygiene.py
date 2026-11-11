from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site, sent_order
from tests.test_flintplate_production import setup_recipe

pytest_plugins = ["tests.test_flintplate"]


def plan_data(workspace: HRWorkspace) -> dict:
    return {
        "request_key": str(uuid.uuid4()),
        "data": {
            "name": "Kühlraum prüfen",
            "location": "Küche",
            "instructions": "Messung und betriebliche Sofortmaßnahme erfassen.",
            "minimum": "0",
            "maximum": "5",
            "unit": "°C",
            "interval_minutes": 240,
            "responsible_user_id": str(workspace.worker.id),
        },
    }


@pytest.mark.asyncio
async def test_plan_versions_freeze_controls_and_require_real_rechecks(
    client: AsyncClient,
    site: Site,
    hr_workspace: HRWorkspace,
) -> None:
    async def post(path: str, data: dict) -> dict:
        return body(await client.post(site.path(path), headers=site.headers, json=data), 201)

    data = plan_data(hr_workspace)
    data["data"]["name"] = "=2+2"
    first = await post("/hygiene/plans", data)
    assert (await post("/hygiene/plans", data))["id"] == first["id"]
    board = body(await client.get(site.path("/hygiene/plans"), headers=site.headers))
    assert board[0]["overdue"] and board[0]["last_record"] is None
    path = f"/hygiene/plans/{first['plan_id']}/checks"
    check = {"request_key": str(uuid.uuid4()), "version": 1, "value": "8"}
    assert (await client.post(site.path(path), headers=site.headers, json=check)).status_code == 422
    check["correction"] = "Ware gesperrt und in kontrollierten Kühlraum verlagert."
    deviation = await post(path, check)
    assert (await post(path, check))["id"] == deviation["id"]
    board = body(await client.get(site.path("/hygiene/plans"), headers=site.headers))
    assert board[0]["unresolved_deviation_ids"] == [deviation["id"]]
    # An unrelated good measurement does not resolve an earlier deviation.
    await post(path, {"request_key": str(uuid.uuid4()), "version": 1, "value": "3"})
    board = body(await client.get(site.path("/hygiene/plans"), headers=site.headers))
    assert board[0]["unresolved_deviation_ids"] == [deviation["id"]]
    await post(
        path,
        {
            "request_key": str(uuid.uuid4()),
            "version": 1,
            "value": "3",
            "corrects_id": deviation["id"],
        },
    )
    board = body(await client.get(site.path("/hygiene/plans"), headers=site.headers))
    assert not board[0]["unresolved_deviation_ids"] and not board[0]["overdue"]
    second = await post(
        "/hygiene/plans",
        {
            **data,
            "request_key": str(uuid.uuid4()),
            "plan_id": first["plan_id"],
            "expected_version": 1,
            "data": {**data["data"], "maximum": "4"},
        },
    )
    assert second["version"] == 2
    board = body(await client.get(site.path("/hygiene/plans"), headers=site.headers))
    assert board[0]["last_record"] is None and board[0]["overdue"]
    assert Decimal((await post(path, check))["maximum"]) == 5
    assert (
        await client.post(
            site.path(path),
            headers=site.headers,
            json={"request_key": str(uuid.uuid4()), "version": 1, "value": "3"},
        )
    ).status_code == 409
    now = datetime.now(UTC)
    export = body(
        await client.get(
            site.path("/hygiene/export"),
            headers=site.headers,
            params={
                "start": (now - timedelta(days=1)).isoformat(),
                "end": (now + timedelta(days=1)).isoformat(),
            },
        )
    )
    assert len(export["records"]) == 3
    assert export["plan_versions"][0]["version"] == 1
    assert set(export["record_plan_versions"].values()) == {first["id"]}
    csv_result = await client.get(
        site.path("/hygiene/export.csv"),
        headers=site.headers,
        params={
            "start": (now - timedelta(days=1)).isoformat(),
            "end": (now + timedelta(days=1)).isoformat(),
        },
    )
    assert csv_result.status_code == 200
    assert csv_result.headers["cache-control"] == "no-store"
    assert "text/csv" in csv_result.headers["content-type"]
    assert "'=2+2" in csv_result.text and "Nachkontrolle zu" in csv_result.text


@pytest.mark.asyncio
async def test_hygiene_assignment_scope_roles_and_export_bounds(
    client: AsyncClient,
    site: Site,
    hr_workspace: HRWorkspace,
) -> None:
    data = plan_data(hr_workspace)
    assert (
        await client.post(
            site.path("/hygiene/plans"), headers=hr_workspace.headers("worker"), json=data
        )
    ).status_code == 403
    data["data"]["responsible_user_id"] = str(uuid.uuid4())
    assert (
        await client.post(site.path("/hygiene/plans"), headers=site.headers, json=data)
    ).status_code == 422
    assert (
        await client.get(site.path("/hygiene/plans"), headers=hr_workspace.headers("other_hr"))
    ).status_code in (403, 404)
    now = datetime.now(UTC)
    assert (
        await client.get(
            site.path("/hygiene/export"),
            headers=site.headers,
            params={"start": now.isoformat(), "end": (now + timedelta(days=94)).isoformat()},
        )
    ).status_code == 422


@pytest.mark.asyncio
async def test_dish_reverse_trace_reaches_ingredient_lot_and_honestly_marks_legacy(
    client: AsyncClient,
    site: Site,
) -> None:
    plain = await sent_order(client, site)
    empty = body(
        await client.get(site.path(f"/orders/{plain['id']}/provenance"), headers=site.headers)
    )
    assert empty["lots"] == [] and "nicht erfunden" in empty["coverage"]
    setup = await setup_recipe(client, site)
    order = await sent_order(
        client,
        site,
        lines=[
            {
                "item_id": site.item_id,
                "menu_version": setup["recipe"]["menu_version"],
                "quantity": 2,
            }
        ],
    )
    body(
        await client.post(
            site.path(f"/orders/{order['id']}/status"),
            headers=site.headers,
            json={"version": order["version"], "status": "preparing"},
        )
    )
    trace = body(
        await client.get(site.path(f"/orders/{order['id']}/provenance"), headers=site.headers)
    )
    assert [lot["code"] for lot in trace["lots"]] == ["F001"]
    assert len(trace["operation_ids"]) == 2 and not trace["truncated"]
