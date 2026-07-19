from corelib.db import make_engine, make_session_factory
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from worker.core.config import get_settings


def get_engine() -> AsyncEngine:
    return make_engine(get_settings().database_url)


def get_session_factory(engine: AsyncEngine | None = None) -> async_sessionmaker[AsyncSession]:
    return make_session_factory(engine or get_engine())
