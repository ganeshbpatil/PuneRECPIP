# Module 9 — Geographic Intelligence

**Status:** Implemented — schema (from Module 2), geocoding provider, resolution service, Celery task, and tests are in this PR.
**Depends on:** [Module 2 — Database](02-database.md) (`addresses.geom`, `service_areas.geom`, both PostGIS `Geography` columns), and [Module 5 — AI Enrichment](05-ai-enrichment.md), whose own docs named this module's primary backlog.

## What's in this module

- `apps/worker/src/worker/geo/provider.py` — `GeocodingProvider` Protocol, `GeocodeResult` DTO.
- `apps/worker/src/worker/geo/nominatim.py` — `NominatimGeocodingProvider`, a real client for the OpenStreetMap Nominatim Search API.
- `apps/worker/src/worker/geo/service.py` — `GeoIntelligenceService`, the resolution orchestrator.
- `apps/worker/src/worker/geo/jobs.py` — `create_geo_resolution_job`.
- `apps/worker/src/worker/tasks/geo.py` — `run_geo_resolution_job`, on the pre-existing `geo` queue (`celery_app.py` already routed `worker.tasks.geo.*` there since Module 1).

## What this module resolves, and why it's these two tables specifically

Two tables carry free-text location data nothing has yet turned into coordinates:

- **`addresses`** — a company's own office/branch addresses, collected during crawling (Module 4) and AI extraction (Module 5), with `latitude`/`longitude`/`geom` all nullable and mostly unset.
- **`service_areas`** — the localities a company says it serves, extracted by Module 5's AI pass. Module 5's own docs are explicit about this being left for Module 9: "`service_areas` rows with `area_type=neighbourhood` and no `city`/`geom` set as its primary backlog to resolve, rather than a schema Module 9 needs to build from scratch."

`GeoIntelligenceService` is per-company (like Modules 5–8): given a company, it geocodes every `Address` and `ServiceArea` row missing `geom`, using a `GeocodingProvider`.

## Why Nominatim, and why this is a different honesty situation than Module 7

Module 7 (RERA) couldn't build a real integration because no live state government portal was reachable *and* I had no confidently-verified knowledge of any specific portal's exact request/response contract — guessing at one would have meant fabricating something that likely wouldn't work.

