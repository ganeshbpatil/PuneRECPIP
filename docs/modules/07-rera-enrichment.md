# Module 7 — Public RERA Enrichment

**Status:** Implemented — schema (from Module 2), registry client, matching service, Celery task, and tests are in this PR.
**Depends on:** [Module 2 — Database](02-database.md) (`rera_details`), and (loosely) [Module 3 — Company Discovery](03-discovery.md), since this module enriches already-discovered companies rather than discovering new ones.

## What's in this module

- `apps/worker/src/worker/rera/profiles.py` — `RERASourceProfile`, declarative per-state registry search config.
- `apps/worker/src/worker/rera/client.py` — `HTTPRERARegistryClient`, a generic HTTP+JSON client driven by a profile.
- `apps/worker/src/worker/rera/models.py` — `RERARegistryRecord`, the plain DTO a client returns.
- `apps/worker/src/worker/rera/service.py` — `RERAEnrichmentService`, the matching orchestrator.
- `apps/worker/src/worker/rera/jobs.py` — `create_rera_enrichment_job`.
- `apps/worker/src/worker/tasks/enrichment.py` — `run_rera_enrichment_job`, added alongside Module 6's `run_social_discovery_job` on the same `enrichment` queue (the queue Module 1's architecture diagram already assigned to social + RERA).

## Why this is a generic, config-driven client rather than a MahaRERA scraper

India's RERA is a state-by-state regulator — MahaRERA for Maharashtra (the immediately relevant one, since this platform is Pune-first), K-RERA for Karnataka, and so on for every other state, each running its own portal with, presumably, its own request/response shape. Two honest constraints shaped this module's design, the same two that shaped Module 6's:

1. **Sandbox reachability.** This sandbox's outbound network proxy allowlists only `pypi.org`, `npmjs.org`, and `anthropic.com` — no state government portal is reachable from here to inspect its actual live search API.
2. **No verified knowledge of the real contract.** Even setting reachability aside, I don't have confidently-verified, current knowledge of any specific state RERA portal's exact endpoint URL, request parameters, or response JSON/HTML shape. Writing a scraper against guessed selectors or a guessed API contract and presenting it as "the MahaRERA integration" would be fabricating something that likely wouldn't work against the real site — worse than not building it, since it would look done without being done.

**What this module does instead:** it follows the exact precedent Module 3 already set for the same problem (directory sites for discovery) — `worker/discovery/site_profiles.py`'s `SiteProfile` pattern. One generic engine (`HTTPRERARegistryClient`) does the fetching, rate limiting, robots.txt compliance, retrying, and JSON field-mapping; a `RERASourceProfile` declares, per state, the search URL template and a dotted-path `field_map` from that state's actual response shape into `RERARegistryRecord`'s fields. `EXAMPLE_PROFILE` is a template proving the pipeline end-to-end against a hand-written JSON fixture, not a working MahaRERA integration. Turning this into a real MahaRERA (or any other state's) integration is a one-time, config-only task once someone can inspect that portal's real response — no code changes needed, same as adding a new discovery directory.

This also happens to be the *architecturally correct* answer independent of the sandbox's constraints: the README states this platform is "Pune-first, designed to expand across India," and different states will need different registry configs regardless of what could be verified from any one development environment.

## How RERA enrichment works

