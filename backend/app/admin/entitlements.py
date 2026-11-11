"""Consistent module availability for the UI and server-side feature checks."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Customer, CustomerModule


async def enabled_modules(db: AsyncSession, tenant_id: uuid.UUID) -> list[str]:
    now = datetime.now(UTC)
    result = await db.scalars(
        select(CustomerModule.module_key)
        .join(Customer, Customer.id == CustomerModule.customer_id)
        .where(
            Customer.id == tenant_id,
            Customer.status.in_(["active", "trial"]),
            or_(
                Customer.status != "trial",
                Customer.trial_ends_at.is_(None),
                Customer.trial_ends_at > now,
            ),
            CustomerModule.enabled.is_(True),
            or_(CustomerModule.expires_at.is_(None), CustomerModule.expires_at > now),
            or_(
                CustomerModule.usage_limit.is_(None),
                CustomerModule.usage_current < CustomerModule.usage_limit,
            ),
        )
    )
    return list(result)
