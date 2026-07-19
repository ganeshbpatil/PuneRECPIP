"""Celery entrypoint for the `enrichment` queue's non-AI enrichment jobs
(Module 6 social discovery, Module 7 RERA enrichment — see
docs/architecture/01-architecture.md's sequence diagram, which groups social
+ RERA into the same `enrichment` queue). Not to be confused with
`worker.enrichment`, the Module 5 AI-extraction *business logic* package, or
`worker/tasks/extraction.py`, the Celery task that runs it on the separate
`extraction` queue.

Thin, sync wrappers — all real logic lives in SocialDiscoveryService /
RERAEnrichmentService so each can be unit/integration-tested without
Celery/Redis."""

import asyncio
import logging

import httpx
from corelib.models import ScrapeJob
from sqlalchemy import select

from worker.celery_app import app
from worker.core.config import get_settings
from worker.core.db import get_session_factory
from worker.core.storage import get_object_storage
from worker.net.ratelimit import DomainRateLimiter
from worker.net.robots import RobotsCache
from worker.rera.client import HTTPRERARegistryClient
from worker.rera.profiles import RERA_SOURCE_PROFILES
from worker.rera.service import RERAEnrichmentService
from worker.social.service import SocialDiscoveryService

logger = logging.getLogger(__name__)


@app.task(
    name="worker.tasks.enrichment.run_social_discovery_job",
    bind=True,
    autoretry_for=(ConnectionError, OSError),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def run_social_discovery_job(self, job_id: str) -> dict:
    return asyncio.run(_run_social_discovery_job_async(job_id))


async def _run_social_discovery_job_async(job_id: str) -> dict:
    settings = get_settings()
    session_factory = get_session_factory()
    storage = get_object_storage(settings)

    async with session_factory() as session:
        job = (
            await session.execute(select(ScrapeJob).where(ScrapeJob.id == job_id))
        ).scalar_one()
        service = SocialDiscoveryService(session, storage)
        result = await service.run(job)

    logger.info("social discovery job %s finished: %s", job_id, result)
    return result


@app.task(
    name="worker.tasks.enrichment.run_rera_enrichment_job",
    bind=True,
    autoretry_for=(ConnectionError, OSError),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def run_rera_enrichment_job(self, job_id: str) -> dict:
    return asyncio.run(_run_rera_enrichment_job_async(job_id))


async def _run_rera_enrichment_job_async(job_id: str) -> dict:
    settings = get_settings()
    session_factory = get_session_factory()

    async with session_factory() as session:
        job = (
            await session.execute(select(ScrapeJob).where(ScrapeJob.id == job_id))
        ).scalar_one()

        profile_name = (job.payload or {}).get("source_profile")
        try:
            profile = RERA_SOURCE_PROFILES[profile_name]
        except KeyError:
            raise ValueError(
                f"unknown rera source_profile {profile_name!r}; registered profiles: "
                f"{sorted(RERA_SOURCE_PROFILES)}"
            ) from None

        async with httpx.AsyncClient(
            headers={"User-Agent": settings.rera_user_agent},
            timeout=settings.rera_request_timeout_seconds,
            follow_redirects=True,
        ) as client:
            registry = HTTPRERARegistryClient(
                profile=profile,
                client=client,
                rate_limiter=DomainRateLimiter(settings.rera_default_requests_per_second),
                robots=RobotsCache(client, settings.rera_user_agent),
                max_retries=settings.rera_max_retries,
            )
            result = await RERAEnrichmentService(session, registry).run(job)

    logger.info("RERA enrichment job %s finished: %s", job_id, result)
    return result
