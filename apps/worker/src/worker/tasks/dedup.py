"""Celery entrypoint for dedup jobs. The task itself is a thin, sync
wrapper — all real logic lives in DedupService so it can be unit/
integration-tested without Celery/Redis."""

import asyncio
import logging

from corelib.models import ScrapeJob
from sqlalchemy import select

from worker.celery_app import app
from worker.core.db import get_session_factory
from worker.dedup.service import DedupService

logger = logging.getLogger(__name__)


@app.task(
    name="worker.tasks.dedup.run_dedup_job",
    bind=True,
    autoretry_for=(ConnectionError, OSError),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def run_dedup_job(self, job_id: str) -> dict:
    return asyncio.run(_run_dedup_job_async(job_id))


async def _run_dedup_job_async(job_id: str) -> dict:
    session_factory = get_session_factory()

    async with session_factory() as session:
        job = (
            await session.execute(select(ScrapeJob).where(ScrapeJob.id == job_id))
        ).scalar_one()
        service = DedupService(session)
        result = await service.run(job)

    logger.info("dedup job %s finished: %s", job_id, result)
    return result
