"""Company service – Sprint 1.2."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.companies.models import Company
from app.companies.schemas import CompanyCreate, CompanyUpdate


async def create_company(db: AsyncSession, data: CompanyCreate, created_by: uuid.UUID) -> Company:
    company = Company(
        **data.model_dump(exclude_none=True, exclude={"workspace_type"}), created_by=created_by
    )
    db.add(company)
    await db.flush()

    # The creator administers their own tenant, never the platform.
    from app.users.models import User

    result = await db.execute(select(User).where(User.id == created_by))
    user = result.scalar_one_or_none()
    if user:
        user.role = "admin"
        user.company_id = company.id
        # A company-only account has no tenant and cannot safely use HR data.
        # Provision its own trial workspace atomically with company creation.
        if user.tenant_id is None:
            from app.admin.models import MODULES, Customer, CustomerModule

            tenant = Customer(
                name=data.name,
                slug=f"workspace-{uuid.uuid4().hex[:16]}",
                type=data.workspace_type,
                plan="enterprise",
                status="trial",
                contact_email=user.email,
                trial_ends_at=datetime.now(UTC) + timedelta(days=14),
            )
            db.add(tenant)
            await db.flush()
            user.tenant_id = tenant.id
            for module in MODULES:
                db.add(
                    CustomerModule(
                        customer_id=tenant.id,
                        module_key=module["key"],
                        enabled=True,
                        usage_limit=50 if module["category"] == "ai" else None,
                    )
                )
        await db.flush()

    return company


async def get_company(db: AsyncSession, company_id: uuid.UUID) -> Company | None:
    result = await db.execute(select(Company).where(Company.id == company_id))
    return result.scalar_one_or_none()


async def update_company(db: AsyncSession, company: Company, data: CompanyUpdate) -> Company:
    for key, val in data.model_dump(exclude_none=True).items():
        setattr(company, key, val)
    await db.flush()
    return company
