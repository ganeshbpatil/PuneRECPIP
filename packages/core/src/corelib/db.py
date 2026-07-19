"""Generic async engine/session-factory helpers shared by every service that
talks to Postgres (api, worker, search-indexer, ...) so the connection-pooling
setup lives in exactly one place instead of being copy-pasted per app."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def make_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
