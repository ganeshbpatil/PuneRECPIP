"""Plain data-transfer object and provider interface for geocoding — a
free-text location string in, a resolved point + address breakdown out.
Deliberately provider-agnostic: `worker/geo/nominatim.py` is the one real
implementation today, but nothing in `GeoIntelligenceService` depends on
Nominatim specifically, the same dependency-injection shape
`worker.enrichment.extractors.AIExtractor` uses for swappable AI providers.
"""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class GeocodeResult:
    latitude: float
    longitude: float
    display_name: str
    city: str | None = None
    state: str | None = None
    country: str | None = None
    postal_code: str | None = None
    raw: dict[str, Any] | None = None


class GeocodingProvider(Protocol):
    async def geocode(self, query: str) -> GeocodeResult | None: ...
