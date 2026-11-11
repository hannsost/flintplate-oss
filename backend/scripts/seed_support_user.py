"""Create the palmscout internal support user."""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Import all models to resolve FK relationships
from app.admin.models import Customer, CustomerModule  # noqa
from app.companies.models import Company  # noqa
from app.security import hash_password
from app.support.models import SupportConfig, SupportSession  # noqa
from app.users.models import User  # noqa

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://hireos:hireos@db:5432/hireos")


async def main() -> None:
    email = os.environ.get("PALMSCOUT_SUPPORT_EMAIL", "").strip().lower()
    password = os.environ.get("PALMSCOUT_SUPPORT_PASSWORD", "")
    if not email or len(password) < 12:
        raise SystemExit(
            "PALMSCOUT_SUPPORT_EMAIL und ein individuelles Passwort mit mindestens 12 Zeichen sind erforderlich."
        )
    engine = create_async_engine(DATABASE_URL)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        row = await db.execute(select(User).where(User.email == email))
        u = row.scalar_one_or_none()
        if u:
            print("ℹ  Support-User existiert bereits.")
        else:
            u = User(
                email=email,
                full_name="palmscout Support",
                hashed_password=hash_password(password),
                role="support",
                is_active=True,
                is_verified=True,
            )
            db.add(u)
            await db.commit()
            print("Support-Zugang erstellt. Zugangsdaten werden nicht ausgegeben.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
