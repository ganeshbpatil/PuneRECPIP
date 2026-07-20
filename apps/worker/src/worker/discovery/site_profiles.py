"""Declarative per-directory scraping config. One `DirectoryDiscoverySource`
engine (sources.py) drives every profile — adding a new real directory means
adding a `SiteProfile` here, not writing a new scraper class.

IMPORTANT: `EXAMPLE_PROFILE` below targets a hand-written local HTML fixture
(apps/worker/tests/fixtures/example_directory.html) used by the test suite —
it is a template proving the engine's fetch/paginate/parse/rate-limit/robots
pipeline end-to-end, not a verified scraper for any real, live business
directory. To point this at a real site (JustDial, Sulekha, IndiaMART, a RERA
agent directory, ...): inspect that site's actual current search-results HTML,
fill in the CSS selectors below to match it, and confirm the site's robots.txt
and terms of service permit automated access at the configured rate. Selectors
on real directories drift over time regardless of who wrote them; treat any
SiteProfile as needing periodic revalidation, not a one-time task.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SiteProfile:
    name: str
    domain: str
    search_url_template: str  # supports {keyword}, {location}, {page}
    result_selector: str
    name_selector: str
    link_selector: str | None = None
    phone_selector: str | None = None
    snippet_selector: str | None = None
    next_page_selector: str | None = None
    requests_per_second: float = 0.5
    link_is_href_attr: bool = True


EXAMPLE_PROFILE = SiteProfile(
    name="example_directory",
    domain="example-directory.test",
    search_url_template=(
        "https://example-directory.test/search?q={keyword}&loc={location}&page={page}"
    ),
    result_selector="div.listing",
    name_selector="h2.listing-name",
    link_selector="a.listing-website",
    phone_selector="span.listing-phone",
    snippet_selector="p.listing-snippet",
    next_page_selector="a.next-page",
    requests_per_second=0.5,
)

# Resolved by profile name from a discovery ScrapeJob's payload (see
# tasks/discovery.py). Add a real, verified profile here as one becomes
# available; nothing beyond EXAMPLE_PROFILE ships until then.
SITE_PROFILES: dict[str, SiteProfile] = {
    EXAMPLE_PROFILE.name: EXAMPLE_PROFILE,
}
