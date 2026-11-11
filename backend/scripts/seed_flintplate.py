"""Explicit local-only synthetic workspace. Never rewrites existing demo accounts."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.engine import make_url

from app import model_registry  # noqa: F401
from app.admin.models import Customer
from app.database import AsyncSessionLocal
from app.gastro.models import DiningTable, Floor, GuestAccount, Membership, MenuItem, Room, Venue
from app.gastro.router import create_shift, shift_status
from app.gastro.schemas import MenuPayload, Packaging, ShiftInput, ShiftState
from app.security import hash_password
from app.users.models import User
from app.worker.models import ALL_MODULES, WorkerSettings


async def main() -> None:
    if (
        os.environ.get("APP_ENV") != "development"
        or make_url(os.environ["DATABASE_URL"]).database != "flintplate"
    ):
        raise RuntimeError("Seed is restricted to the local flintplate development database")
    async with AsyncSessionLocal() as db:
        if (
            await db.execute(select(Customer.id).where(Customer.slug == "flintplate-demo"))
        ).first():
            print("FlintPlate demo already exists; no changes.")
            return
        tenant = Customer(
            name="Hafen & Funken",
            slug="flintplate-demo",
            type="internal_hr",
            status="active",
            plan="professional",
        )
        db.add(tenant)
        await db.flush()
        password = secrets.token_urlsafe(18)
        manager = User(
            email="leitung@flintplate.example",
            full_name="Alex Winter",
            hashed_password=hash_password(password),
            role="recruiter",
            tenant_id=tenant.id,
            is_verified=True,
        )
        worker = User(
            email="team@flintplate.example",
            full_name="Sam Berger",
            hashed_password=hash_password(password),
            role="worker",
            tenant_id=tenant.id,
            is_verified=True,
        )
        guest = User(
            email="gast@flintplate.example",
            full_name="Robin Sommer",
            hashed_password=hash_password(password),
            role="candidate",
            is_verified=True,
        )
        db.add_all([manager, worker, guest])
        await db.flush()
        db.add(
            WorkerSettings(
                user_id=worker.id,
                tenant_id=tenant.id,
                active_modules=dict(ALL_MODULES),
                is_active=True,
                assigned_manager_id=manager.id,
            )
        )
        venue = Venue(tenant_id=tenant.id, name="Hafen & Funken", guest_enabled=True)
        db.add(venue)
        await db.flush()
        db.add_all(
            [
                Membership(venue_id=venue.id, user_id=manager.id, role="manager"),
                Membership(venue_id=venue.id, user_id=worker.id, role="service"),
                GuestAccount(venue_id=venue.id, user_id=guest.id),
            ]
        )
        floors = [
            Floor(venue_id=venue.id, name="Erdgeschoss", level=0),
            Floor(venue_id=venue.id, name="Obergeschoss", level=1),
            Floor(venue_id=venue.id, name="Am Wasser", level=-1),
        ]
        db.add_all(floors)
        await db.flush()
        rooms = [
            Room(venue_id=venue.id, floor_id=floors[0].id, name="Restaurant"),
            Room(venue_id=venue.id, floor_id=floors[0].id, name="Terrasse"),
            Room(venue_id=venue.id, floor_id=floors[1].id, name="Spielraum"),
            Room(venue_id=venue.id, floor_id=floors[2].id, name="Bootssteg"),
        ]
        db.add_all(rooms)
        await db.flush()
        for n in range(1, 9):
            db.add(
                DiningTable(
                    venue_id=venue.id,
                    name=f"T{n:02}",
                    room_id=rooms[0 if n < 7 else 1].id,
                    area="Restaurant" if n < 7 else "Terrasse",
                    seats=4 if n % 3 else 6,
                    x=80 + ((n - 1) % 3) * 290,
                    y=100 + ((n - 1) // 3) * 300,
                )
            )
        for name, kind, room, rate, x, y, seats in [
            ("Bowling 01", "bowling", rooms[2], 2800, 100, 120, 6),
            ("Billard 01", "billiard", rooms[2], 1200, 530, 120, 4),
            ("Tretboot 01", "pedal_boat", rooms[3], 2000, 100, 150, 4),
            ("Tretboot 02", "pedal_boat", rooms[3], 2000, 520, 150, 4),
            ("Minigolf Gruppe", "activity", rooms[3], 1800, 300, 500, 6),
        ]:
            db.add(
                DiningTable(
                    venue_id=venue.id,
                    name=name,
                    kind=kind,
                    room_id=room.id,
                    area=room.name,
                    seats=seats,
                    hourly_rate_cents=rate,
                    billing_minutes=15,
                    x=x,
                    y=y,
                )
            )
        box = Packaging(
            name="Mehrweg-Box",
            price_cents=50,
            deposit_cents=500,
            tax_rate_bps=1900,
            deposit_tax_rate_bps=0,
            reusable=True,
        )
        cup = Packaging(
            name="Mehrweg-Becher",
            price_cents=0,
            deposit_cents=200,
            tax_rate_bps=1900,
            deposit_tax_rate_bps=0,
            reusable=True,
        )
        for sku, name, description, category, price, cost, allergens, station, package in [
            (
                "S01",
                "Ofenkürbis & Feta",
                "Gerösteter Kürbis, cremiger Feta, Granatapfel und Kräuteröl.",
                "Aus der Küche",
                1490,
                420,
                ["Milch"],
                "kitchen",
                box,
            ),
            (
                "S02",
                "Hafen-Burger",
                "Rindfleisch, Bergkäse, Zwiebel-Chutney und knusprige Pommes.",
                "Aus der Küche",
                1890,
                610,
                ["Gluten", "Milch", "Senf"],
                "kitchen",
                box,
            ),
            (
                "S03",
                "Green Bowl",
                "Quinoa, Avocado, saisonales Gemüse und Zitronen-Tahini.",
                "Aus der Küche",
                1590,
                430,
                ["Sesam"],
                "kitchen",
                box,
            ),
            (
                "S04",
                "Trüffel-Pommes",
                "Knusprige Kartoffeln, Parmesan und Trüffel-Mayonnaise.",
                "Kleine Begleiter",
                690,
                180,
                ["Milch", "Ei"],
                "kitchen",
                box,
            ),
            (
                "D01",
                "Zitronen-Limo",
                "Hausgemacht mit frischer Minze · 0,4 l",
                "An der Bar",
                490,
                90,
                [],
                "bar",
                cup,
            ),
            (
                "D02",
                "Flat White",
                "Doppelter Espresso mit fein geschäumter Milch.",
                "An der Bar",
                420,
                95,
                ["Milch"],
                "bar",
                cup,
            ),
            (
                "D03",
                "Rhabarber-Schorle",
                "Fruchtig, leicht herb und eiskalt · 0,4 l",
                "An der Bar",
                460,
                100,
                [],
                "bar",
                cup,
            ),
            (
                "N01",
                "Warmer Schokokuchen",
                "Flüssiger Kern, Vanilleeis und Beeren.",
                "Etwas Süßes",
                790,
                210,
                ["Gluten", "Milch", "Ei"],
                "kitchen",
                box,
            ),
        ]:
            data = MenuPayload(
                name=name,
                description=description,
                category=category,
                price_cents=price,
                cost_cents=cost,
                tax_rate_bps=1900,
                allergens=allergens,
                station=station,
                takeaway_packaging=package,
            )
            db.add(
                MenuItem(
                    venue_id=venue.id,
                    sku=sku,
                    draft=data.model_dump(mode="json"),
                    published=data.model_dump(mode="json"),
                    version=1,
                    published_version=1,
                )
            )
        await db.flush()
        now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        shift = await create_shift(
            venue.id,
            ShiftInput(
                worker_id=worker.id,
                station="Service & Terrasse",
                starts_at=now,
                ends_at=now + timedelta(hours=8),
                break_minutes=30,
            ),
            manager,
            db,
        )
        await shift_status(
            venue.id, shift.id, ShiftState(version=shift.version, status="published"), manager, db
        )
        await db.commit()
        root = Path("/app/.local")
        root.mkdir(mode=0o700, exist_ok=True)
        path = root / "demo-access.json"
        path.write_text(
            json.dumps(
                {
                    "venue_id": str(venue.id),
                    "password": password,
                    "manager": manager.email,
                    "worker": worker.email,
                    "guest": guest.email,
                },
                indent=2,
            )
            + "\n"
        )
        path.chmod(0o600)
        print(
            "Synthetic demo created. Credentials: backend/.local/demo-access.json. Tax examples require venue configuration before real use."
        )


asyncio.run(main())
