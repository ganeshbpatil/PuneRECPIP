"""Celery entrypoint for the `enrichment` queue's non-AI enrichment jobs
(Module 6 social discovery today; Module 7 RERA enrichment will land here
too — see docs/architecture/01-architecture.md's sequence diagram, which
groups social + RERA into the same `enrichment` queue). Not to be confused
with `worker.enrichment`, the Module 5 AI-extraction *business logic*
package, or `worker/tasks/extraction.py`, the Celery task that runs it on
the separate `extraction` queue.

Thin, sync wrapper — all real logic lives in SocialDiscoveryService so it
can be unit/integration-tested without Celery/Redis."""

import asyncio
import logging

from corelib.models import ScrapeJob
from sqlalchemy import select

from worker.celery_app import app
from worker.core.config import get_settings
from worker.core.db import get_session_factory
from worker.core.storage import get_object_storage
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
