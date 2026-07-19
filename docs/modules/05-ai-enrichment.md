# Module 5 — AI Enrichment

**Status:** Implemented — schema, extractors, orchestrator, Celery task, and tests are in this PR.
**Depends on:** [Module 2 — Database](02-database.md) and [Module 4 — Website Crawling](04-crawling.md) (consumes the pending `job_type=extraction` jobs Module 4 leaves behind).

## What's in this module

- `packages/core/src/corelib/schemas/enrichment.py` — `CompanyExtraction`, the one Pydantic model driving everything: the JSON schema handed to the AI provider, response validation, and the shape persisted as `ai_summaries.structured_json`.
- Migration `64d908e31c7b_seed_business_categories.py` — seeds a curated 9-category taxonomy (Broker, Channel Partner, Developer, Consultant, Leasing Firm, Property Management Company, Real Estate Agency, Investment Advisory, Land Aggregator) that AI-extracted free-text labels get matched against.
- `apps/worker/src/worker/enrichment/` — `extractors.py` (`ClaudeExtractor`, `OpenAIExtractor`), `embeddings.py` (`OpenAIEmbeddingProvider`), `category_matching.py` (pg_trgm fuzzy match against the seeded taxonomy), `developer_matching.py` (exact match only — see rationale below), `service.py` (`EnrichmentService`, the orchestrator), `prompts.py`.
- `apps/worker/src/worker/tasks/extraction.py` — the Celery task wrapping `EnrichmentService`.

## A necessary honesty note

