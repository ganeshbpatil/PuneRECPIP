"""Duplicate detection (Module 8): given a company, finds other companies in
the database that are plausibly the same real-world business, scores each
candidate pair, and auto-merges the ones that clear a confidence bar.
Discovery (Module 3) already prevents saving an *exact* duplicate at
ingestion time (same domain or same name-slug); this module catches
near-duplicates that get in anyway — the same company discovered through two
different directories with slightly different name spellings, crawled under
`www.` vs bare-domain before domain normalization caught up, entered once
via discovery and once via a Google Maps/RERA sync, etc.

Scoring model: each "structural" signal — an exact match on website domain,
phone number, or email address — is strong, near-zero-false-positive
evidence on its own (two unrelated real estate businesses essentially never
share a phone number or email address by coincidence), so any single one of
those crosses AUTO_MERGE_THRESHOLD alone. RERA registration number is
deliberately *not* one of these signals despite being an equally strong
identifier in principle: `rera_details.registration_number` already has a
database-level UNIQUE constraint (Module 7), so two different companies can
never simultaneously hold a `RERADetail` row with the same number — there is
no "shared registration number" state for this module to detect. The
interesting case Module 7 already flagged (matching company Y's search
finds a registration number already linked to company X, silently
reassigning it) is closer to a two-`RERAEnrichmentService`-runs race than a
dedup signal, and needs its own conflict-handling design rather than being
folded into this scoring model — left as an open question below.

Name similarity (pg_trgm) is the opposite: real estate business names are
full of generic, widely-reused tokens ("Realty", "Properties", "Estates",
a locality name), so two genuinely different businesses can score high on
name alone. Its weight is capped low enough that name similarity by itself,
however high, never crosses the merge bar — it only pushes an already-
plausible structural match higher, or (documented in module docs as a known
limitation) misses a true duplicate that shares no structural signal yet.
That's a deliberate precision-over-recall choice: an incorrect merge folds
one real business's data into another's, which is worse than leaving two
duplicate rows unmerged for a later pass to catch.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from corelib.enums import ChangeSource, CompanyStatus, LogLevel, ScrapeJobStatus
from corelib.models import (
    ChangeHistory,
    Company,
    EmailAddress,
    JobLog,
    MergeHistory,
    PhoneNumber,
    ScrapeJob,
    Website,
)
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Loose, recall-oriented bar for even *considering* a company as a candidate
# — deliberately looser than any scoring weight below. Actual merge
# decisions are gated by the weighted composite score, not this bar; this
# only keeps the candidate set from being every row in the table.
NAME_CANDIDATE_THRESHOLD = 0.3

NAME_WEIGHT = 0.4
DOMAIN_WEIGHT = 0.6
PHONE_WEIGHT = 0.5
EMAIL_WEIGHT = 0.4

# Domain match (0.6) clears this alone; phone (0.5) or email (0.4) alone do
# not and need some corroboration (a second signal, or high name
# similarity) to cross it. Name similarity's 0.4 max contribution never
# clears it by itself. Untuned pending real cross-source data — see
# docs/modules/08-duplicate-detection.md.
AUTO_MERGE_THRESHOLD = 0.6

# Higher-progress statuses make a company the preferred merge target (more
# is likely known about it); MERGED/INACTIVE/REJECTED never win, and are
# already excluded from candidate generation.
_STATUS_RANK = {
    CompanyStatus.DISCOVERED.value: 0,
    CompanyStatus.CRAWLING.value: 1,
    CompanyStatus.CRAWLED.value: 2,
    CompanyStatus.ENRICHING.value: 3,
    CompanyStatus.ENRICHED.value: 4,
    CompanyStatus.VERIFIED.value: 5,
}


@dataclass(frozen=True, slots=True)
class CompanySignals:
    domains: set[str]
    phones: set[str]
    emails: set[str]


class DedupService:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def run(self, job: ScrapeJob) -> dict:
        job.status = ScrapeJobStatus.RUNNING.value
        if job.started_at is None:
            job.started_at = datetime.now(UTC)
        await self._session.commit()

        try:
            company = await self._load_company(job)

            if company.status == CompanyStatus.MERGED.value:
                await self._log(
                    job,
                    LogLevel.INFO,
                    "company is already merged, skipping dedup",
                    {"company_id": str(company.id)},
                )
                result = {"candidates_considered": 0, "merges": []}
            else:
                result = await self._dedup_company(job, company)

            job.status = ScrapeJobStatus.SUCCEEDED.value
        except Exception as exc:  # noqa: BLE001 - persist failure state before re-raising
            job.status = ScrapeJobStatus.FAILED.value
            job.error_message = str(exc)
            await self._log(job, LogLevel.ERROR, "dedup job failed", {"error": str(exc)})
            job.finished_at = datetime.now(UTC)
            await self._session.commit()
            raise
        else:
            job.result = result
            job.finished_at = datetime.now(UTC)
            await self._session.commit()

        return result

    async def _dedup_company(self, job: ScrapeJob, company: Company) -> dict:
        signals = await self._load_signals(company.id)
        candidates = await self._find_candidates(company, signals)

        merges = []
        for candidate in candidates:
            score, criteria = await self._score_pair(company, candidate, signals)

            if score < AUTO_MERGE_THRESHOLD:
                await self._log(
                    job,
                    LogLevel.DEBUG,
                    "candidate considered, not confident enough to merge",
                    {"candidate_company_id": str(candidate.id), "score": score, **criteria},
                )
                continue

            primary, duplicate = _pick_primary(company, candidate)
            await self._merge(job, primary, duplicate, score, criteria)
            merges.append(
                {
                    "primary_company_id": str(primary.id),
                    "duplicate_company_id": str(duplicate.id),
                    "score": score,
                }
            )

            if duplicate.id == company.id:
                # `company` itself just got merged away — it no longer
                # represents an active listing, so there's nothing left to
                # compare the remaining candidates against.
                break

        return {"candidates_considered": len(candidates), "merges": merges}

    async def _load_company(self, job: ScrapeJob) -> Company:
        if job.company_id is None:
            raise ValueError("dedup jobs must have company_id set")
        company = (
            await self._session.execute(select(Company).where(Company.id == job.company_id))
        ).scalar_one_or_none()
        if company is None:
            raise ValueError(f"company {job.company_id} not found")
        return company

    async def _load_signals(self, company_id) -> CompanySignals:
        domains = set(
            (
                await self._session.execute(
                    select(Website.domain).where(Website.company_id == company_id)
                )
            )
            .scalars()
            .all()
        )
        phones = set(
            (
                await self._session.execute(
                    select(PhoneNumber.phone_number).where(
                        PhoneNumber.company_id == company_id
                    )
                )
            )
            .scalars()
            .all()
        )
        emails = set(
            (
                await self._session.execute(
                    select(EmailAddress.email).where(EmailAddress.company_id == company_id)
                )
            )
            .scalars()
            .all()
        )
        return CompanySignals(domains=domains, phones=phones, emails=emails)

    async def _find_candidates(
        self, company: Company, signals: CompanySignals
    ) -> list[Company]:
        conditions = [func.similarity(Company.name, company.name) > NAME_CANDIDATE_THRESHOLD]
        if signals.domains:
            conditions.append(
                Company.id.in_(
                    select(Website.company_id).where(Website.domain.in_(signals.domains))
                )
            )
        if signals.phones:
            conditions.append(
                Company.id.in_(
                    select(PhoneNumber.company_id).where(
                        PhoneNumber.phone_number.in_(signals.phones),
                        PhoneNumber.company_id.is_not(None),
                    )
                )
            )
        if signals.emails:
            conditions.append(
                Company.id.in_(
                    select(EmailAddress.company_id).where(
                        EmailAddress.email.in_(signals.emails),
                        EmailAddress.company_id.is_not(None),
                    )
                )
            )
        stmt = select(Company).where(
            Company.id != company.id,
            Company.status != CompanyStatus.MERGED.value,
            or_(*conditions),
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def _score_pair(
        self, company: Company, candidate: Company, company_signals: CompanySignals
    ) -> tuple[float, dict]:
        candidate_signals = await self._load_signals(candidate.id)
        name_similarity = (
            await self._session.execute(
                select(func.similarity(company.name, candidate.name))
            )
        ).scalar_one()

        domain_match = bool(company_signals.domains & candidate_signals.domains)
        phone_match = bool(company_signals.phones & candidate_signals.phones)
        email_match = bool(company_signals.emails & candidate_signals.emails)

        score = float(name_similarity) * NAME_WEIGHT
        if domain_match:
            score += DOMAIN_WEIGHT
        if phone_match:
            score += PHONE_WEIGHT
        if email_match:
            score += EMAIL_WEIGHT
        score = min(score, 1.0)

        criteria = {
            "name_similarity": round(float(name_similarity), 3),
            "domain_match": domain_match,
            "phone_match": phone_match,
            "email_match": email_match,
        }
        return score, criteria

    async def _merge(
        self, job: ScrapeJob, primary: Company, duplicate: Company, score: float, criteria: dict
    ) -> None:
        old_status = duplicate.status
        duplicate.is_duplicate = True
        duplicate.status = CompanyStatus.MERGED.value
        duplicate.merged_into_company_id = primary.id

        self._session.add(
            MergeHistory(
                primary_company_id=primary.id,
                duplicate_company_id=duplicate.id,
                match_score=score,
                match_criteria=criteria,
                merged_by_job_id=job.id,
            )
        )
        self._session.add(
            ChangeHistory(
                entity_type="company",
                entity_id=duplicate.id,
                field_name="status",
                old_value={"status": old_status},
                new_value={"status": CompanyStatus.MERGED.value},
                change_source=ChangeSource.DEDUP_MERGE.value,
                changed_by_job_id=job.id,
            )
        )
        await self._log(
            job,
            LogLevel.INFO,
            "merged duplicate company",
            {
                "primary_company_id": str(primary.id),
                "duplicate_company_id": str(duplicate.id),
                "score": score,
                **criteria,
            },
        )

    async def _log(self, job: ScrapeJob, level: LogLevel, message: str, context: dict) -> None:
        self._session.add(
            JobLog(scrape_job_id=job.id, level=level.value, message=message, context=context)
        )
        logger.log(_PY_LOG_LEVEL[level], "%s: %s", message, context)


def _pick_primary(a: Company, b: Company) -> tuple[Company, Company]:
    """Returns (primary, duplicate). The company further along the pipeline
    (more likely to have real crawled/enriched data attached) wins; ties
    break toward the older record, on the theory that it was discovered
    first and is more likely the canonical listing."""
    rank_a = _STATUS_RANK.get(a.status, 0)
    rank_b = _STATUS_RANK.get(b.status, 0)
    if rank_a != rank_b:
        return (a, b) if rank_a > rank_b else (b, a)

    time_a = a.discovered_at or a.created_at
    time_b = b.discovered_at or b.created_at
    return (a, b) if time_a <= time_b else (b, a)


_PY_LOG_LEVEL = {
    LogLevel.DEBUG: logging.DEBUG,
    LogLevel.INFO: logging.INFO,
    LogLevel.WARNING: logging.WARNING,
    LogLevel.ERROR: logging.ERROR,
    LogLevel.CRITICAL: logging.CRITICAL,
}
