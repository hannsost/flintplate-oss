"""Temporary real API for browser acceptance, isolated to a fresh flintplate_test schema.

Uses a Unix socket in .local so the existing UI can proxy test requests without
changing its normal API port or starting another Compose stack. No production
accounts, orders or cash entries are touched. Automatic expiry is 45 minutes.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import signal
import socket
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.engine import make_url

source = make_url(os.environ["DATABASE_URL"])
if source.database not in {"flintplate", "flintplate_test"}:
    raise RuntimeError("Only the isolated FlintPlate test database is allowed")
os.environ["DATABASE_URL"] = source.set(database="flintplate_test").render_as_string(
    hide_password=False
)
os.environ["APP_ENV"] = "test"
os.environ["FLINTPLATE_REPLACEMENT_WORKER"] = "false"
os.environ["SMTP_HOST"] = ""
os.environ["AI_MOCK_MODE"] = "true"
if os.environ.get("REDIS_URL"):
    os.environ["REDIS_URL"] = (
        make_url(os.environ["REDIS_URL"]).set(database="1").render_as_string(hide_password=False)
    )

import uvicorn  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402
from alembic.operations import Operations  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402
from sqlalchemy import Connection, select, text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app import database  # noqa: E402

schema = "browser_" + uuid.uuid4().hex
engine = create_async_engine(
    os.environ["DATABASE_URL"],
    hide_parameters=True,
    poolclass=NullPool,
    connect_args={"server_settings": {"search_path": f"{schema},public"}},
    execution_options={"schema_translate_map": {None: schema}},
)
database.engine = engine
database.AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

from app.admin.models import Customer  # noqa: E402
from app.gastro.models import (  # noqa: E402
    DiningTable,
    Floor,
    GuestAccount,
    Membership,
    MenuItem,
    Order,
    Room,
    Venue,
)
from app.gastro.schemas import LineInput, MenuPayload, OrderInput  # noqa: E402
from app.gastro.service import snapshot_lines  # noqa: E402
from app.gastro.station_service import ensure_defaults  # noqa: E402
from app.main import app  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.users.models import User  # noqa: E402
from app.worker.models import ALL_MODULES, WorkerSettings  # noqa: E402


class IsolatedServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self) -> Iterator[None]:
        # Uvicorn normally re-raises SIGTERM after shutdown. Our outer finally
        # must finish removing the owned test schema and private socket first.
        yield


async def main() -> None:
    directory = Path(".local")
    directory.mkdir(exist_ok=True)
    owner = directory.stat()
    access = directory / "browser-acceptance-access.json"
    endpoint = directory / "browser-acceptance.sock"
    if endpoint.exists():
        raise RuntimeError(
            "A browser acceptance socket already exists; do not replace a running test"
        )
    server: uvicorn.Server | None = None
    listener: socket.socket | None = None
    try:
        async with engine.begin() as connection:
            # Database-wide dependencies must outlive this disposable schema,
            # and remain visible to the independent migration/test schemas.
            await connection.execute(
                text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
            )
            await connection.execute(
                text("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public")
            )
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))

            # Browser acceptance must exercise the actual installed guards and
            # defaults too, rather than metadata.create_all's incomplete DDL.
            def migrate(sync_connection: Connection) -> None:
                previous_map = sync_connection.get_execution_options().get("schema_translate_map")
                sync_connection.execution_options(schema_translate_map=None)
                try:
                    with Operations.context(MigrationContext.configure(sync_connection)):
                        for revision in reversed(list(ScriptDirectory("alembic").walk_revisions())):
                            revision.module.upgrade()
                finally:
                    sync_connection.execution_options(schema_translate_map=previous_map)

            await connection.run_sync(migrate)
        async with database.AsyncSessionLocal() as db:
            tenant = Customer(
                name="Browserprüfung FlintPlate",
                slug="browser-" + uuid.uuid4().hex,
                type="internal_hr",
                status="active",
                plan="professional",
            )
            db.add(tenant)
            await db.flush()
            password = secrets.token_urlsafe(24)
            manager = User(
                email="manager-" + uuid.uuid4().hex + "@example.test",
                full_name="Test Leitung",
                hashed_password=hash_password(password),
                role="recruiter",
                tenant_id=tenant.id,
                is_verified=True,
            )
            worker = User(
                email="worker-" + uuid.uuid4().hex + "@example.test",
                full_name="Test Service",
                hashed_password=hash_password(password),
                role="worker",
                tenant_id=tenant.id,
                is_verified=True,
            )
            guest = User(
                email="guest-" + uuid.uuid4().hex + "@example.test",
                full_name="Test Gast",
                hashed_password=hash_password(password),
                role="candidate",
                is_verified=True,
            )
            kitchen = User(
                email="kitchen-" + uuid.uuid4().hex + "@example.test",
                full_name="Test Küche",
                hashed_password=hash_password(password),
                role="worker",
                tenant_id=tenant.id,
                is_verified=True,
            )
            db.add_all([manager, worker, guest, kitchen])
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
            db.add(
                WorkerSettings(
                    user_id=kitchen.id,
                    tenant_id=tenant.id,
                    active_modules=dict(ALL_MODULES),
                    is_active=True,
                    assigned_manager_id=manager.id,
                )
            )
            venue = Venue(
                tenant_id=tenant.id,
                name="Browserprüfung FlintPlate",
                guest_enabled=True,
                guest_table_orders=True,
                guest_open_tables=True,
            )
            db.add(venue)
            await db.flush()
            await ensure_defaults(db, venue.id)
            db.add_all(
                [
                    Membership(venue_id=venue.id, user_id=manager.id, role="manager"),
                    Membership(venue_id=venue.id, user_id=worker.id, role="service"),
                    Membership(venue_id=venue.id, user_id=kitchen.id, role="kitchen"),
                    GuestAccount(venue_id=venue.id, user_id=guest.id),
                ]
            )
            floor = Floor(venue_id=venue.id, name="Erdgeschoss", level=0)
            db.add(floor)
            await db.flush()
            room = Room(venue_id=venue.id, floor_id=floor.id, name="Restaurant")
            db.add(room)
            await db.flush()
            for index, name in enumerate(("T01", "T02")):
                db.add(
                    DiningTable(
                        venue_id=venue.id,
                        room_id=room.id,
                        name=name,
                        seats=4,
                        x=80 + index * 300,
                        y=100,
                    )
                )
            for index in range(13):
                name = (
                    "Testgericht"
                    if index == 0
                    else "Wasser" if index == 1 else f"Testartikel {index + 1:02}"
                )
                data = MenuPayload(
                    name=name,
                    price_cents=300 if index == 1 else 1000,
                    tax_rate_bps=1900,
                    cost_cents=250,
                    station="bar" if index == 1 else "kitchen",
                ).model_dump(mode="json")
                db.add(
                    MenuItem(
                        venue_id=venue.id,
                        sku=f"TEST-{index:02}",
                        draft=data,
                        published=data,
                        version=1,
                        published_version=1,
                    )
                )
            # An indivisible unit with an odd cent amount exercises shared-item
            # payment and persistent 334/334/333 shares through the real UI.
            shared_data = MenuPayload(
                name="Gemeinsame Flasche",
                price_cents=1001,
                tax_rate_bps=1900,
                cost_cents=250,
                station="bar",
            ).model_dump(mode="json")
            db.add(
                MenuItem(
                    venue_id=venue.id,
                    sku="TEST-SHARED",
                    draft=shared_data,
                    published=shared_data,
                    version=1,
                    published_version=1,
                )
            )
            await db.flush()
            # Explicit historical fixture: a closed unpaid legacy receipt older
            # than the recent-100 feed, followed by 101 newer closed receipts.
            # Browser acceptance must find it through the visible history search.
            history_item = (
                await db.execute(
                    select(MenuItem).where(MenuItem.venue_id == venue.id, MenuItem.sku == "TEST-00")
                )
            ).scalar_one()
            history_input = OrderInput(
                request_key=uuid.uuid4(),
                lines=[LineInput(item_id=history_item.id, menu_version=1, quantity=1)],
            )
            history_lines, history_total = await snapshot_lines(db, venue, history_input)
            history_id = uuid.uuid4()
            history_number = "FP-HISTORY-OLD"
            stamp = datetime.now(UTC) - timedelta(days=1)
            for index in range(102):
                db.add(
                    Order(
                        id=history_id if index == 0 else uuid.uuid4(),
                        venue_id=venue.id,
                        actor_id=manager.id,
                        request_key=uuid.uuid4(),
                        request_hash="f" * 64,
                        number=history_number if index == 0 else f"FP-HISTORY-{index:03d}",
                        status="cancelled",
                        fulfillment_status="cancelled",
                        payment_status="open",
                        lines=history_lines,
                        subtotal_cents=history_total,
                        total_cents=history_total,
                        currency="EUR",
                        note="Synthetischer historischer Stornobon nur zur Browserabnahme",
                        created_at=(
                            stamp - timedelta(days=90)
                            if index == 0
                            else stamp + timedelta(seconds=index)
                        ),
                    )
                )
            await db.commit()
            payload = {
                "manager": manager.email,
                "worker": worker.email,
                "guest": guest.email,
                "kitchen": kitchen.email,
                "password": password,
                "venue_id": str(venue.id),
                "history_order_id": str(history_id),
                "history_order_number": history_number,
            }
            access.write_text(json.dumps(payload))
            access.chmod(0o600)
            if os.geteuid() == 0:
                os.chown(access, owner.st_uid, owner.st_gid)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(endpoint))
        endpoint.chmod(0o600)
        if os.geteuid() == 0:
            os.chown(endpoint, owner.st_uid, owner.st_gid)
        listener.listen(128)
        listener.setblocking(False)
        server = IsolatedServer(
            uvicorn.Config(app, lifespan="off", access_log=False, log_level="warning")
        )
        loop = asyncio.get_running_loop()
        for shutdown_signal in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(shutdown_signal, setattr, server, "should_exit", True)

        async def expire() -> None:
            await asyncio.sleep(2700)
            assert server is not None
            server.should_exit = True

        expiration = asyncio.create_task(expire())
        print(
            "Isolated FlintPlate browser API ready (flintplate_test only, 45-minute expiry).",
            flush=True,
        )
        try:
            await server.serve(sockets=[listener])
        finally:
            expiration.cancel()
    finally:
        if listener is not None:
            listener.close()
        endpoint.unlink(missing_ok=True)
        access.unlink(missing_ok=True)
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
