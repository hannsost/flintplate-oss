"""Admin-Seed: legt einen Admin-User an oder befördert einen bestehenden User.

Usage (im Backend-Container):
  python scripts/seed_admin.py --email admin@example.invalid --password <pw>
  python scripts/seed_admin.py --email bestehendemail@firma.de --promote
  python scripts/seed_admin.py --list
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

# Allow running from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


async def main() -> None:
    parser = argparse.ArgumentParser(description="palmscout Admin Seed Script")
    sub = parser.add_subparsers(dest="cmd")

    create_p = sub.add_parser("create", help="Neuen Admin-User anlegen")
    create_p.add_argument("--email", required=True)
    create_p.add_argument("--password", required=True)
    create_p.add_argument("--name", default="Admin")

    promote_p = sub.add_parser("promote", help="Bestehenden User zu Admin befördern")
    promote_p.add_argument("--email", required=True)

    sub.add_parser("list", help="Alle Admins auflisten")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    import app.admin.models  # noqa: F401 – registers customers table in metadata
    import app.applications.models  # noqa: F401 – registers applications table in metadata
    import app.companies.models  # noqa: F401 – registers companies table in metadata
    import app.jobs.models  # noqa: F401 – registers job_postings table in metadata
    import app.profiles.models  # noqa: F401 – registers profiles table in metadata
    from app.config import get_settings
    from app.users.models import User

    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as db:
        if args.cmd == "create":
            from app.security import hash_password

            existing = (
                await db.execute(select(User).where(User.email == args.email))
            ).scalar_one_or_none()
            if existing:
                print(
                    f"User {args.email} exists bereits – nutze 'promote' um ihn zum Admin zu machen."
                )
                return
            user = User(
                email=args.email,
                hashed_password=hash_password(args.password),
                full_name=args.name,
                role="admin",
                is_active=True,
                is_verified=True,
            )
            db.add(user)
            await db.commit()
            print(f"✅ Admin-User angelegt: {args.email} (ID: {user.id})")

        elif args.cmd == "promote":
            user = (
                await db.execute(select(User).where(User.email == args.email))
            ).scalar_one_or_none()
            if not user:
                print(f"User {args.email} nicht gefunden.")
                return
            old_role = user.role
            user.role = "admin"
            await db.commit()
            print(f"✅ {args.email}: {old_role} → admin")

        elif args.cmd == "list":
            admins = (await db.execute(select(User).where(User.role == "admin"))).scalars().all()
            if not admins:
                print("Keine Admin-User gefunden.")
                return
            print(f"{'Email':<40} {'Name':<25} {'ID'}")
            print("-" * 90)
            for a in admins:
                print(f"{a.email:<40} {(a.full_name or ''):<25} {a.id}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
