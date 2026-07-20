"""Creates the `scrape_jobs` row a RERA enrichment run is driven by. Kept
separate from `service.py` (which only knows how to *run* a job, not create
one) so an API endpoint can create RERA enrichment jobs without importing
Celery code — same split as `worker.discovery.jobs`/`worker.social.jobs`."""

import uuid

from corelib.enums import ScrapeJobStatus, ScrapeJobType
from corelib.models import ScrapeJob
from sqlalchemy.ext.asyncio import AsyncSession


async def create_rera_enrichment_job(
    session: AsyncSession, *, company_id: uuid.UUID, source_profile: str
) -> ScrapeJob:
    job = ScrapeJob(
        job_type=ScrapeJobType.RERA_ENRICHMENT.value,
        status=ScrapeJobStatus.PENDING.value,
        queue_name="enrichment",
        company_id=company_id,
        payload={"source_profile": source_profile},
    )
    session.add(job)
    await session.commit()
    return job
