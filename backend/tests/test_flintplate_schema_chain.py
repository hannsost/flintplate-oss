"""Compare the installed migration chain with ORM reads, not create_all tables."""

from __future__ import annotations

import uuid

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Base


@pytest.mark.asyncio
async def test_complete_migration_chain_supports_every_flintplate_model_column(
    db_session: AsyncSession,
) -> None:
    directory = ScriptDirectory("alembic")
    revisions = list(reversed(list(directory.walk_revisions())))

    def check(connection: Connection) -> None:
        assert (
            connection.execute(text("SELECT current_database()")).scalar_one() == "flintplate_test"
        )
        schema = "schema_chain_" + uuid.uuid4().hex
        previous_path = connection.execute(text("SHOW search_path")).scalar_one()
        previous_map = connection.get_execution_options().get("schema_translate_map")
        connection.execution_options(schema_translate_map=None)
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(
            text("SELECT set_config('search_path', :path, true)"), {"path": f"{schema},public"}
        )
        try:
            with (
                connection.begin_nested(),
                Operations.context(MigrationContext.configure(connection)),
            ):
                for revision in revisions:
                    revision.module.upgrade()
                installed = inspect(connection)
                tables = set(installed.get_table_names(schema=schema))
                for model in Base.metadata.tables.values():
                    if not (model.name.startswith("fp_") or model.name == "tasks"):
                        continue
                    assert model.name in tables, model.name
                    columns = {
                        column["name"]
                        for column in installed.get_columns(model.name, schema=schema)
                    }
                    assert set(model.c.keys()) <= columns, (
                        model.name,
                        set(model.c.keys()) - columns,
                    )
                    # Compile and execute the actual ORM table projection against
                    # migration-created tables, so inherited columns cannot hide.
                    connection.execute(model.select().limit(0))
        finally:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            connection.execute(
                text("SELECT set_config('search_path', :path, true)"), {"path": previous_path}
            )
            connection.execution_options(schema_translate_map=previous_map)

    await (await db_session.connection()).run_sync(check)


@pytest.mark.asyncio
async def test_timestamp_repair_roundtrip_preserves_rows_and_immutable_guard(
    db_session: AsyncSession,
) -> None:
    revision = ScriptDirectory("alembic").get_revision("076a")
    assert revision is not None
    migration = revision.module

    def check(connection: Connection) -> None:
        assert (
            connection.execute(text("SELECT current_database()")).scalar_one() == "flintplate_test"
        )
        schema = "timestamp_repair_" + uuid.uuid4().hex
        previous_path = connection.execute(text("SHOW search_path")).scalar_one()
        previous_map = connection.get_execution_options().get("schema_translate_map")
        connection.execution_options(schema_translate_map=None)
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text("SELECT set_config('search_path', :path, true)"), {"path": schema})
        try:
            with (
                connection.begin_nested(),
                Operations.context(MigrationContext.configure(connection)),
            ):
                for table in migration.TABLES:
                    connection.execute(
                        text(
                            f"CREATE TABLE {table}(id integer PRIMARY KEY, evidence integer NOT NULL)"
                        )
                    )
                    connection.execute(text(f"INSERT INTO {table} VALUES(1,42)"))
                connection.execute(
                    text(
                        "CREATE FUNCTION preserve_evidence() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'immutable evidence'; END $$"
                    )
                )
                connection.execute(
                    text(
                        "CREATE TRIGGER preserve_evidence BEFORE UPDATE OR DELETE ON fp_stock_operations FOR EACH ROW EXECUTE FUNCTION preserve_evidence()"
                    )
                )
                # Real trigger bodies from the repair operate on realistic shells;
                # evidence stands for the immutable quantity/price/source fields.
                guarded = {
                    "fp_stock_lots": ("fp_guard_stock_lot_update", "blocked=true"),
                    "fp_purchase_orders": ("fp_guard_purchase_order", "status='approved'"),
                    "fp_purchase_invoices": ("fp_guard_purchase_invoice", "status='approved'"),
                }
                for table in guarded:
                    connection.execute(
                        text(
                            f"ALTER TABLE {table} ADD version integer NOT NULL DEFAULT 1, "
                            "ADD status text NOT NULL DEFAULT 'draft', "
                            "ADD blocked boolean NOT NULL DEFAULT false"
                        )
                    )
                migration.upgrade()
                for table, (function, _) in guarded.items():
                    connection.execute(
                        text(
                            f"CREATE TRIGGER business_guard BEFORE UPDATE ON {table} "
                            f"FOR EACH ROW EXECUTE FUNCTION {function}()"
                        )
                    )
                for table in migration.TABLES:
                    row = connection.execute(
                        text(f"SELECT id,evidence,updated_at FROM {table}")
                    ).one()
                    assert row.id == 1 and row.evidence == 42 and row.updated_at is not None
                with (
                    pytest.raises(DBAPIError, match="immutable evidence"),
                    connection.begin_nested(),
                ):
                    connection.execute(text("UPDATE fp_stock_operations SET evidence=0"))
                for table, (_, action) in guarded.items():
                    # ORM-style metadata updates must not prevent an allowed action.
                    connection.execute(
                        text(
                            f"UPDATE {table} SET {action}, version=2, "
                            "updated_at=updated_at + interval '1 second'"
                        )
                    )
                    assert (
                        connection.execute(text(f"SELECT version FROM {table}")).scalar_one() == 2
                    )
                    with pytest.raises(DBAPIError, match="immutable"), connection.begin_nested():
                        connection.execute(
                            text(
                                f"UPDATE {table} SET evidence=0, version=3, "
                                "updated_at=updated_at + interval '1 second'"
                            )
                        )
                    with pytest.raises(DBAPIError, match="immutable"), connection.begin_nested():
                        connection.execute(text(f"UPDATE {table} SET version=4"))
                with pytest.raises(DBAPIError, match="immutable"), connection.begin_nested():
                    connection.execute(
                        text("UPDATE fp_purchase_invoices SET status='rejected', version=3")
                    )
                migration.downgrade()
                # Restored pre-repair guards still admit valid state changes.
                connection.execute(text("UPDATE fp_stock_lots SET blocked=false, version=3"))
                connection.execute(
                    text("UPDATE fp_purchase_orders SET status='received', version=3")
                )
                for table in migration.TABLES:
                    assert "updated_at" not in {
                        column["name"]
                        for column in inspect(connection).get_columns(table, schema=schema)
                    }
                migration.upgrade()
                assert (
                    connection.execute(
                        text("SELECT evidence FROM fp_stock_operations")
                    ).scalar_one()
                    == 42
                )
        finally:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            connection.execute(
                text("SELECT set_config('search_path', :path, true)"), {"path": previous_path}
            )
            connection.execution_options(schema_translate_map=previous_map)

    await (await db_session.connection()).run_sync(check)
