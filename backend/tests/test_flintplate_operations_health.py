"""Readiness checks use the isolated test schema and never need Alembic access."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import Response
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.exc import OperationalError

from app import operations_health as health
from tests.conftest import test_engine


@pytest.mark.asyncio
async def test_database_probe_checks_current_physical_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(health, "engine", test_engine)
    assert await health.database_ready() is True
    actual = health.required_columns()
    assert {"table_name": "fp_orders", "column_name": "tip_refunded_cents"} in actual
    assert any(row["table_name"] == "fp_reservation_resources" for row in actual)
    monkeypatch.setattr(
        health,
        "required_columns",
        lambda: [*actual, {"table_name": "fp_orders", "column_name": "missing_probe_column"}],
    )
    assert await health.database_ready() is False
    monkeypatch.setattr(health, "required_columns", lambda: [])
    assert await health.database_ready() is False


@pytest.mark.asyncio
async def test_dependency_failure_and_timeout_are_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = AsyncMock()
    connection.scalar.side_effect = OperationalError("private statement", {}, ValueError("secret"))
    fake_engine = AsyncMock()
    fake_engine.connect = lambda: connection
    connection.__aenter__.return_value = connection
    monkeypatch.setattr(health, "engine", fake_engine)
    assert await health.database_ready() is False

    client = AsyncMock()
    client.__aenter__.return_value = client
    client.ping.side_effect = RedisConnectionError("private credentials")
    monkeypatch.setattr(health, "redis_client", lambda: client)
    assert await health.redis_ready() is False

    async def slow_ping() -> bool:
        await asyncio.sleep(1)
        return True

    client.ping.side_effect = slow_ping
    monkeypatch.setattr(health, "PROBE_TIMEOUT_SECONDS", 0.01)
    assert await health.redis_ready() is False


@pytest.mark.asyncio
@pytest.mark.parametrize("database,redis", [(True, True), (False, True), (True, False)])
async def test_status_and_no_store(
    monkeypatch: pytest.MonkeyPatch, database: bool, redis: bool
) -> None:
    monkeypatch.setattr(health, "database_ready", AsyncMock(return_value=database))
    monkeypatch.setattr(health, "redis_ready", AsyncMock(return_value=redis))
    response = Response()
    result = await health.readiness(response)
    assert response.status_code == (200 if database and redis else 503)
    assert result.model_dump() == {"status": "ready" if database and redis else "not_ready"}
    assert response.headers["Cache-Control"] == "no-store"
