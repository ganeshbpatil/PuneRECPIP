"""RERA enrichment (Module 7): looks up a company's registration in a state's
public RERA registry (queried by company name via an RERARegistryClient),
picks the best name-similarity match, and upserts a `RERADetail` row linking
`company_id` to that registration once the match clears a confidence bar.
No match above the bar is a normal, expected outcome (most companies won't
have a registered name close enough to a registry candidate, or the registry
has no candidates at all) — not a job failure.

Mirrors EnrichmentService's job lifecycle (Module 5) and reuses the same
pg_trgm `similarity()` scoring worker.enrichment.category_matching uses,
just applied to two ad-hoc strings (a company name and a candidate
registrant name) instead of an indexed column.
"""

import logging
from datetime import UTC, date, datetime

from corelib.enums import LogLevel, RERARegistrantType, RERAStatus, ScrapeJobStatus
from corelib.models import Company, JobLog, RERADetail, ScrapeJob
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from worker.rera.client import RERARegistryClient
from worker.rera.models import RERARegistryRecord

logger = logging.getLogger(__name__)

# pg_trgm similarity is 0 (nothing alike) to 1 (identical). Company legal
# names carry more distinguishing tokens than the short category labels
# category_matching.py scores (threshold 0.4 there), so this bar is higher —
# tuned to avoid linking two similarly-named-but-different real estate
# businesses ("Acme Realty Pune" vs "Acme Realty Estates") to the same
# registration, at the cost of missing some genuine matches with unusually
# different registered-vs-trading names. Revisit once run against real data.
MATCH_CONFIDENCE_THRESHOLD = 0.5


class RERAEnrichmentService:
    def __init__(self, session: AsyncSession, registry: RERARegistryClient):
        self._session = session
        self._registry = registry

    async def run(self, job: ScrapeJob) -> dict:
        job.status = ScrapeJobStatus.RUNNING.value
        if job.started_at is None:
            job.started_at = datetime.now(UTC)
        await self._session.commit()

        try:
            company = await self._load_company(job)
            candidates = await self._registry.search(company.name)
            match = await self._best_match(company, candidates)

            if match is None:
                await self._log(
                    job,
                    LogLevel.INFO,
                    "no confident RERA match found",
                    {"candidates_considered": len(candidates)},
                )
                result = {"matched": False, "candidates_considered": len(candidates)}
            else:
                record, confidence = match
                detail = await self._upsert_detail(company, record, confidence)
                await self._log(
                    job,
                    LogLevel.INFO,
                    "matched RERA registration",
                    {
                        "registration_number": detail.registration_number,
                        "confidence": confidence,
                    },
                )
                result = {
                    "matched": True,
                    "registration_number": detail.registration_number,
                    "confidence": confidence,
                    "candidates_considered": len(candidates),
                }

            job.status = ScrapeJobStatus.SUCCEEDED.value
        except Exception as exc:  # noqa: BLE001 - persist failure state before re-raising
            job.status = ScrapeJobStatus.FAILED.value
            job.error_message = str(exc)
            await self._log(
                job, LogLevel.ERROR, "RERA enrichment job failed", {"error": str(exc)}
            )
            job.finished_at = datetime.now(UTC)
            await self._session.commit()
            raise
        else:
            job.result = result
            job.finished_at = datetime.now(UTC)
            await self._session.commit()

        return result

    async def _load_company(self, job: ScrapeJob) -> Company:
        if job.company_id is None:
            raise ValueError("RERA enrichment jobs must have company_id set")
        company = (
            await self._session.execute(select(Company).where(Company.id == job.company_id))
        ).scalar_one_or_none()
        if company is None:
            raise ValueError(f"company {job.company_id} not found")
        return company

    async def _best_match(
        self, company: Company, candidates: list[RERARegistryRecord]
    ) -> tuple[RERARegistryRecord, float] | None:
        best_record: RERARegistryRecord | None = None
        best_score = 0.0
        for candidate in candidates:
            score = (
                await self._session.execute(
                    select(func.similarity(company.name, candidate.registrant_name))
                )
            ).scalar_one()
            if score > best_score:
                best_score = score
                best_record = candidate

        if best_record is None or best_score < MATCH_CONFIDENCE_THRESHOLD:
            return None
        return best_record, float(best_score)

    async def _upsert_detail(
        self, company: Company, record: RERARegistryRecord, confidence: float
    ) -> RERADetail:
        existing = (
            await self._session.execute(
                select(RERADetail).where(
                    RERADetail.registration_number == record.registration_number
                )
            )
        ).scalar_one_or_none()

        registrant_type = _normalize_registrant_type(record.registrant_type)
        status = _normalize_status(record.status)
        registration_date = _parse_date(record.registration_date)
        expiry_date = _parse_date(record.expiry_date)

        if existing is not None:
            existing.company_id = company.id
            existing.registrant_name = record.registrant_name
            existing.registrant_type = registrant_type
            existing.registered_address = record.registered_address
            existing.registration_date = registration_date
            existing.expiry_date = expiry_date
            existing.status = status
            existing.matched_confidence = confidence
            existing.raw_data = record.raw
            return existing

        detail = RERADetail(
            company_id=company.id,
            registration_number=record.registration_number,
            registrant_name=record.registrant_name,
            registrant_type=registrant_type,
            registered_address=record.registered_address,
            registration_date=registration_date,
            expiry_date=expiry_date,
            status=status,
            matched_confidence=confidence,
            raw_data=record.raw,
        )
        self._session.add(detail)
        await self._session.flush()
        return detail

    async def _log(self, job: ScrapeJob, level: LogLevel, message: str, context: dict) -> None:
        self._session.add(
            JobLog(scrape_job_id=job.id, level=level.value, message=message, context=context)
        )
        logger.log(_PY_LOG_LEVEL[level], "%s: %s", message, context)


def _normalize_registrant_type(value: str | None) -> str:
    if value and value.strip().lower().startswith("promot"):
        return RERARegistrantType.PROMOTER.value
    return RERARegistrantType.AGENT.value


def _normalize_status(value: str | None) -> str:
    if not value:
        return RERAStatus.ACTIVE.value
    normalized = value.strip().lower()
    if "expir" in normalized:
        return RERAStatus.EXPIRED.value
    if "cancel" in normalized:
        return RERAStatus.CANCELLED.value
    if "suspend" in normalized:
        return RERAStatus.SUSPENDED.value
    return RERAStatus.ACTIVE.value


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    logger.warning("could not parse RERA date %r with any known format", value)
    return None


_PY_LOG_LEVEL = {
    LogLevel.DEBUG: logging.DEBUG,
    LogLevel.INFO: logging.INFO,
    LogLevel.WARNING: logging.WARNING,
    LogLevel.ERROR: logging.ERROR,
    LogLevel.CRITICAL: logging.CRITICAL,
}
