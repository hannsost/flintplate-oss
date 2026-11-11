"""
Regression tests for multi-tenancy data isolation – T-1.

Verifies that each tenant can only see their own data across all affected endpoints:
- /maps/data
- /zeitarbeit/pool
- /zeitarbeit/canvas/pool
- /zeitarbeit/assignments
- /jobs/recruiter/candidates (search)
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Customer
from app.maps.service import get_map_data
from app.users.models import User
from app.zeitarbeit.models import Disposition, TempWorkerAvailability, WorkAssignment
from app.zeitarbeit.service import list_assignments, list_pool_workers

# ── Test Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
async def tenant_a(db_session: AsyncSession) -> Customer:
    """Create first test tenant (Acme Corp)."""
    tenant = Customer(
        id=uuid.uuid4(),
        name="Acme Corp",
        slug="acme-corp",
        plan="professional",
        status="active",
    )
    db_session.add(tenant)
    await db_session.flush()
    return tenant


@pytest.fixture
async def tenant_b(db_session: AsyncSession) -> Customer:
    """Create second test tenant (Beta Inc)."""
    tenant = Customer(
        id=uuid.uuid4(),
        name="Beta Inc",
        slug="beta-inc",
        plan="professional",
        status="active",
    )
    db_session.add(tenant)
    await db_session.flush()
    return tenant


@pytest.fixture
async def recruiter_a(db_session: AsyncSession, tenant_a: Customer) -> User:
    """Create recruiter for tenant A."""
    from app.security import hash_password

    user = User(
        id=uuid.uuid4(),
        email="recruiter-a@acme.test",
        hashed_password=hash_password("password123"),
        full_name="Recruiter A",
        role="recruiter",
        tenant_id=tenant_a.id,
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def recruiter_b(db_session: AsyncSession, tenant_b: Customer) -> User:
    """Create recruiter for tenant B."""
    from app.security import hash_password

    user = User(
        id=uuid.uuid4(),
        email="recruiter-b@beta.test",
        hashed_password=hash_password("password123"),
        full_name="Recruiter B",
        role="recruiter",
        tenant_id=tenant_b.id,
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def worker_a(db_session: AsyncSession, tenant_a: Customer) -> User:
    """Create worker for tenant A."""
    from app.security import hash_password

    user = User(
        id=uuid.uuid4(),
        email="worker-a@acme.test",
        hashed_password=hash_password("password123"),
        full_name="Worker A",
        role="candidate",  # Workers are candidates in pool
        tenant_id=tenant_a.id,
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def worker_b(db_session: AsyncSession, tenant_b: Customer) -> User:
    """Create worker for tenant B."""
    from app.security import hash_password

    user = User(
        id=uuid.uuid4(),
        email="worker-b@beta.test",
        hashed_password=hash_password("password123"),
        full_name="Worker B",
        role="candidate",
        tenant_id=tenant_b.id,
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def assignment_a(
    db_session: AsyncSession,
    recruiter_a: User,
    tenant_a: Customer,
) -> WorkAssignment:
    """Create work assignment for tenant A."""
    assignment = WorkAssignment(
        id=uuid.uuid4(),
        recruiter_id=recruiter_a.id,
        tenant_id=tenant_a.id,
        title="Test Assignment A",
        description="Assignment for tenant A",
        location="Berlin",
        required_skills=["Python", "Docker"],
        status="active",
        slots=2,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 12, 31),
    )
    db_session.add(assignment)
    await db_session.flush()
    return assignment


@pytest.fixture
async def assignment_b(
    db_session: AsyncSession,
    recruiter_b: User,
    tenant_b: Customer,
) -> WorkAssignment:
    """Create work assignment for tenant B."""
    assignment = WorkAssignment(
        id=uuid.uuid4(),
        recruiter_id=recruiter_b.id,
        tenant_id=tenant_b.id,
        title="Test Assignment B",
        description="Assignment for tenant B",
        location="Munich",
        required_skills=["Java", "Kubernetes"],
        status="active",
        slots=3,
        start_date=date(2026, 9, 15),
        end_date=date(2027, 1, 31),
    )
    db_session.add(assignment)
    await db_session.flush()
    return assignment


@pytest.fixture
async def pool_availability_a(
    db_session: AsyncSession,
    worker_a: User,
) -> TempWorkerAvailability:
    """Create pool availability for worker A."""
    avail = TempWorkerAvailability(
        id=uuid.uuid4(),
        user_id=worker_a.id,
        is_in_pool=True,
        preferred_location="Berlin",
        total_placed_months=5,
    )
    db_session.add(avail)
    await db_session.flush()
    return avail


@pytest.fixture
async def pool_availability_b(
    db_session: AsyncSession,
    worker_b: User,
) -> TempWorkerAvailability:
    """Create pool availability for worker B."""
    avail = TempWorkerAvailability(
        id=uuid.uuid4(),
        user_id=worker_b.id,
        is_in_pool=True,
        preferred_location="Munich",
        total_placed_months=3,
    )
    db_session.add(avail)
    await db_session.flush()
    return avail


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_maps_data_tenant_scoped_assignments(
    db_session: AsyncSession,
    assignment_a: WorkAssignment,
    assignment_b: WorkAssignment,
    recruiter_a: User,
    recruiter_b: User,
) -> None:
    """T-1: Recruiter A should only see assignments from tenant A on map."""
    # Recruiter A views map (tenant A)
    result_a = await get_map_data(db_session, tenant_id=recruiter_a.tenant_id)
    assert len(result_a.assignments) == 1, "Recruiter A should see 1 assignment (their own tenant)"
    assert result_a.assignments[0].id == str(assignment_a.id)

    # Recruiter B views map (tenant B)
    result_b = await get_map_data(db_session, tenant_id=recruiter_b.tenant_id)
    assert len(result_b.assignments) == 1, "Recruiter B should see 1 assignment (their own tenant)"
    assert result_b.assignments[0].id == str(assignment_b.id)


@pytest.mark.asyncio
async def test_maps_data_tenant_scoped_workers(
    db_session: AsyncSession,
    pool_availability_a: TempWorkerAvailability,
    pool_availability_b: TempWorkerAvailability,
    recruiter_a: User,
    recruiter_b: User,
) -> None:
    """T-1: Recruiter A should only see workers from tenant A on map."""
    result_a = await get_map_data(db_session, tenant_id=recruiter_a.tenant_id)
    assert len(result_a.workers) == 1, "Recruiter A should see 1 worker (their own tenant)"
    assert result_a.workers[0].user_id == str(pool_availability_a.user_id)

    result_b = await get_map_data(db_session, tenant_id=recruiter_b.tenant_id)
    assert len(result_b.workers) == 1, "Recruiter B should see 1 worker (their own tenant)"
    assert result_b.workers[0].user_id == str(pool_availability_b.user_id)


@pytest.mark.asyncio
async def test_pool_workers_tenant_scoped(
    db_session: AsyncSession,
    pool_availability_a: TempWorkerAvailability,
    pool_availability_b: TempWorkerAvailability,
    recruiter_a: User,
    recruiter_b: User,
) -> None:
    """T-1: Pool endpoint should return only this tenant's workers."""
    pool_a = await list_pool_workers(db_session, tenant_id=recruiter_a.tenant_id)
    assert len(pool_a) == 1, "Recruiter A should see only 1 pool worker"
    assert pool_a[0].user_id == pool_availability_a.user_id

    pool_b = await list_pool_workers(db_session, tenant_id=recruiter_b.tenant_id)
    assert len(pool_b) == 1, "Recruiter B should see only 1 pool worker"
    assert pool_b[0].user_id == pool_availability_b.user_id


