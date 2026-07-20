"""Plain data-transfer object for what an RERARegistryClient returns —
deliberately not the SQLAlchemy RERADetail model. A client knows nothing
about the database or about any particular company; RERAEnrichmentService is
the only place a RERARegistryRecord gets matched to a company and persisted.
Same separation discovery.models.DiscoveredListing draws for DiscoverySource.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RERARegistryRecord:
    registration_number: str
    registrant_name: str
    registrant_type: str | None = None
    registered_address: str | None = None
    registration_date: str | None = None
    expiry_date: str | None = None
    status: str | None = None
    raw: dict[str, Any] | None = None
