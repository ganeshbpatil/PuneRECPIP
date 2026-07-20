"""Regression test for a real bug hit during development: openai.AsyncOpenAI
raises immediately at construction when no API key is configured (unlike
anthropic.AsyncAnthropic, and unlike the httpx.AsyncClient/BrowserPool used
by the discovery/crawl tasks, which never fail until a real request is
made). That construction originally happened before any try/except that
could persist job failure, so a missing credential left the job stuck in
`pending` forever instead of transitioning to `failed`.

Deliberately does NOT use the shared savepoint-isolated `session` fixture:
`_run_extraction_job_async` — like the real Celery task — opens its own,
independent database connection via `get_settings()`/`get_session_factory()`,
which can't see data set up on a different, uncommitted, savepoint-scoped
connection. So this test commits its own setup for real (and cleans up for
real afterward) against TEST_DATABASE_URL, with DATABASE_URL pointed at the
same database so the task's own connection lands in the right place —
exactly what actually happens when the real Celery task runs in production.
"""

import os

import pytest
from corelib.enums import PageType, ScrapeJobStatus, ScrapeJobType
from corelib.models import Company, CrawlSnapshot, ScrapeJob
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from worker.core.config import get_settings
from worker.tasks.extraction import _run_extraction_job_async

# Test directories here aren't packages, so this can't `from .conftest import
# TEST_DATABASE_URL` — same default conftest.py uses.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://punerecpip:punerecpip_dev@localhost:5432/punerecpip_test",
)

pytestmark = pytest.mark.asyncio


async def test_missing_credentials_marks_job_failed_not_stuck_pending(
    migrated_schema: None, monkeypatch
):
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    get_settings.cache_clear()

    engine = create_async_engine(TEST_DATABASE_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as setup_session:
        company = Company(name="Acme Realty Pune", slug="acme-realty-extraction-task-test")
        setup_session.add(company)
        await setup_session.flush()
        setup_session.add(
            CrawlSnapshot(
                company_id=company.id,
                url="https://acme.example/",
                page_type=PageType.HOME.value,
                markdown_key=None,
                is_current=True,
            )
        )
        job = ScrapeJob(
            job_type=ScrapeJobType.EXTRACTION.value,
            status=ScrapeJobStatus.PENDING.value,
            company_id=company.id,
        )
        setup_session.add(job)
        await setup_session.commit()
        job_id = str(job.id)
        company_id = company.id

    try:
        with pytest.raises(Exception, match="credentials"):
            await _run_extraction_job_async(job_id)

        async with session_factory() as check_session:
            refreshed = (
                await check_session.execute(select(ScrapeJob).where(ScrapeJob.id == job_id))
            ).scalar_one()
            assert refreshed.status == ScrapeJobStatus.FAILED.value
            assert refreshed.error_message is not None
            assert "credentials" in refreshed.error_message.lower()
    finally:
        async with session_factory() as cleanup_session:
            await cleanup_session.execute(
                delete(CrawlSnapshot).where(CrawlSnapshot.company_id == company_id)
            )
            await cleanup_session.execute(
                delete(ScrapeJob).where(ScrapeJob.company_id == company_id)
            )
            await cleanup_session.execute(delete(Company).where(Company.id == company_id))
            await cleanup_session.commit()
        await engine.dispose()
        get_settings.cache_clear()
