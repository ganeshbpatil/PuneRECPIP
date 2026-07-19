"""Celery entrypoint for discovery jobs. The task itself is a thin, sync
wrapper — all real logic (pagination, dedup, checkpointing) lives in
DiscoveryService so it can be unit/integration-tested without Celery/Redis."""

import asyncio
import logging

import httpx
from corelib.models import ScrapeJob
from sqlalchemy import select

from worker.celery_app import app
from worker.core.config import get_settings
from worker.core.db import get_session_factory
from worker.discovery.service import DiscoveryService
from worker.discovery.site_profiles import SITE_PROFILES
from worker.discovery.sources import DirectoryDiscoverySource
from worker.net.ratelimit import DomainRateLimiter
from worker.net.robots import RobotsCache

logger = logging.getLogger(__name__)


@app.task(
    name="worker.tasks.discovery.run_discovery_job",
    bind=True,
    autoretry_for=(ConnectionError, OSError),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def run_discovery_job(self, job_id: str) -> dict:
    """Runs (or resumes) the discovery ScrapeJob identified by `job_id`. Safe
    to re-invoke with the same job_id after a crash — DiscoveryService resumes
    from the job's persisted checkpoint instead of starting over."""
    return asyncio.run(_run_discovery_job_async(job_id))


async def _run_discovery_job_async(job_id: str) -> dict:
    settings = get_settings()
    session_factory = get_session_factory()

    async with session_factory() as session:
        job = (
            await session.execute(select(ScrapeJob).where(ScrapeJob.id == job_id))
        ).scalar_one()

        profile_name = job.payload["site_profile"]
        try:
            profile = SITE_PROFILES[profile_name]
        except KeyError:
            raise ValueError(
                f"unknown site_profile {profile_name!r}; registered profiles: "
                f"{sorted(SITE_PROFILES)}"
            ) from None

        async with httpx.AsyncClient(
            headers={"User-Agent": settings.discovery_user_agent},
            timeout=settings.discovery_request_timeout_seconds,
            follow_redirects=True,
        ) as client:
            source = DirectoryDiscoverySource(
                profile=profile,
                client=client,
                rate_limiter=DomainRateLimiter(settings.discovery_default_requests_per_second),
                robots=RobotsCache(client, settings.discovery_user_agent),
                max_retries=settings.discovery_max_retries,
            )
            result = await DiscoveryService(session, source).run(job)

    logger.info("discovery job %s finished: %s", job_id, result)
    return {
        "companies_discovered": result.companies_discovered,
        "companies_skipped_duplicate": result.companies_skipped_duplicate,
        "queries_run": result.queries_run,
        "errors": result.errors,
    }
