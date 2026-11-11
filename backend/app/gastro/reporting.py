"""Consistent non-blocking read snapshots for reports spanning several ledgers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro.dependencies import DB


async def reporting_db(db: DB) -> AsyncSession:
    # Place this dependency before Actor so the shared get_db session acquires
    # its isolation before authentication's first SELECT. A borrowed transaction
    # (e.g. rollback-scoped fixtures) stays under its caller's transaction policy.
    if not db.in_transaction():
        await db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        await db.execute(text("SET TRANSACTION READ ONLY"))
    return db


ReportingDB = Annotated[AsyncSession, Depends(reporting_db)]
