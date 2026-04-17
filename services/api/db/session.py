import os
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_raw_url = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://vre_user:vre_pass@postgres:5432/vre",
)
# Render/Railway give postgres:// but asyncpg needs postgresql+asyncpg://
DATABASE_URL = _raw_url.replace("postgres://", "postgresql+asyncpg://", 1) if _raw_url.startswith("postgres://") else _raw_url

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
