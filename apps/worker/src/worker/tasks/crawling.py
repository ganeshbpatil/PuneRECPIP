"""Celery entrypoint for crawl jobs. The task itself is a thin, sync wrapper —
all real logic (page selection, extraction, checkpointing) lives in
CrawlService so it can be unit/integration-tested without Celery/Redis."""

import asyncio
import logging

import httpx
from corelib.models import ScrapeJob
from sqlalchemy import select

from worker.celery_app import app
from worker.core.config import get_settings
from worker.core.db import get_session_factory
from worker.core.storage import get_object_storage
from worker.crawling.browser import BrowserPool
from worker.crawling.service import CrawlService
from worker.net.ratelimit import DomainRateLimiter
from worker.net.robots import RobotsCache

logger = logging.getLogger(__name__)


@app.task(
    name="worker.tasks.crawling.run_crawl_job",
    bind=True,
    autoretry_for=(ConnectionError, OSError),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def run_crawl_job(self, job_id: str) -> dict:
    """Runs (or resumes) the crawl ScrapeJob identified by `job_id`. Safe to
    re-invoke with the same job_id after a crash — CrawlService resumes from
    the job's persisted checkpoint instead of re-crawling completed pages."""
    return asyncio.run(_run_crawl_job_async(job_id))


async def _run_crawl_job_async(job_id: str) -> dict:
    settings = get_settings()
    session_factory = get_session_factory()
    storage = get_object_storage(settings)

    async with (
        session_factory() as session,
        httpx.AsyncClient() as robots_client,
        BrowserPool(
            executable_path=settings.chromium_executable_path,
            max_concurrent_pages=settings.crawl_max_concurrent_pages,
            user_agent=settings.crawl_user_agent,
            page_timeout_seconds=settings.crawl_page_timeout_seconds,
            max_retries=settings.crawl_max_retries,
        ) as browser,
    ):
        job = (
            await session.execute(select(ScrapeJob).where(ScrapeJob.id == job_id))
        ).scalar_one()

        service = CrawlService(
            session,
            browser,
            storage,
            rate_limiter=DomainRateLimiter(settings.crawl_default_requests_per_second),
            robots=RobotsCache(robots_client, settings.crawl_user_agent),
            max_pages_per_company=settings.crawl_max_pages_per_company,
        )
        result = await service.run(job)

    logger.info("crawl job %s finished: %s", job_id, result)
    return {
        "pages_crawled": result.pages_crawled,
        "emails_found": result.emails_found,
        "phones_found": result.phones_found,
        "errors": result.errors,
    }
