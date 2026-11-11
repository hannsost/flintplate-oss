from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.main import app
from app.security import get_current_user
from tests.hr_support import HRWorkspace


@pytest.mark.asyncio
async def test_commit_failure_never_acknowledges_success(
    client: AsyncClient, db_session: AsyncSession, hr_workspace: HRWorkspace
) -> None:
    async def failing_commit() -> AsyncGenerator[AsyncSession, None]:
        yield db_session
        raise HTTPException(503, "Synthetic transaction failure")

    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = failing_commit
    app.dependency_overrides[get_current_user] = lambda: hr_workspace.hr
    try:
        response = await client.post(
            "/gastro/venues", json={"name": "Never acknowledge uncommitted venue"}
        )
        assert response.status_code == 503
        assert response.json()["detail"] == "Synthetic transaction failure"
    finally:
        app.dependency_overrides[get_db] = previous
        app.dependency_overrides.pop(get_current_user, None)
