"""Declarative per-state RERA registry search config. India's RERA is a
state-by-state regulator (MahaRERA for Maharashtra, K-RERA for Karnataka,
...), each with its own portal and, likely, its own public search response
shape — so, same reasoning as worker.discovery.site_profiles.SiteProfile,
one generic HTTP+JSON client (client.py) is driven entirely by a
RERASourceProfile's field mapping, and adding a new state's registry is
configuration, not code.

IMPORTANT: EXAMPLE_PROFILE targets a hand-written local JSON fixture used by
the test suite — a template proving the fetch/rate-limit/robots/parse
pipeline end-to-end, not a verified integration with any real state's live
RERA portal. This sandbox has no network access to any government portal
(the outbound proxy allowlists only pypi.org/npmjs.org/anthropic.com) to
inspect one against, so none ships pre-configured. To point this at a real
registry: inspect that portal's actual public search API response, fill in
the dotted-path `results_path`/`field_map` below to match it, and confirm
the portal's terms of use permit automated access at the configured rate —
exactly the one-time, per-source verification work
worker/discovery/site_profiles.py already calls out for directory sources.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RERASourceProfile:
    name: str
    state: str
    domain: str
    search_url_template: str  # supports {query}, {page}
    # Dotted path to the list of result objects within the parsed JSON
    # response body, e.g. "data.results"; "" if the response body itself is
    # the list.
    results_path: str
    # RERARegistryRecord field name -> dotted path to that value within each
    # result object, e.g. {"registration_number": "regNo"}. Only
    # "registration_number" and "registrant_name" are required for a result
    # to be usable; everything else is best-effort.
    field_map: dict[str, str] = field(default_factory=dict)
    requests_per_second: float = 0.5


EXAMPLE_PROFILE = RERASourceProfile(
    name="example_rera_registry",
    state="example",
    domain="example-rera-registry.test",
    search_url_template=(
        "https://example-rera-registry.test/api/search?name={query}&page={page}"
    ),
    results_path="data.results",
    field_map={
        "registration_number": "registrationNo",
        "registrant_name": "applicantName",
        "registrant_type": "category",
        "registered_address": "address",
        "registration_date": "regDate",
        "expiry_date": "validTill",
        "status": "status",
    },
    requests_per_second=0.5,
)

# Resolved by profile name from a rera_enrichment ScrapeJob's payload (see
# tasks/enrichment.py). Add a real, verified profile here as one becomes
# available; nothing beyond EXAMPLE_PROFILE ships until then.
RERA_SOURCE_PROFILES: dict[str, RERASourceProfile] = {
    EXAMPLE_PROFILE.name: EXAMPLE_PROFILE,
}
