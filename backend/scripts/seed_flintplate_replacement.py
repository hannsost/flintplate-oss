"""Add synthetic staff to the explicitly local demo for browser acceptance."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.engine import make_url

from app import model_registry  # noqa: F401
from app.admin.models import Customer
from app.database import AsyncSessionLocal, engine
from app.gastro.models import Membership, Venue
from app.security import hash_password
from app.users.models import User
from app.worker.models import ALL_MODULES, WorkerSettings


async def main() -> None:
    if (
        os.environ.get("APP_ENV") != "development"
        or make_url(os.environ["DATABASE_URL"]).database != "flintplate"
    ):
        raise RuntimeError("Local FlintPlate demo only")
    path = Path("/app/.local/demo-access.json")
    credentials = json.loads(path.read_text())
    async with AsyncSessionLocal.begin() as db:
        venue = (
            await db.execute(
                select(Venue)
                .join(Customer, Customer.id == Venue.tenant_id)
                .where(Customer.slug == "flintplate-demo")
            )
        ).scalar_one()
        existing = (
            await db.execute(select(User).where(User.email == "vertretung@flintplate.example"))
        ).scalar_one_or_none()
        if existing is None:
            existing = User(
                email="vertretung@flintplate.example",
                full_name="Jamie Kern",
                role="worker",
                tenant_id=venue.tenant_id,
                is_verified=True,
                hashed_password=hash_password(credentials["password"]),
            )
            db.add(existing)
            await db.flush()
            db.add(
                WorkerSettings(
                    user_id=existing.id,
                    tenant_id=venue.tenant_id,
                    date_of_birth=date(1994, 5, 12),
                    max_weekly_hours=35,
                    hourly_rate=18,
                    is_active=True,
                    active_modules=dict(ALL_MODULES),
                )
            )
            db.add(
                Membership(
                    venue_id=venue.id,
                    user_id=existing.id,
                    role="service",
                    stations=["service", "kitchen"],
                    competence=4,
                )
            )
        worker = (
            await db.execute(
                select(User).where(
                    User.email == credentials["worker"], User.tenant_id == venue.tenant_id
                )
            )
        ).scalar_one()
        settings = (
            await db.execute(select(WorkerSettings).where(WorkerSettings.user_id == worker.id))
        ).scalar_one()
        if settings.date_of_birth is None:
            settings.date_of_birth = date(1992, 2, 14)
        credentials["replacement"] = existing.email
    path.write_text(json.dumps(credentials, indent=2) + "\n")
    path.chmod(0o600)
    await engine.dispose()
    print(
        "Synthetic replacement employee prepared; voluntary availability remains employee-controlled."
    )


asyncio.run(main())
