"""Readiness without migration privileges or diagnostic details in responses."""

from __future__ import annotations

import asyncio
import json
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.cache import redis_client
from app.database import Base, engine

router = APIRouter()
PROBE_TIMEOUT_SECONDS = 2.0


class ReadinessRead(BaseModel):
    status: Literal["ready", "not_ready"]


def required_columns() -> list[dict[str, str]]:
    # All registered FlintPlate models, including later extensions, must have
    # their actual columns. The runtime role need not read alembic_version.
    return [
        {"table_name": table.name, "column_name": column.name}
        for table in Base.metadata.tables.values()
        if table.name.startswith("fp_")
        for column in table.columns
    ]


async def database_ready() -> bool:
    expected = required_columns()
    if not expected:
        return False
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            async with engine.connect() as connection:
                result = await connection.scalar(
                    text(
                        "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='vector') "
                        "AND NOT EXISTS ("
                        "SELECT 1 FROM jsonb_to_recordset(CAST(:expected AS jsonb)) "
                        "AS expected(table_name text, column_name text) WHERE NOT EXISTS ("
                        "SELECT 1 FROM pg_class c "
                        "JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "JOIN pg_attribute a ON a.attrelid=c.oid "
                        "WHERE n.nspname=current_schema() AND c.relname=expected.table_name "
                        "AND c.relkind IN ('r','p') AND a.attname=expected.column_name "
                        "AND a.attnum>0 AND NOT a.attisdropped "
                        "AND has_table_privilege(c.oid,'SELECT')))"
                    ),
                    {"expected": json.dumps(expected)},
                )
                return result is True
    except (SQLAlchemyError, OSError, TimeoutError):
        return False


async def redis_ready() -> bool:
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            async with redis_client() as client:
                return bool(await client.ping())
    except (RedisError, OSError, TimeoutError):
        return False


@router.get(
    "/ready",
    response_model=ReadinessRead,
    status_code=200,
    summary="Datenbank, aktuelles FlintPlate-Schema, Vector und Redis prüfen",
    responses={503: {"model": ReadinessRead, "description": "Abhängigkeit nicht bereit"}},
)
async def readiness(response: Response) -> ReadinessRead:
    database, redis = await asyncio.gather(database_ready(), redis_ready())
    response.headers["Cache-Control"] = "no-store"
    if not database or not redis:
        response.status_code = 503
        return ReadinessRead(status="not_ready")
    return ReadinessRead(status="ready")
