"""Celery entrypoint for geo resolution jobs. The task itself is a thin,
sync wrapper — all real logic lives in GeoIntelligenceService so it can be
unit/integration-tested without Celery/Redis."""

import asyncio
import logging

import httpx
from corelib.models import ScrapeJob
from sqlalchemy import select

from worker.celery_app import app
from worker.core.config import get_settings
from worker.core.db import get_session_factory
from worker.geo.nominatim import NominatimGeocodingProvider
from worker.geo.service import GeoIntelligenceService
from worker.net.ratelimit import DomainRateLimiter

logger = logging.getLogger(__name__)


@app.task(
    name="worker.tasks.geo.run_geo_resolution_job",
    bind=True,
    autoretry_for=(ConnectionError, OSError),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def run_geo_resolution_job(self, job_id: str) -> dict:
    return asyncio.run(_run_geo_resolution_job_async(job_id))


async def _run_geo_resolution_job_async(job_id: str) -> dict:
    settings = get_settings()
    session_factory = get_session_factory()

    async with session_factory() as session:
        job = (
            await session.execute(select(ScrapeJob).where(ScrapeJob.id == job_id))
        ).scalar_one()

        async with httpx.AsyncClient(
            headers={"User-Agent": settings.geo_user_agent},
            timeout=settings.geo_request_timeout_seconds,
            follow_redirects=True,
        ) as client:
            provider = NominatimGeocodingProvider(
                client,
                DomainRateLimiter(settings.geo_requests_per_second),
                base_url=settings.geo_nominatim_base_url,
                requests_per_second=settings.geo_requests_per_second,
                max_retries=settings.geo_max_retries,
            )
            result = await GeoIntelligenceService(session, provider).run(job)

    logger.info("geo resolution job %s finished: %s", job_id, result)
    return result
