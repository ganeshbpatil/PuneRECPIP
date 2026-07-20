"""Creates the `scrape_jobs` row a social discovery run is driven by. Kept
separate from `service.py` (which only knows how to *run* a job, not create
one) so an API endpoint can create social discovery jobs without importing
Celery code — same split as `worker.discovery.jobs`."""

import uuid

from corelib.enums import ScrapeJobStatus, ScrapeJobType
from corelib.models import ScrapeJob
from sqlalchemy.ext.asyncio import AsyncSession


async def create_social_discovery_job(session: AsyncSession, *, company_id: uuid.UUID) -> ScrapeJob:
    job = ScrapeJob(
        job_type=ScrapeJobType.SOCIAL_ENRICHMENT.value,
        status=ScrapeJobStatus.PENDING.value,
        queue_name="enrichment",
        company_id=company_id,
    )
    session.add(job)
    await session.commit()
    return job