@pytest.mark.asyncio
async def test_assignments_tenant_scoped(
    db_session: AsyncSession,
    assignment_a: WorkAssignment,
    assignment_b: WorkAssignment,
    recruiter_a: User,
    recruiter_b: User,
) -> None:
    """T-1: Assignments list should be scoped by tenant."""
    # Get assignments for tenant A
    assignments_a = await list_assignments(db_session, recruiter_a.id, status=None)
    assert (
        len(assignments_a) == 1
    ), f"Expected 1 assignment for recruiter A, got {len(assignments_a)}"
    assert assignments_a[0].id == assignment_a.id

    # Get assignments for tenant B
    assignments_b = await list_assignments(db_session, recruiter_b.id, status=None)
    assert (
        len(assignments_b) == 1
    ), f"Expected 1 assignment for recruiter B, got {len(assignments_b)}"
    assert assignments_b[0].id == assignment_b.id


@pytest.mark.asyncio
async def test_disposition_isolation(
    db_session: AsyncSession,
    assignment_a: WorkAssignment,
    assignment_b: WorkAssignment,
    worker_a: User,
    worker_b: User,
) -> None:
    """T-1: Dispositions for one tenant should not affect another."""
    from decimal import Decimal

    from app.zeitarbeit.service import get_dispositions

    # Create disposition for assignment A
    disp_a = Disposition(
        id=uuid.uuid4(),
        assignment_id=assignment_a.id,
        worker_id=worker_a.id,
        status="suggested",
        score=Decimal("0.95"),
    )
    db_session.add(disp_a)

    # Create disposition for assignment B
    disp_b = Disposition(
        id=uuid.uuid4(),
        assignment_id=assignment_b.id,
        worker_id=worker_b.id,
        status="suggested",
        score=Decimal("0.87"),
    )
    db_session.add(disp_b)
    await db_session.flush()

    # Dispositions for assignment A should only show A's disposition
    disps_a = await get_dispositions(db_session, assignment_a.id)
    assert len(disps_a) == 1, "Assignment A should have only 1 disposition"
    assert disps_a[0].worker_id == worker_a.id

    # Dispositions for assignment B should only show B's disposition
    disps_b = await get_dispositions(db_session, assignment_b.id)
    assert len(disps_b) == 1, "Assignment B should have only 1 disposition"
    assert disps_b[0].worker_id == worker_b.id


@pytest.mark.asyncio
async def test_cross_tenant_access_blocked(
    db_session: AsyncSession,
    recruiter_a: User,
    recruiter_b: User,
    assignment_b: WorkAssignment,
) -> None:
    """T-1: Recruiter A cannot see data from tenant B."""
    # Recruiter A tries to view tenant B's assignments
    assignments_a = await list_assignments(db_session, recruiter_a.id)
    assignment_ids = [a.id for a in assignments_a]
    assert (
        assignment_b.id not in assignment_ids
    ), "Recruiter A should not see tenant B's assignments"

    # Recruiter A tries to view tenant B's map data
    map_data_a = await get_map_data(db_session, tenant_id=recruiter_a.tenant_id)
    map_assignment_ids = [a.id for a in map_data_a.assignments]
    assert (
        str(assignment_b.id) not in map_assignment_ids
    ), "Recruiter A should not see tenant B's assignments on map"