1. `RERAEnrichmentService.run(job)` loads the company for `job.company_id`.
2. Calls the configured `RERARegistryClient.search(company.name)`, which fetches from the state registry per the resolved `RERASourceProfile` (rate-limited per domain, robots.txt-checked, retried on transient failures — the same `worker.net` plumbing Module 3's `DirectoryDiscoverySource` uses).
3. Scores every returned candidate's `registrant_name` against the company's name using Postgres's real `pg_trgm` `similarity()` function (same mechanism Module 5's category matching uses, just scoring two ad-hoc strings instead of an indexed column) and keeps the highest-scoring one.
4. If the best score clears `MATCH_CONFIDENCE_THRESHOLD` (0.5 — see the constant's docstring for the reasoning), upserts a `RERADetail` row: creates one if `registration_number` is new, or updates and links an existing *unlinked* one (`RERADetail.company_id` is nullable by design — a registry record can already exist from a prior sync before it's matched to any company, per the model's own docstring). Registrant type and status free text are normalized against `RERARegistrantType`/`RERAStatus`; registration/expiry dates are parsed against a few common formats.
5. No confident match is a normal, expected success outcome (`{"matched": false, "candidates_considered": N}`), not a job failure — most searches won't return a close enough name, and that's not an error.

## A note on match confidence and false positives

Linking the wrong RERA registration to a company would be worse than not linking one at all — it would attach someone else's legal registration details to a business. The 0.5 pg_trgm threshold is deliberately more conservative than category matching's 0.4 (company legal names carry more distinguishing tokens than short category labels, so a real match should score noticeably higher), but it's still an untuned default pending real registry data. A registered legal name that differs meaningfully from a company's commonly-used trading name (a real, common pattern) could legitimately fail to match — that's a recall/precision tradeoff intentionally biased toward precision here, worth revisiting once this runs against a real state's data.

## Testing

- **Unit** (`tests/unit/test_rera_client.py`): field-mapping against a realistic JSON fixture (via `httpx.MockTransport`, same style as Module 3's `test_sources.py`), a malformed result missing required fields being skipped rather than crashing the page, pagination stopping on an empty page, and robots.txt disallow raising.
- **Integration** (`tests/integration/test_rera_enrichment_service.py`), against real Postgres (real `pg_trgm` similarity scoring) with a `FakeRERARegistryClient` standing in for the network client: a confident match creating a linked `RERADetail`, registrant-type/date-format normalization, no-match-above-threshold *not* creating a row, zero candidates succeeding as unmatched, best-of-multiple-candidates selection, and relinking a pre-existing *unlinked* registry record to a company on a later run.
- **Manual end-to-end**: a real Redis broker and a real `celery worker` subprocess consuming the `enrichment` queue, with `EXAMPLE_PROFILE` temporarily pointed at a local `http.server` fixture standing in for a state portal (the same approach Module 4 used for its own manual E2E run, for the same reason — no real target is reachable from here). Dispatched `run_rera_enrichment_job` via `.delay()` and confirmed the persisted `rera_details` row and `scrape_jobs.result` directly in Postgres. The fixture-pointing edit was reverted before committing — nothing in the shipped `EXAMPLE_PROFILE` points at a local address.

## Recommendations / open questions

1. **No real state profile ships yet.** Wiring up MahaRERA (or another state) for real requires someone to inspect that portal's actual live search response and fill in `field_map` — flagged here so it isn't mistaken for an oversight later. Given the standing "public data only, no login-gated scraping" constraint (Module 1's architecture doc, §8.6), that inspection should also confirm the portal's terms of use permit automated access at whatever rate is configured.
2. **`MATCH_CONFIDENCE_THRESHOLD` (0.5) is untuned**, like Module 5's category-matching threshold and Module 6's blacklist — a reasonable starting bar, not an empirically-validated one; revisit once real registry data is available.
3. **Conflicting re-match not handled specially.** If a later run links a `registration_number` that's already linked to a *different* company, this module's upsert simply overwrites the link (last-match-wins) rather than flagging the conflict. Real registration-number collisions across two distinct discovered companies should be rare, but worth a dedicated check if it turns out not to be — plausibly Module 8 (Duplicate Detection) territory, since a shared RERA registration number is itself a strong dedup signal.
4. **Bulk registry ingest is out of scope here.** This module is company-driven (given a company, search the registry for it) rather than registry-driven (pull the whole registry and match every row against known companies). A future bulk-sync job that walks a state's full registry and creates unlinked `RERADetail` rows for later matching is a reasonable extension the schema already supports (`company_id` nullable) but isn't built here.
