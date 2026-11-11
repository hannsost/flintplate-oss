"""Real PostgreSQL checks for the separate runtime role; only flintplate_test."""

from __future__ import annotations

import os
import secrets
import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest
from sqlalchemy.engine import make_url

from tools.run_tests import test_environment as isolated_environment
from tools.runtime_db import APPEND_ONLY_TABLES, connect_owner, identifier, provision_role


@pytest.fixture
async def runtime_connection() -> AsyncIterator[asyncpg.Connection]:
    url = make_url(os.environ["DATABASE_URL"])
    assert url.database == "flintplate_test"
    owner = await connect_owner(os.environ["DATABASE_URL"])
    schema = f"runtime_{uuid.uuid4().hex}"
    role = f"flintplate_test_{uuid.uuid4().hex}"
    password = secrets.token_hex(32)
    namespace = identifier(schema)
    connection = None
    try:
        await owner.execute(f"CREATE SCHEMA {namespace}")
        for name in (*sorted(APPEND_ONLY_TABLES), "fp_orders", "alembic_version"):
            await owner.execute(
                f"CREATE TABLE {namespace}.{identifier(name)} "
                "(id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, value integer NOT NULL)"
            )
        # Test a pre-existing role with an inherited owner grant; provisioning
        # must remove SET ROLE as well as inherited privileges.
        await owner.execute(f"CREATE ROLE {identifier(role)}")
        await owner.execute(f"GRANT flintplate TO {identifier(role)}")
        for _ in range(2):
            await provision_role(
                owner, password=password, role=role, schema=schema, lockdown_public=False
            )
        connection = await asyncpg.connect(
            host=url.host,
            port=url.port or 5432,
            user=role,
            password=password,
            database=url.database,
        )
        yield connection
    finally:
        if connection is not None:
            await connection.close()
        await owner.execute(f"DROP SCHEMA IF EXISTS {namespace} CASCADE")
        if await owner.fetchval("SELECT 1 FROM pg_roles WHERE rolname=$1", role):
            await owner.execute(f"DROP OWNED BY {identifier(role)}")
            await owner.execute(f"DROP ROLE {identifier(role)}")
        await owner.close()


async def test_runtime_can_record_business_changes_but_cannot_rewrite_ledgers(
    runtime_connection: asyncpg.Connection,
) -> None:
    db = runtime_connection
    await db.execute("INSERT INTO fp_orders(value) VALUES(1)")
    await db.execute("UPDATE fp_orders SET value=2")
    assert await db.fetchval("SELECT value FROM fp_orders") == 2
    await db.execute("DELETE FROM fp_orders")
    for table in sorted(APPEND_ONLY_TABLES):
        await db.execute(f"INSERT INTO {table}(value) VALUES(1)")
        assert await db.fetchval(f"SELECT count(*) FROM {table}") == 1
        for command in (
            f"UPDATE {table} SET value=2",
            f"DELETE FROM {table}",
            f"TRUNCATE {table}",
            f"ALTER TABLE {table} DISABLE TRIGGER ALL",
            f"DROP TABLE {table}",
        ):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await db.execute(command)
    for command in (
        "SELECT * FROM alembic_version",
        "UPDATE alembic_version SET value=3",
        "CREATE TABLE forged(value integer)",
        "CREATE SCHEMA forged_runtime_schema",
        "CREATE ROLE forged_runtime_role",
        "SET ROLE flintplate",
        "SET session_replication_role = replica",
    ):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await db.execute(command)
    attributes = await db.fetchrow(
        "SELECT rolsuper,rolcreatedb,rolcreaterole,rolinherit,rolreplication,rolbypassrls "
        "FROM pg_roles WHERE rolname=current_user"
    )
    assert attributes is not None and not any(attributes.values())


def test_test_runner_refuses_upstream_and_runtime_identities() -> None:
    for database, username in (
        ("hireos_test", "flintplate"),
        ("hireos", "hireos"),
        ("flintplate", "flintplate_runtime"),
    ):
        with pytest.raises(ValueError):
            isolated_environment({"DATABASE_URL": f"postgresql+asyncpg://{username}@db/{database}"})
    environment = isolated_environment(
        {
            "DATABASE_URL": "postgresql+asyncpg://flintplate:temporary-test-password@db/flintplate",
            "FLINTPLATE_RUNTIME_DB_PASSWORD": "temporary-test-runtime-password",
            "SECRET_KEY": "temporary-live-signer",
        }
    )
    assert make_url(environment["DATABASE_URL"]).database == "flintplate_test"
    assert "FLINTPLATE_RUNTIME_DB_PASSWORD" not in environment
    assert environment["SECRET_KEY"] != "temporary-live-signer"
