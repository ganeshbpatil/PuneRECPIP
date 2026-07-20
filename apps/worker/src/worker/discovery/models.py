"""Plain data-transfer objects for what a DiscoverySource returns — deliberately
not SQLAlchemy models. A source knows nothing about the database; DiscoveryService
is the only place a DiscoveredListing gets turned into a Company/Website row."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SearchQuery:
    keyword: str
    location: str


@dataclass(frozen=True, slots=True)
class DiscoveredListing:
    name: str
    website_url: str | None = None
    phone_raw: str | None = None
    snippet: str | None = None
    source_listing_url: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryPage:
    listings: list[DiscoveredListing]
    has_next: bool
