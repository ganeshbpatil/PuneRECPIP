"""Creates the `scrape_jobs` row a geo resolution run is driven by. Kept
separate from `service.py` (which only knows how to *run* a job, not create
one) so an API endpoint can create geo resolution jobs without importing
Celery code — same split as `worker.discovery.jobs`/`worker.social.jobs`/
`worker.rera.jobs`/`worker.dedup.jobs`."""

import uuid

from corelib.enums import ScrapeJobStatus, ScrapeJobType
from corelib.models import ScrapeJob
from sqlalchemy.ext.asyncio import AsyncSession


async def create_geo_resolution_job(session: AsyncSession, *, company_id: uuid.UUID) -> ScrapeJob:
    job = ScrapeJob(
        job_type=ScrapeJobType.GEO_RESOLUTION.value,
        status=ScrapeJobStatus.PENDING.value,
        queue_name="geo",
        company_id=company_id,
    )
    session.add(job)
    await session.commit()
    return job
