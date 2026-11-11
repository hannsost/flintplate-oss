"""Seed all test users for QA / manual testing (Sprint all).

Creates:
  - 2 Tenants  (Enterprise + Starter)
  - 1 Platform Admin
  - 2 Recruiters (one per tenant)
  - 2 Candidates (job seekers)

Usage (inside backend container):
    docker compose exec backend python scripts/seed_test_users.py

Idempotent – safe to run multiple times.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Test data ─────────────────────────────────────────────────────────────────

TENANTS = [
    {
        "slug": "demo-enterprise",
        "name": "DemoFirma GmbH (Enterprise)",
        "type": "zeitarbeit",
        "plan": "enterprise",
        "status": "active",
        "contact_email": "recruiter@demo-enterprise.de",
        "contact_name": "Max Mustermann",
        "city": "München",
        "country": "DE",
        "primary_color": "#2563eb",
        # all 14 modules enabled, unlimited usage
        "modules": "ALL",
    },
    {
        "slug": "demo-starter",
        "name": "StartupRecruit AG (Starter)",
        "type": "recruiter_agency",
        "plan": "starter",
        "status": "active",
        "contact_email": "recruiter@demo-starter.de",
        "contact_name": "Anna Schmidt",
        "city": "Berlin",
        "country": "DE",
        "primary_color": "#10b981",
        # only core modules enabled (no AI, no advanced analytics)
        "modules": [
            "kanban_pipeline",
            "interview_scheduling",
            "partner_portal",
            "org_charts",
            "dms",
        ],
    },
]

USERS = [
    # ── Platform Admin (no tenant) ─────────────────────────────────────────
    {
        "email": "admin@hireos.test",
        "password": "Admin1234!",
        "full_name": "Platform Admin",
        "role": "admin",
        "tenant_slug": None,
        "is_verified": True,
    },
    # ── Enterprise Recruiter ───────────────────────────────────────────────
    {
        "email": "recruiter@demo-enterprise.de",
        "password": "Recruiter1234!",
        "full_name": "Max Mustermann",
        "role": "recruiter",
        "tenant_slug": "demo-enterprise",
        "is_verified": True,
    },
    # ── Enterprise Admin-Recruiter (admin role, linked to tenant) ──────────
    {
        "email": "admin-recruiter@demo-enterprise.de",
        "password": "AdminRec1234!",
        "full_name": "Lena Huber (Admin+Recruiter)",
        "role": "admin",
        "tenant_slug": "demo-enterprise",
        "is_verified": True,
    },
    # ── Starter Recruiter ──────────────────────────────────────────────────
    {
        "email": "recruiter@demo-starter.de",
        "password": "Starter1234!",
        "full_name": "Anna Schmidt",
        "role": "recruiter",
        "tenant_slug": "demo-starter",
        "is_verified": True,
    },
    # ── Candidate / Job Seeker 1 ───────────────────────────────────────────
    {
        "email": "kandidat@hireos.test",
        "password": "Kandidat1234!",
        "full_name": "Jonas Weber",
        "role": "candidate",
        "tenant_slug": None,
        "is_verified": True,
    },
    # ── Candidate / Job Seeker 2 ───────────────────────────────────────────
    {
        "email": "kandidat2@hireos.test",
        "password": "Kandidat1234!",
        "full_name": "Sophie Müller",
        "role": "candidate",
        "tenant_slug": None,
        "is_verified": False,  # unverified → tests the email-verification banner
    },
]


# ── Seed logic ────────────────────────────────────────────────────────────────


async def seed() -> None:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    import app.applications.models  # noqa: F401

    # ensure all FK-referenced tables are registered in metadata
    import app.companies.models  # noqa: F401
    import app.jobs.models  # noqa: F401
    import app.profiles.models  # noqa: F401
    from app.admin.models import MODULES, Customer, CustomerModule
    from app.companies.models import Company
    from app.config import get_settings
    from app.security import hash_password
    from app.users.models import User

    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    all_module_keys = [m["key"] for m in MODULES]

    async with Session() as db:
        # ── 1. Tenants ─────────────────────────────────────────────────────
        tenant_map: dict[str, uuid.UUID] = {}
        for t in TENANTS:
            existing = (
                await db.execute(select(Customer).where(Customer.slug == t["slug"]))
            ).scalar_one_or_none()

            if existing:
                tenant_map[t["slug"]] = existing.id
                print(f"  skip tenant: {t['slug']} (exists)")
            else:
                c = Customer(
                    id=uuid.uuid4(),
                    slug=t["slug"],
                    name=t["name"],
                    type=t["type"],
                    plan=t["plan"],
                    status=t["status"],
                    contact_email=t["contact_email"],
                    contact_name=t["contact_name"],
                    city=t["city"],
                    country=t["country"],
                    primary_color=t["primary_color"],
                    trial_ends_at=datetime.now(UTC) + timedelta(days=90),
                )
                db.add(c)
                await db.flush()
                tenant_map[t["slug"]] = c.id

                # Enable modules
                module_keys = all_module_keys if t["modules"] == "ALL" else t["modules"]
                for key in module_keys:
                    mod = CustomerModule(
                        id=uuid.uuid4(),
                        customer_id=c.id,
                        module_key=key,
                        enabled=True,
                        usage_limit=None,
                    )
                    db.add(mod)

                print(f"  created tenant: {t['slug']} ({len(module_keys)} modules)")

        await db.commit()

        # ── 2. Users + Companies ─────────────────────────────────────────────
        for u in USERS:
            existing = (
                await db.execute(select(User).where(User.email == u["email"]))
            ).scalar_one_or_none()

            if existing:
                print(f"  skip user: {u['email']} (exists)")
                continue

            tenant_id = tenant_map.get(u["tenant_slug"]) if u["tenant_slug"] else None

            # Create Company for recruiters
            company_id = None
            if u["role"] == "recruiter" and u["tenant_slug"]:
                tenant_data = next((t for t in TENANTS if t["slug"] == u["tenant_slug"]), None)
                company = Company(
                    id=uuid.uuid4(),
                    name=tenant_data["name"] if tenant_data else u["full_name"],
                    location=tenant_data["city"] if tenant_data else None,
                    created_by=None,
                )
                db.add(company)
                await db.flush()
                company_id = company.id
                print(f"  created company: {company.name}")

            user = User(
                id=uuid.uuid4(),
                email=u["email"],
                hashed_password=hash_password(u["password"]),
                full_name=u["full_name"],
                role=u["role"],
                is_active=True,
                is_verified=u["is_verified"],
                tenant_id=tenant_id,
                company_id=company_id,
            )
            db.add(user)
            print(
                f"  created user:  {u['email']}  [{u['role']}]{'  (unverified)' if not u['is_verified'] else ''}"
            )

        await db.commit()

    await engine.dispose()
    print("\nDone. See TEST_USERS.md for login credentials.")


if __name__ == "__main__":
    asyncio.run(seed())
