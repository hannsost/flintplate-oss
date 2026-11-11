from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import get_settings

settings = get_settings()

if settings.app_env == "test":
    # Background services also use this engine outside the overridden get_db.
    # Pytest's per-test loops cannot share pooled asyncpg connections. Close each
    # connection within its owning loop instead of leaking it during loop teardown.
    engine = create_async_engine(
        settings.database_url, echo=False, hide_parameters=True, poolclass=NullPool
    )
else:
    engine = create_async_engine(
        settings.database_url,
        echo=not settings.is_production,
        hide_parameters=True,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