Geocoding is a different situation: Nominatim (OpenStreetMap's search/geocoding API) is a free, keyless, extensively and stably documented public API (https://nominatim.org/release-docs/latest/api/Search/) whose request shape and JSON response shape I have solid, current, verifiable knowledge of — the kind of well-established API this session's knowledge is reliable on, the same category as the Anthropic/OpenAI SDKs Module 5 used. What's missing here isn't contract knowledge, it's the same thing that was missing in Modules 5–7: this sandbox's outbound proxy has no route to `nominatim.openstreetmap.org` (or any other geocoding provider) to make a live call.

So `NominatimGeocodingProvider` is real, complete client code — verified structurally against `httpx.MockTransport` with realistic, documented Nominatim response payloads (`tests/unit/test_nominatim.py`), the same pattern Module 5 used for `ClaudeExtractor`/`OpenAIExtractor` when no live credential was available. `GeoIntelligenceService`'s actual logic (which rows need resolving, how a result gets applied, PostGIS point construction) is tested fully against real Postgres/PostGIS with a `FakeGeocodingProvider` (`tests/integration/test_geo_intelligence_service.py`), and a manual end-to-end run proved the full pipeline through a real Redis broker and Celery worker against a local HTTP fixture standing in for Nominatim (the same approach Module 4 and Module 7 used for their own E2E runs against unreachable-from-here targets).

### Nominatim's usage policy is a real, binding constraint, not just an implementation detail

The shared public Nominatim instance has a published usage policy (https://operations.osmfoundation.org/policies/nominatim/): a descriptive `User-Agent` identifying the calling application is required, and the request rate is capped at 1/second. `NominatimGeocodingProvider` enforces both — `worker.net`'s shared `DomainRateLimiter` (the same rate limiter Modules 3/4/7 use) gates every request, and `geo_user_agent` in settings identifies this project. `base_url` is configurable specifically so a production deployment can point at a self-hosted Nominatim instance (or a paid provider) instead of leaning on the shared public one at any real volume — using the shared instance beyond light, respectful use would itself violate the policy this module is trying to comply with.

## Resolution logic

1. **Addresses**: every `Address` with `geom IS NULL` gets a query built from `locality, city, state, country` (whichever are set). A successful geocode sets `latitude`/`longitude`/`geom` (a real PostGIS `Geography` point, via `geoalchemy2`'s `WKTElement` — no `shapely` dependency needed for this), and fills in `city`/`state`/`postal_code` **only if not already set** — an address's own already-known values are never overwritten by a geocoder's guess.
2. **Service areas**: every `ServiceArea` with `geom IS NULL` gets a similar treatment, with one addition — Module 5's AI-extracted service areas are typically just a bare locality name ("Kothrud") with no `city`/`state`, and geocoding a bare Indian locality name alone is ambiguous (many locality names repeat across cities/states). Before falling back to anything, the service first checks whether this *company* already has a known city/state (from one of its own `Address` rows, geocoded or not) and anchors the query to that. Only when the company has no location context at all does it fall back to this platform's Pune-first default (`"<locality>, Pune, Maharashtra, India"`) — a documented limitation once the platform expands beyond Pune (see Recommendations).
3. **No match** is logged and skipped, not a job failure — consistent with Module 7's "no confident match is a normal outcome" precedent, since not every free-text location will resolve.
4. **Idempotent by construction**: only rows with `geom IS NULL` are ever considered, so re-running the job after a successful resolution does no work and makes no further geocoding calls (verified in `test_already_geocoded_address_is_not_reprocessed`).

## Why a real `Geography` point, not just numeric columns

`addresses`/`service_areas` already had plain `latitude`/`longitude` `Numeric` columns before this module; the point of also populating the GeoAlchemy2 `Geography` column (backed by a GIST index Module 2 already created) is that it makes "companies within N km of a point" or "companies inside this drawn polygon" — exactly the kind of query Module 11's search/map UI will need — a fast indexed spatial query instead of a full-table scan computing Haversine distance in application code.

## Testing

- **Unit** (`tests/unit/test_nominatim.py`): response parsing against realistic Nominatim JSON payloads, including the documented ambiguity in which "city-like" key is populated (`city` vs `town` vs `suburb` depending on place type), empty results, and malformed lat/lon.
- **Integration** (`tests/integration/test_geo_intelligence_service.py`), against real Postgres/PostGIS with a `FakeGeocodingProvider`: geocoding an address end-to-end with the result read back via a real `ST_AsText()` call (proving it's a genuine, queryable geography, not an opaque blob), existing city/state never being overwritten, a service area resolving via the company's own known city, the Pune-first fallback when a company has no location context at all, a no-match result being logged and skipped, and an already-geocoded row never being reprocessed or re-queried on a second run.
- **Manual end-to-end**: a real Redis broker and a real `celery worker` subprocess consuming the `geo` queue, with `geo_nominatim_base_url` pointed at a local `http.server` fixture (via the `GEO_NOMINATIM_BASE_URL` env var — no code or shipped-config change needed), dispatching `run_geo_resolution_job` via `.delay()` and confirming the persisted `addresses` row (city/state/postal_code/lat/lon *and* a real `ST_AsText(geom)` result) directly in Postgres.

## Recommendations / open questions

1. **The Pune-first fallback is a real limitation once this platform expands India-wide**, as the README says it's designed to. A company whose only service areas are bare locality names, discovered before any of its own addresses are known, will get geocoded against a wrong assumed city if that locality name happens to collide with a same-named locality elsewhere in India. The fix is naturally incremental: as soon as any address gets resolved (or a company's registered city becomes known some other way — RERA registered address, for instance), a re-run of this job stops needing the fallback for that company.
2. **`geo_requests_per_second` (1.0) reflects Nominatim's documented public-instance policy, not a tuned choice** — a self-hosted instance or paid provider could safely run faster; this default is a compliance floor, not a performance target.
3. **`google_maps_listings` is untouched by this module.** The schema has a dedicated table for it, but populating it requires a Google Maps Places API integration (credentialed, paid) that's a distinct data-source module from geographic *resolution* — this module resolves location text already collected elsewhere, it doesn't add a new discovery source. Worth scoping separately if Google Maps listing sync becomes a priority.
4. **No reverse-geocoding or address validation.** This module only forward-geocodes (text → point); it doesn't attempt to validate that a resolved point is plausible (e.g., actually within India/Maharashtra bounds) — a sanity-check bounding-box filter would be a cheap addition if bad geocodes turn out to be common against real data.
