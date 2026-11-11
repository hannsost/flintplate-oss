"""End-to-end HR operations with two isolated organizations and synthetic workers."""

import uuid
from dataclasses import dataclass, field

import pytest
from httpx import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Customer
from app.security import create_access_token
from app.users.models import User
from app.worker.models import ALL_MODULES, WorkerSettings
from tests.utils import auth_headers


@dataclass
class HRWorkspace:
    hr: User
    worker: User
    other_hr: User
    other_worker: User

    _headers: dict[str, dict[str, str]] = field(init=False)

    def __post_init__(self) -> None:
        # Keep request credentials independent of ORM expiration after an expected rollback.
        self._headers = {
            who: auth_headers(create_access_token({"sub": getattr(self, who).email}))
            for who in ("hr", "worker", "other_hr", "other_worker")
        }

    def headers(self, who: str = "hr") -> dict[str, str]:
        return self._headers[who]


@pytest.fixture
async def hr_workspace(db_session: AsyncSession) -> HRWorkspace:
    users = []
    for suffix in ["a", "b"]:
        tenant = Customer(
            name=f"Synthetic HR {suffix}", slug=f"hr-{uuid.uuid4().hex}", status="active"
        )
        db_session.add(tenant)
        await db_session.flush()
        hr = User(
            email=f"hr-{uuid.uuid4().hex}@example.com",
            hashed_password="unused-fixture",
            full_name=f"HR {suffix}",
            role="recruiter",
            tenant_id=tenant.id,
        )
        worker = User(
            email=f"worker-{uuid.uuid4().hex}@example.com",
            hashed_password="unused-fixture",
            full_name=f"Worker {suffix}",
            role="worker",
            tenant_id=tenant.id,
        )
        db_session.add_all([hr, worker])
        await db_session.flush()
        db_session.add(
            WorkerSettings(
                user_id=worker.id,
                tenant_id=tenant.id,
                is_active=True,
                active_modules=dict(ALL_MODULES),
                assigned_manager_id=hr.id,
            )
        )
        users.extend([hr, worker])
    await db_session.flush()
    return HRWorkspace(*users)


def body(response: Response, status: int = 200) -> dict:
    assert response.status_code == status, response.text
    return response.json()
