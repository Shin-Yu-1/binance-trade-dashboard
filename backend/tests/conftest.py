import os
from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.storage.models import Base

TEST_DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/binance_test",
)


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    # A fresh engine per test avoids asyncpg connections being reused
    # across pytest-asyncio's per-test event loops ("attached to a
    # different loop" errors).
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s

    await engine.dispose()
