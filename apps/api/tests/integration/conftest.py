"""Integration tests run against a real, disposable Postgres database — not
sqlite — because the schema depends on Postgres-only features (citext, pg_trgm,
PostGIS geography, pgvector, partial/GIN/GIST indexes) that sqlite can't emulate.

Set TEST_DATABASE_URL to point at that database; defaults to a local
`punerecpip_test` database alongside the dev `punerecpip` one.
"""

import os
import subprocess
import sys
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://punerecpip:punerecpip_dev@localhost:5432/punerecpip_test",
)

API_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run_alembic(*args: str) -> None:
    env = {**os.environ, "DATABASE_URL": TEST_DATABASE_URL}
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=API_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="session", autouse=True)
def migrated_schema() -> None:
    """Migrations run out-of-process via the CLI (mirrors how they run in
    CI/deploy) rather than in-process, since alembic/env.py drives its own
    asyncio.run() event loop that can't nest inside pytest-asyncio's."""
    _run_alembic("upgrade", "head")
    yield
    _run_alembic("downgrade", "base")


@pytest_asyncio.fixture
async def engine(migrated_schema: None) -> AsyncGenerator[AsyncEngine]:
    eng = create_async_engine(TEST_DATABASE_URL)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        yield s
        await s.rollback()
