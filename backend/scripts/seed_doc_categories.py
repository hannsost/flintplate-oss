"""Seed global default doc_categories (Sprint 3.1).

Run once after migration 026:
    docker compose exec backend python scripts/seed_doc_categories.py

Creates 7 system categories visible to all tenants (tenant_id = NULL).
Idempotent — skips existing slugs.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

SYSTEM_CATEGORIES = [
    {"slug": "zeugnis", "name": "Zeugnisse", "color": "#3b82f6", "icon": "🎓", "sort_order": 0},
    {"slug": "vertrag", "name": "Verträge", "color": "#10b981", "icon": "📑", "sort_order": 1},
    {
        "slug": "bewerbung",
        "name": "Bewerbungsunterlagen",
        "color": "#8b5cf6",
        "icon": "📋",
        "sort_order": 2,
    },
    {
        "slug": "ausweis",
        "name": "Ausweise & Zertifikate",
        "color": "#f59e0b",
        "icon": "🪪",
        "sort_order": 3,
    },
    {"slug": "lohnzettel", "name": "Lohnzettel", "color": "#ef4444", "icon": "💶", "sort_order": 4},
    {"slug": "vorlage", "name": "Vorlagen", "color": "#6366f1", "icon": "📐", "sort_order": 5},
    {"slug": "sonstiges", "name": "Sonstiges", "color": "#6b7280", "icon": "📄", "sort_order": 6},
]


async def seed() -> None:
    from sqlalchemy import select

    import app.admin.models  # noqa: F401 – registers customers table
    import app.users.models  # noqa: F401 – registers users table
    from app.database import AsyncSessionLocal
    from app.dms.models import DocCategory

    async with AsyncSessionLocal() as db:
        for cat_data in SYSTEM_CATEGORIES:
            existing = await db.execute(
                select(DocCategory).where(
                    DocCategory.slug == cat_data["slug"],
                    DocCategory.tenant_id.is_(None),
                )
            )
            if existing.scalar_one_or_none():
                print(f"  skip: {cat_data['slug']} (already exists)")
                continue

            cat = DocCategory(
                id=uuid.uuid4(),
                tenant_id=None,
                is_system=True,
                **cat_data,
            )
            db.add(cat)
            print(f"  created: {cat_data['icon']} {cat_data['name']}")

        await db.commit()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(seed())
