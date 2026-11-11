"""Check new order/production schema upgrades with existing financial snapshots."""

from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_order_and_production_migrations_preserve_snapshots_and_identity(
    db_session: AsyncSession,
) -> None:
    modules = []
    for filename in (
        "068_flintplate_inventory.py",
        "069_flintplate_order_operations.py",
        "070_flintplate_recipes_haccp.py",
        "075_flintplate_hygiene_plans.py",
    ):
        spec = importlib.util.spec_from_file_location(filename, Path("alembic/versions") / filename)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)

    def check(sync: Connection) -> None:
        schema = f"erp_migration_{uuid.uuid4().hex}"
        previous_path = sync.execute(text("SHOW search_path")).scalar_one()
        previous_map = sync.get_execution_options().get("schema_translate_map")
        sync.execution_options(schema_translate_map=None)
        sync.execute(text(f'CREATE SCHEMA "{schema}"'))
        sync.execute(
            text("SELECT set_config('search_path', :path, true)"), {"path": f"{schema},public"}
        )
        try:
            for table in ("fp_venues", "users", "fp_menu_items"):
                sync.execute(text(f"CREATE TABLE {table} (id uuid PRIMARY KEY)"))
            sync.execute(
                text(
                    "CREATE TABLE fp_orders (id uuid PRIMARY KEY, lines jsonb NOT NULL, "
                    "status text NOT NULL, paid_at timestamptz, pos_requested boolean NOT NULL, "
                    "total_cents integer NOT NULL, tax_cents integer NOT NULL)"
                )
            )
            order_id, existing_line = uuid.uuid4(), str(uuid.uuid4())
            lines = [
                {"name": "Historischer Preis", "total_cents": 1234, "tax_cents": 197},
                {
                    "name": "Neue Position",
                    "total_cents": 500,
                    "tax_cents": 80,
                    "line_id": existing_line,
                    "course": 2,
                    "preparation_status": "ready",
                },
            ]
            sync.execute(
                text(
                    "INSERT INTO fp_orders VALUES (:id, CAST(:lines AS jsonb), 'settled', now(), true, 1734, 277)"
                ),
                {"id": order_id, "lines": json.dumps(lines)},
            )
            with Operations.context(MigrationContext.configure(sync)):
                for module in modules:
                    module.upgrade()
                upgraded = sync.execute(text("SELECT * FROM fp_orders")).mappings().one()
                assert upgraded["total_cents"] == 1734 and upgraded["tax_cents"] == 277
                assert upgraded["fulfillment_status"] == "served"
                assert upgraded["payment_status"] == "paid"
                first = upgraded["lines"]
                assert first[0]["line_id"] == str(uuid.uuid5(order_id, "line:0"))
                assert first[1]["line_id"] == existing_line
                assert first[1]["course"] == 2 and first[1]["preparation_status"] == "ready"
                assert [row["total_cents"] for row in first] == [1234, 500]
                for module in reversed(modules):
                    module.downgrade()
                for module in modules:
                    module.upgrade()
                assert sync.execute(text("SELECT lines FROM fp_orders")).scalar_one() == first
                triggers = sync.execute(
                    text(
                        "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                        "JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname=:schema AND c.relname IN "
                        "('fp_recipe_versions','fp_prep_runs','fp_haccp_records') AND NOT t.tgisinternal"
                    ),
                    {"schema": schema},
                ).scalar_one()
                assert triggers == 6
                ids = {
                    name: uuid.uuid4()
                    for name in (
                        "venue",
                        "actor",
                        "record",
                        "plan",
                        "plan_version",
                        "check",
                        "record_key",
                        "plan_key",
                        "check_key",
                    )
                }
                for statement in (
                    "INSERT INTO fp_venues VALUES (:venue)",
                    "INSERT INTO users VALUES (:actor)",
                    "INSERT INTO fp_haccp_records(id,venue_id,request_key,request_hash,name,location,measured_at,value,minimum,maximum,unit,result,correction,actor_id) VALUES (:record,:venue,:record_key,'hash','Kontrolle','Küche',now(),3,0,5,'C','ok','',:actor)",
                    "INSERT INTO fp_hygiene_plan_versions(id,venue_id,request_key,request_hash,plan_id,version,data,actor_id) VALUES (:plan_version,:venue,:plan_key,'hash',:plan,1,'{}'::jsonb,:actor)",
                    "INSERT INTO fp_hygiene_plan_checks(id,venue_id,request_key,request_hash,plan_version_id,record_id) VALUES (:check,:venue,:check_key,'hash',:plan_version,:record)",
                ):
                    sync.execute(text(statement), ids)
                for table in ("fp_hygiene_plan_versions", "fp_hygiene_plan_checks"):
                    for statement in (
                        f"UPDATE {table} SET request_hash='changed'",
                        f"DELETE FROM {table}",
                        f"TRUNCATE {table} CASCADE",
                    ):
                        with pytest.raises(DBAPIError, match="append-only"), sync.begin_nested():
                            sync.execute(text(statement))
        finally:
            sync.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            sync.execute(
                text("SELECT set_config('search_path', :path, true)"), {"path": previous_path}
            )
            sync.execution_options(schema_translate_map=previous_map)

    await (await db_session.connection()).run_sync(check)
