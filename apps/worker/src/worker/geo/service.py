"""Geographic intelligence (Module 9): resolves the free-text location data
earlier modules collected — company `Address` rows and AI-extracted
`ServiceArea` rows (Module 5) — into structured city/state and a real
PostGIS `Geography` point, via a `GeocodingProvider`. Module 5's own docs
named this exact backlog: `service_areas` rows with `area_type=neighbourhood`
and no `city`/`geom` set, left for this module to resolve rather than a
schema it needs to build from scratch.

Per-company, like Modules 5-8: geocodes every `Address`/`ServiceArea` missing
`geom` for one company. Storing a real `Geography` point (not just plain
lat/lon numeric columns) means Module 11's "companies within N km" or
"companies inside this polygon" queries can use the GIST index Module 2
already created, instead of scanning and computing distance in application
code.
"""

import logging
from datetime import UTC, datetime

from corelib.enums import LogLevel, ScrapeJobStatus
from corelib.models import Address, Company, JobLog, ScrapeJob, ServiceArea
from geoalchemy2.elements import WKTElement
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from worker.geo.provider import GeocodeResult, GeocodingProvider

logger = logging.getLogger(__name__)


class GeoIntelligenceService:
    def __init__(self, session: AsyncSession, provider: GeocodingProvider):
        self._session = session
        self._provider = provider

    async def run(self, job: ScrapeJob) -> dict:
        job.status = ScrapeJobStatus.RUNNING.value
        if job.started_at is None:
            job.started_at = datetime.now(UTC)
        await self._session.commit()

        try:
            company = await self._load_company(job)
            addresses_geocoded = await self._resolve_addresses(job, company)
            service_areas_resolved = await self._resolve_service_areas(job, company)
            result = {
                "addresses_geocoded": addresses_geocoded,
                "service_areas_resolved": service_areas_resolved,
            }
            job.status = ScrapeJobStatus.SUCCEEDED.value
        except Exception as exc:  # noqa: BLE001 - persist failure state before re-raising
            job.status = ScrapeJobStatus.FAILED.value
            job.error_message = str(exc)
            await self._log(
                job, LogLevel.ERROR, "geo resolution job failed", {"error": str(exc)}
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
            raise ValueError("geo resolution jobs must have company_id set")
        company = (
            await self._session.execute(select(Company).where(Company.id == job.company_id))
        ).scalar_one_or_none()
        if company is None:
            raise ValueError(f"company {job.company_id} not found")
        return company

    async def _resolve_addresses(self, job: ScrapeJob, company: Company) -> int:
        addresses = (
            await self._session.execute(
                select(Address).where(
                    Address.company_id == company.id, Address.geom.is_(None)
                )
            )
        ).scalars().all()

        resolved = 0
        for address in addresses:
            query = _address_query(address)
            if query is None:
                continue

            result = await self._provider.geocode(query)
            if result is None:
                await self._log(
                    job,
                    LogLevel.INFO,
                    "no geocode match for address",
                    {"address_id": str(address.id), "query": query},
                )
                continue

            _apply_to_address(address, result)
            resolved += 1
            await self._log(
                job,
                LogLevel.INFO,
                "geocoded address",
                {"address_id": str(address.id), "city": result.city},
            )

        return resolved

    async def _resolve_service_areas(self, job: ScrapeJob, company: Company) -> int:
        service_areas = (
            await self._session.execute(
                select(ServiceArea).where(
                    ServiceArea.company_id == company.id, ServiceArea.geom.is_(None)
                )
            )
        ).scalars().all()
        if not service_areas:
            return 0

        fallback_city, fallback_state = await self._infer_company_city_state(company.id)

        resolved = 0
        for area in service_areas:
            query = _service_area_query(area, fallback_city, fallback_state)
            if query is None:
                continue

            result = await self._provider.geocode(query)
            if result is None:
                await self._log(
                    job,
                    LogLevel.INFO,
                    "no geocode match for service area",
                    {"service_area_id": str(area.id), "query": query},
                )
                continue

            _apply_to_service_area(area, result)
            resolved += 1
            await self._log(
                job,
                LogLevel.INFO,
                "resolved service area",
                {"service_area_id": str(area.id), "city": result.city},
            )

        return resolved

    async def _infer_company_city_state(
        self, company_id
    ) -> tuple[str | None, str | None]:
        """Prefer a city/state this company is already known to be in (from
        its own address, geocoded or not) over guessing — only falls back to
        this platform's Pune-first default when nothing is known at all."""
        row = (
            await self._session.execute(
                select(Address.city, Address.state)
                .where(Address.company_id == company_id, Address.city.is_not(None))
                .order_by(Address.is_primary.desc())
                .limit(1)
            )
        ).first()
        return (row.city, row.state) if row else (None, None)

    async def _log(self, job: ScrapeJob, level: LogLevel, message: str, context: dict) -> None:
        self._session.add(
            JobLog(scrape_job_id=job.id, level=level.value, message=message, context=context)
        )
        logger.log(_PY_LOG_LEVEL[level], "%s: %s", message, context)


def _address_query(address: Address) -> str | None:
    parts = [p for p in (address.locality, address.city, address.state, address.country) if p]
    return ", ".join(parts) if parts else None


def _service_area_query(
    area: ServiceArea, fallback_city: str | None, fallback_state: str | None
) -> str | None:
    parts = [p for p in (area.locality, area.city, area.state) if p]
    if not parts:
        return None

    # Module 5's AI extraction typically leaves service_areas with only
    # `locality` set (a bare neighbourhood name) — geocoding "Kothrud" alone
    # is ambiguous (multiple places share common Indian locality names), so
    # anchor it to context. Prefer the company's own known city/state; only
    # fall back to this platform's Pune-first default when nothing else is
    # known about the company at all (documented limitation once this
    # expands beyond Pune — see module docs).
    if area.city is None and area.state is None:
        if fallback_city or fallback_state:
            parts.extend(p for p in (fallback_city, fallback_state) if p)
        else:
            parts.extend(["Pune", "Maharashtra"])
    parts.append("India")
    return ", ".join(parts)


def _to_point(result: GeocodeResult) -> WKTElement:
    return WKTElement(f"POINT({result.longitude} {result.latitude})", srid=4326)


def _apply_to_address(address: Address, result: GeocodeResult) -> None:
    address.latitude = result.latitude
    address.longitude = result.longitude
    address.geom = _to_point(result)
    if not address.city and result.city:
        address.city = result.city
    if not address.state and result.state:
        address.state = result.state
    if not address.postal_code and result.postal_code:
        address.postal_code = result.postal_code


def _apply_to_service_area(area: ServiceArea, result: GeocodeResult) -> None:
    area.geom = _to_point(result)
    if not area.city and result.city:
        area.city = result.city
    if not area.state and result.state:
        area.state = result.state


_PY_LOG_LEVEL = {
    LogLevel.DEBUG: logging.DEBUG,
    LogLevel.INFO: logging.INFO,
    LogLevel.WARNING: logging.WARNING,
    LogLevel.ERROR: logging.ERROR,
    LogLevel.CRITICAL: logging.CRITICAL,
}