This sandbox has no `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` — confirmed directly, and consistent with not having outbound access to `api.openai.com` either (blocked by the same proxy allowlist that affected Modules 3–4; `api.anthropic.com` is reachable but there's no credential to authenticate with). This is expected: I'm Claude, not a separately-credentialed caller with my own billing account to hit the Claude API recursively.

What that means concretely for this module:
- `ClaudeExtractor` and `OpenAIExtractor` are real, complete SDK usage (Anthropic tool-use with forced `tool_choice`; OpenAI's `chat.completions.parse(response_format=<pydantic model>)` structured-outputs helper) — verified structurally against `httpx.MockTransport` returning realistic, provider-documented response payloads (`tests/unit/test_extractors.py`), not against a live API.
- `EnrichmentService` — the actual business logic: assembling crawled content, projecting the AI's structured response onto the database — is tested fully against real Postgres using a `FakeAIExtractor`/`FakeEmbeddingProvider` (`tests/integration/test_enrichment_service.py`), the same dependency-injection pattern used for `DiscoverySource` (Module 3) and `BrowserPool` consumers (Module 4).
- A manual end-to-end run through a real Redis broker and a real `celery worker` subprocess proved the full pipeline wiring up to the point a real credential would be needed — see "Bug found" below, which that exact run caught.

## How enrichment works

1. `EnrichmentService.run(job)` loads the company and every `is_current` `CrawlSnapshot` Module 4 left for it.
2. Assembles their Markdown (fetched from object storage via each snapshot's `markdown_key`) into one prompt, ordered home → about → services → contact → team → projects → developers, capped at `enrichment_max_content_chars` (default ~24k chars, roughly 6k tokens) so a large multi-page crawl stays within a reasonable request size regardless of how much Module 4 collected.
3. Calls the configured `AIExtractor` (`ENRICHMENT_PROVIDER=claude` or `openai`) with that content, getting back a validated `CompanyExtraction`.
4. Generates an embedding of `summary_markdown` via OpenAI's `text-embedding-3-small` (1536-dim, matching the `Vector` column Module 2 already fixed) — used regardless of which provider did the extraction itself, since Anthropic has no public embeddings endpoint.
5. Projects the extraction onto:
   - **`ai_summaries`** — the structured JSON and Markdown summary verbatim, versioned via the same `is_current` pattern Module 2 established for this table.
   - **`company_categories`** — the free-text `business_category` matched (pg_trgm similarity, threshold 0.4) against the seeded taxonomy, or created if nothing's close enough; marked primary, any prior primary demoted (not deleted).
   - **`company_specializations`** — one upserted row per specialization the AI found evidence for, each with its own confidence.
   - **`service_areas`** — one row per named area, stored as `locality`/`area_type=neighbourhood` with no `city`/`geom` resolved yet — Module 9 (Geographic Intelligence) owns turning a raw locality string into a proper geo hierarchy; this module only captures what the AI actually read off the page.
   - **`company_developer_partnerships`** + **`developers`** — matched by exact name only (see below), created if new.
   - **`companies`** itself — `status=enriched`, `last_enriched_at`, `confidence_score`, and `year_established` (only overwritten if the AI found an explicit statement — never inferred, never overwrites a known value with silence).
6. No pending hand-off job is created for a "next module" the way Discovery→Crawl→Extraction chained — see "No Module 6+ hand-off" below.

### Business category matching: fuzzy; developer matching: exact only

Both are real matching problems but with different risk profiles. The business category taxonomy is small (9 seeded rows) and curated — pg_trgm similarity confidently reuses "Consultant" for "Realty Consultants" (similarity ~0.5) without fear of merging two genuinely different categories. Developer names are the opposite: an organically-growing list of hundreds of real, often similarly-named companies ("Kolte Patil" vs. "Kolte Constructions") where fuzzy matching risks silently attributing a partnership to the wrong developer. `developer_matching.py` only matches on exact (case/slug-normalized) name; near-duplicate developer cleanup is Module 8's job, same as company dedup.

### No Module 6+ hand-off

Modules 3 and 4 each left a durable pending job for the next pipeline stage (discovery → crawl → extraction). Module 5 doesn't create an equivalent pending job for Module 6 (Social Discovery), because there isn't one obvious next stage the way crawl-then-extract was — Modules 6 through 10 are largely independent enrichment passes (social profiles, RERA matching, dedup, geo-resolution, scoring) that can run whenever, not a single linear continuation. This is a deliberate scope decision, not an oversight — documented here so it isn't mistaken for a missing feature in a later module's review.

### Why this module doesn't checkpoint page-by-page

Unlike `DiscoveryService`/`CrawlService`, which commit progress after every page/query (a crash should lose at most one unit of work), `EnrichmentService` commits once at the end of a single, atomic pass: one AI call, one persistence phase. There's nothing meaningful to resume mid-way through a single AI call, and re-running the whole thing on retry is idempotent in effect (the `is_current` versioning and upsert logic throughout absorb a re-run cleanly) even though it does re-spend the AI API call. Building finer-grained checkpointing for a workflow whose real unit of work is "one request" would be complexity without a resilience benefit.

## Bug found & fixed during this module

`openai.AsyncOpenAI(api_key=...)` raises immediately at construction when no credential is available — unlike `anthropic.AsyncAnthropic` (tolerates `None`, only fails on the actual request) and unlike the `httpx.AsyncClient`/`BrowserPool` objects the discovery/crawl tasks construct (plain instantiation, never fails until a real request is attempted). The extraction task originally constructed both the extractor's client and the embeddings client *before* handing off to `EnrichmentService.run()`, which is where the job's `try`/`except`-and-persist-`failed` logic lives. A missing credential therefore raised before the job was ever marked `running`, left it stuck in `pending` forever, and surfaced only as an unhandled Celery task exception — caught by the manual end-to-end run against a real Celery worker, exactly the kind of thing that's invisible to a fully-mocked test suite. Fixed by moving client construction inside a `try`/`except` in the task that mirrors `EnrichmentService`'s own failure-persistence, and added `tests/integration/test_extraction_task.py` as a regression test that runs the task's real async body (not through Celery) against real Postgres with no credential configured, asserting the job lands in `failed` with a clear error rather than staying `pending`.

## Testing

- **Unit** (`tests/unit/`): `test_extractors.py` (both `ClaudeExtractor`/`OpenAIExtractor` against `httpx.MockTransport` with realistic provider response payloads, including the "no tool_use block" / "refusal" failure paths), `test_embeddings.py`.
- **Integration** (`tests/integration/`): `test_category_matching.py` (real pg_trgm — exact match, fuzzy match with empirically-verified similarity scores, create-when-nothing-close, no duplicate on repeat), `test_enrichment_service.py` (full run against real Postgres + real object storage using `FakeAIExtractor`/`FakeEmbeddingProvider` — persistence across all five projections, re-run versioning without duplication, missing-crawled-content failure, extractor-exception failure), `test_extraction_task.py` (the regression test above).
- **Manual end-to-end**: a real Redis broker + a real `celery worker` subprocess consuming the `extraction` queue, which is what caught the bug above.

## Recommendations / open questions

1. **`enrichment_max_content_chars` (24k) is an untuned default.** Real tuning needs real crawled content and real cost/quality tradeoffs against a live provider — reasonable to revisit once this runs against genuine data.
2. **Service area resolution.** Module 9 should read `service_areas` rows with `area_type=neighbourhood` and no `city`/`geom` set as its primary backlog to resolve, rather than a schema Module 9 needs to build from scratch.
3. **Category taxonomy growth.** The 9 seeded categories will not stay exhaustive — `match_or_create_business_category`'s fallback creation path is the intended way the taxonomy grows, but a periodic review of auto-created categories (are "Interior Design Studio" and "Vastu Shastra Consultancy" actually distinct businesses this platform should track, or noise from an unusual company's self-description?) is a reasonable operational practice once this runs against real discovered companies.
