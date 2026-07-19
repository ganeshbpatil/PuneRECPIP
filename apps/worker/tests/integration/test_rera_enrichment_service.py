"""RERAEnrichmentService against real Postgres — pg_trgm's similarity()
scoring the match quality is a real database feature, same rationale as
test_category_matching.py. The registry client is the one faked dependency
here (this sandbox has no network access to any real state RERA portal —
see worker/rera/profiles.py); FakeRERARegistryClient stands in for it,
mirroring the FakeAIExtractor/FakeEmbeddingProvider pattern used for
Module 5's EnrichmentService tests.
"""

import pytest
from corelib.enums import RERARegistrantType, RERAStatus, ScrapeJobStatus, ScrapeJobType
from corelib.models import Company, JobLog, RERADetail, ScrapeJob
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from worker.rera.models import RERARegistryRecord
from worker.rera.service import RERAEnrichmentService

pytestmark = pytest.mark.asyncio


class FakeRERARegistryClient:
    def __init__(self, records: list[RERARegistryRecord]):
        self._records = records
        self.queries: list[str] = []

    async def search(self, query: str) -> list[RERARegistryRecord]:
        self.queries.append(query)
        return self._records


async def _make_company(session: AsyncSession, name: str, slug: str) -> Company:
    company = Company(name=name, slug=slug)
    session.add(company)
    await session.flush()
    return company


async def _make_job(session: AsyncSession, company: Company) -> ScrapeJob:
    job = ScrapeJob(
        job_type=ScrapeJobType.RERA_ENRICHMENT.value,
        status=ScrapeJobStatus.PENDING.value,
        company_id=company.id,
    )
    session.add(job)
    await session.commit()
    return job


async def test_confident_match_creates_linked_rera_detail(session: AsyncSession):
    company = await _make_company(session, "Acme Realty Pune", "acme-realty-pune-rera-test")
    job = await _make_job(session, company)
    registry = FakeRERARegistryClient(
        [
            RERARegistryRecord(
                registration_number="P52100012345-rera-test",
                registrant_name="Acme Realty Pune",
                registrant_type="Agent",
                registered_address="FC Road, Pune",
                registration_date="2019-04-01",
                expiry_date="2024-03-31",
                status="Active",
                raw={"registrationNo": "P52100012345-rera-test"},
            )
        ]
    )

    result = await RERAEnrichmentService(session, registry).run(job)

    assert job.status == ScrapeJobStatus.SUCCEEDED.value
    assert result["matched"] is True
    assert result["registration_number"] == "P52100012345-rera-test"
    assert result["confidence"] == pytest.approx(1.0)

    detail = (
        await session.execute(
            select(RERADetail).where(
                RERADetail.registration_number == "P52100012345-rera-test"
            )
        )
    ).scalar_one()
    assert detail.company_id == company.id
    assert detail.registrant_type == RERARegistrantType.AGENT.value
    assert detail.status == RERAStatus.ACTIVE.value
    assert detail.registration_date.isoformat() == "2019-04-01"
    assert detail.expiry_date.isoformat() == "2024-03-31"
    assert float(detail.matched_confidence) == pytest.approx(1.0)
    assert detail.raw_data == {"registrationNo": "P52100012345-rera-test"}

    assert registry.queries == ["Acme Realty Pune"]

    logs = (
        await session.execute(select(JobLog).where(JobLog.scrape_job_id == job.id))
    ).scalars().all()
    assert any("matched RERA registration" in log.message for log in logs)


async def test_promoter_and_non_standard_date_format_normalized(session: AsyncSession):
    company = await _make_company(
        session, "Baner Broker Associates", "baner-broker-associates-rera-test"
    )
    job = await _make_job(session, company)
    registry = FakeRERARegistryClient(
        [
            RERARegistryRecord(
                registration_number="P52100067890-rera-test",
                registrant_name="Baner Broker Associates",
                registrant_type="Promoter",
                registration_date="01-06-2020",
                expiry_date="31-05-2025",
                status="Expired",
            )
        ]
    )

    await RERAEnrichmentService(session, registry).run(job)

    detail = (
        await session.execute(
            select(RERADetail).where(
                RERADetail.registration_number == "P52100067890-rera-test"
            )
        )
    ).scalar_one()
    assert detail.registrant_type == RERARegistrantType.PROMOTER.value
    assert detail.status == RERAStatus.EXPIRED.value
    assert detail.registration_date.isoformat() == "2020-06-01"
    assert detail.expiry_date.isoformat() == "2025-05-31"


async def test_no_candidates_close_enough_does_not_match(session: AsyncSession):
    company = await _make_company(session, "Acme Realty Pune", "acme-no-match-rera-test")
    job = await _make_job(session, company)
    registry = FakeRERARegistryClient(
        [
            RERARegistryRecord(
                registration_number="P52100011111-rera-test",
                registrant_name="Totally Different Business Name Ltd",
            )
        ]
    )

    result = await RERAEnrichmentService(session, registry).run(job)

    assert job.status == ScrapeJobStatus.SUCCEEDED.value
    assert result["matched"] is False
    assert result["candidates_considered"] == 1

    count = (
        await session.execute(
            select(RERADetail).where(
                RERADetail.registration_number == "P52100011111-rera-test"
            )
        )
    ).scalar_one_or_none()
    assert count is None


async def test_no_candidates_at_all_succeeds_unmatched(session: AsyncSession):
    company = await _make_company(session, "Nobody Realty", "nobody-realty-rera-test")
    job = await _make_job(session, company)
    registry = FakeRERARegistryClient([])

    result = await RERAEnrichmentService(session, registry).run(job)

    assert job.status == ScrapeJobStatus.SUCCEEDED.value
    assert result == {"matched": False, "candidates_considered": 0}


async def test_best_of_multiple_candidates_is_chosen(session: AsyncSession):
    company = await _make_company(session, "Acme Realty Pune", "acme-best-match-rera-test")
    job = await _make_job(session, company)
    registry = FakeRERARegistryClient(
        [
            RERARegistryRecord(
                registration_number="P52100022222-rera-test",
                registrant_name="Zenith Estates",
            ),
            RERARegistryRecord(
                registration_number="P52100033333-rera-test",
                registrant_name="Acme Realty Pune",
            ),
        ]
    )

    result = await RERAEnrichmentService(session, registry).run(job)

    assert result["matched"] is True
    assert result["registration_number"] == "P52100033333-rera-test"


async def test_rerun_relinks_existing_unlinked_registry_record(session: AsyncSession):
    """RERADetail.company_id is nullable by design (a registry record can
    exist before being matched to a company — see the model docstring). A
    later run against the same registration_number should link it rather
    than create a duplicate row."""
    company = await _make_company(session, "Acme Realty Pune", "acme-relink-rera-test")
    session.add(
        RERADetail(
            company_id=None,
            registration_number="P52100044444-rera-test",
            registrant_name="Acme Realty Pune",
        )
    )
    await session.flush()
    job = await _make_job(session, company)
    registry = FakeRERARegistryClient(
        [
            RERARegistryRecord(
                registration_number="P52100044444-rera-test",
                registrant_name="Acme Realty Pune",
                status="Active",
            )
        ]
    )

    await RERAEnrichmentService(session, registry).run(job)

    details = (
        await session.execute(
            select(RERADetail).where(
                RERADetail.registration_number == "P52100044444-rera-test"
            )
        )
    ).scalars().all()
    assert len(details) == 1
    assert details[0].company_id == company.id
