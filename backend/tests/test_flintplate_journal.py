from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_flintplate import Site

pytest_plugins = ["tests.test_flintplate"]


@pytest.mark.asyncio
async def test_actual_audit_migration_seals_and_rejects_mutation(
    site: Site, db_session: AsyncSession
) -> None:
    connection = await db_session.connection()

    def install(sync_connection):
        module_path = Path("alembic/versions/057_flintplate_audit_chain.py")
        spec = importlib.util.spec_from_file_location("audit_migration", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with Operations.context(MigrationContext.configure(sync_connection)):
            # Metadata-only test setup already contains the four columns, but no triggers.
            for name in ("audit_sequence", "previous_hash", "event_hash", "canonical_payload"):
                sync_connection.execute(text(f"ALTER TABLE fp_events DROP COLUMN {name}"))
            module.upgrade()
            module.downgrade()
            module.upgrade()

    await connection.run_sync(install)
    rows = (
        (
            await db_session.execute(
                text("SELECT * FROM fp_events WHERE venue_id=:venue ORDER BY audit_sequence"),
                {"venue": site.venue_id},
            )
        )
        .mappings()
        .all()
    )
    assert rows
    previous = "0" * 64
    for index, row in enumerate(rows, 1):
        assert row["audit_sequence"] == index and row["previous_hash"] == previous
        assert (
            row["event_hash"]
            == hashlib.sha256((previous + "|" + row["canonical_payload"]).encode()).hexdigest()
        )
        previous = row["event_hash"]
    for sql in (
        "UPDATE fp_events SET kind='changed'",
        "DELETE FROM fp_events",
        "TRUNCATE fp_events",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            async with db_session.begin_nested():
                await db_session.execute(text(sql))
    await db_session.execute(
        text(
            "INSERT INTO fp_events (id,venue_id,kind,aggregate_id,payload) VALUES (gen_random_uuid(),:venue,'test.sealed',gen_random_uuid(),'{}'::jsonb)"
        ),
        {"venue": site.venue_id},
    )
    latest = (
        (
            await db_session.execute(
                text(
                    "SELECT * FROM fp_events WHERE venue_id=:venue ORDER BY audit_sequence DESC LIMIT 1"
                ),
                {"venue": site.venue_id},
            )
        )
        .mappings()
        .one()
    )
    assert latest["previous_hash"] == previous and latest["audit_sequence"] == len(rows) + 1
    assert latest["sequence"] > rows[-1]["sequence"]
