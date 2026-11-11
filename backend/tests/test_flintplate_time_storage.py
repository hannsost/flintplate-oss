from __future__ import annotations

from datetime import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.hr_support import HRWorkspace, body


@pytest.mark.asyncio
async def test_clock_out_round_trips_through_timestamptz(
    client: AsyncClient, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    await db_session.execute(text("SET LOCAL TIME ZONE 'Europe/Berlin'"))
    # Verify the test schema exercises the real migration's PostgreSQL type.
    data_type = (
        await db_session.execute(
            text(
                "SELECT data_type FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='time_entries' AND column_name='clock_in'"
            )
        )
    ).scalar_one()
    assert data_type == "timestamp with time zone"
    headers = hr_workspace.headers("worker")
    entry = body(
        await client.post(
            "/worker/time", headers=headers, json={"clock_in": "2026-09-01T10:00:00+02:00"}
        ),
        201,
    )
    assert datetime.fromisoformat(entry["clock_in"]).hour == 8
    # A fresh SELECT after the insert must not mix aware PostgreSQL values with
    # the existing personnel API's normalized naive UTC update payload.
    db_session.expire_all()
    updated = body(
        await client.patch(
            f"/worker/time/{entry['id']}",
            headers=headers,
            json={"clock_out": "2026-09-01T16:00:00+02:00", "break_minutes": 30},
        )
    )
    assert updated["net_minutes"] == 330
    assert datetime.fromisoformat(updated["clock_out"]).hour == 14
    body(await client.post(f"/worker/time/{entry['id']}/submit", headers=headers))
