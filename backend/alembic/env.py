"""Alembic async environment – works with asyncpg + PostgreSQL 16."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Ensure the project root (/app inside container) is on sys.path so that
# `from app.xxx import ...` works regardless of how alembic is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.absences.models import Absence  # noqa: F401 – register metadata

# ── Import all models so Alembic can detect them ─────────────────────────────
from app.database import Base
from app.messages.models import Message, MessageThread  # noqa: F401 – register metadata
from app.payroll.models import PayStub  # noqa: F401 – register metadata
from app.tasks.models import Task  # noqa: F401 – register metadata
from app.teams.models import Team, TeamMember  # noqa: F401 – register metadata
from app.users.models import PrivacyConsent, User  # noqa: F401 – register metadata
from app.worker.assignment_models import WorkerAssignment  # noqa: F401 – register metadata
from app.worker.models import WorkerSettings  # noqa: F401 – register metadata
from app.worker.time_models import TimeEntry, TimeEntryCorrection  # noqa: F401 – register metadata

# ── Alembic Config ────────────────────────────────────────────────────────────
config = context.config

# Override sqlalchemy.url from environment variable
db_url = os.environ.get("DATABASE_URL", config.get_main_option("sqlalchemy.url"))
config.set_main_option("sqlalchemy.url", db_url or "")

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


# ── Offline migrations (generates SQL without DB connection) ──────────────────
def run_migrations_offline() -> None:
    context.configure(
        url=db_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online migrations (runs against live DB) ─────────────────────────────────
def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
