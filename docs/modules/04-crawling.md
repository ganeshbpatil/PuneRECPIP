# Module 4 — Website Crawling

**Status:** Implemented — engine, orchestrator, Celery task, and tests are in this PR.
**Depends on:** [Module 2 — Database](02-database.md) (new `crawl_snapshots` table added here) and [Module 3 — Company Discovery](03-discovery.md) (this module consumes the pending `job_type=crawl` `scrape_jobs` rows Module 3 leaves behind).

## What's in this module

- `packages/core/src/corelib/models/crawl_snapshot.py` — the `crawl_snapshots` table, plus a new `PageType` enum. Migration `d3bd343165c9_add_crawl_snapshots.py`.
- `packages/core/src/corelib/storage.py` — `ObjectStorage` protocol with two implementations: `LocalFilesystemObjectStorage` (dev/test) and `S3ObjectStorage` (AWS S3 or MinIO, boto3-based).
- `apps/worker/src/worker/net/` — `ratelimit.py`, `robots.py`, `retry.py`, promoted out of `worker.discovery` (Module 3) since crawling needs the exact same per-domain rate limiting and robots.txt compliance.
- `apps/worker/src/worker/crawling/` — the crawl engine: `browser.py` (Playwright pool), `page_classifier.py`, `link_extraction.py`, `content_extraction.py`, `contact_extraction.py`, `service.py` (`CrawlService`, the orchestrator).
- `apps/worker/src/worker/tasks/crawling.py` — the Celery task wrapping `CrawlService`.
- `apps/worker/tests/fixtures/site/` — a real, hand-written 4-page company website, served by a real local HTTP server in tests (not mocked HTTP responses — an actual `http.server` process and an actual browser navigating to it).

## A real environment constraint, and how it's handled

The master prompt specifies Crawl4AI as the primary crawling tool. This sandbox has no outbound network access to install a browser via `playwright install` (see Module 3's docs for the same networking constraint), and it ships a **pre-installed Chromium at revision 1194**. Every `crawl4ai`/`playwright` release on PyPI right now pins a newer revision (1228 as of `playwright==1.61.0`, which `crawl4ai==0.9.2` itself depends on) — confirmed directly:

```
$ python -c "from playwright.async_api import async_playwright; ..."
BrowserType.launch: Executable doesn't exist at
  /opt/pw-browsers/chromium_headless_shell-1228/chrome-headless-shell-linux64/chrome-headless-shell
```

Playwright's `launch(executable_path=...)` bypasses the revision check entirely and was verified working against the pre-installed binary. Crawl4AI's `BrowserConfig`, however, has **no parameter that reaches `executable_path`** — its `browser_manager.py` builds the `playwright.chromium.launch()` call itself from `headless`/`args`/`chrome_channel`/`proxy_config` only (checked directly against the installed package source). There is no supported way to point Crawl4AI's browser launch at a specific binary short of monkeypatching its internals, which is worse than not using it.

**Decision:** built the crawler on raw Playwright (itself an explicitly approved "Browser Automation" tool) plus `trafilatura` and `markdownify` (both explicitly approved "Data Extraction" tools) instead of Crawl4AI's orchestration layer. This is a deployment-environment workaround, not a rejection of Crawl4AI as a choice — `worker.core.config.Settings.chromium_executable_path` defaults to `None`, which lets Playwright resolve its own properly-`playwright install`-ed browser exactly as it would in a normal deployment or in CI (see below). A future module could reintroduce Crawl4AI on top of the same Playwright foundation once that's worth the added dependency weight; nothing here forecloses it.

CI (`.github/workflows/ci.yml`) runs `playwright install --with-deps chromium` and leaves `CHROMIUM_EXECUTABLE_PATH` unset, so it exercises the normal, un-pinned code path — this sandbox's pinned-binary path is exercised locally (auto-detected by `apps/worker/tests/conftest.py`'s `chromium_executable_path` fixture, no manual env var needed) but isn't a permanent architectural feature.

## How a crawl works

1. `CrawlService.run(job)` loads the `Company` and its primary (or earliest-created) `Website` from `job.company_id` — set by Module 3 when it discovered the company.
2. Fetches the homepage through `BrowserPool` (real Chromium, one shared browser process, per-fetch isolated `BrowserContext`, semaphore-bounded concurrency).
3. Extracts every same-domain link from the homepage (`link_extraction.py`), classifies each by URL/anchor-text keywords (`page_classifier.py`: about/services/team/contact/projects/developers — deterministic, not the AI classification of Module 5), and keeps the first link matching each distinct category, up to `max_pages_per_company - 1`.
4. Fetches each selected page, extracts clean HTML (`trafilatura`, falling back to a naive script/style-stripped version for text-sparse pages like a bare "Contact Us" form that trafilatura's article-tuned heuristics would otherwise reject), converts to Markdown (`markdownify`), and extracts emails/phones (`contact_extraction.py` — `mailto:`/`tel:` links checked first as high-confidence explicit signals, then a regex scan of visible text filtered through `normalize_india_phone`'s digit-count validation).
5. Uploads raw HTML, clean HTML, Markdown, and a full-page PNG screenshot to object storage under `crawls/{company_id}/{page_type}/{content_hash}/...`; writes one `crawl_snapshots` row per page with the storage keys plus the extracted emails/phones/links as JSONB (see "Where 'Structured JSON' lives" below).
6. After all pages: aggregates every email/phone found across the crawl's current snapshots onto the company (deduped against what's already there), sets `company.status = crawled` / `last_crawled_at`, sets `website.status = active` / `last_checked_at`, and — the hand-off to Module 5 — creates a **pending** `scrape_jobs` row with `job_type=extraction`. Same durable-ledger pattern Module 3 used for its own hand-off to this module.
7. Checkpointed and **committed after every single page** (homepage included), for the same reason as `DiscoveryService`: a crash must lose at most one in-flight page, never previously completed ones. `run_crawl_job(job_id)` is safe to re-invoke with the same ID.

### Checkpoint shape

```json
{"visited": ["https://acme.example/", "https://acme.example/about"], "candidate_pages": [{"url": "...", "page_type": "services"}, ...]}
```

`candidate_pages` is computed once, right after the homepage crawl, and persisted — so resuming never needs to re-fetch the homepage just to re-derive its link list.

### Where "Structured JSON" lives

The master prompt lists "Structured JSON" alongside HTML/Markdown/Screenshots under "Store." The deterministically-extracted structured data here (emails, phones, internal links found on a page) is small and relational-shaped, so it's stored as JSONB columns directly on `crawl_snapshots` rather than as a fourth object-storage artifact per page — genuinely structured, queryable data belongs in Postgres; only the large, opaque artifacts (HTML/Markdown/screenshot bytes) go to object storage. See Module 2's design-rationale table for the same reasoning applied elsewhere in this schema.

### A bug this module's tests caught

`RobotsCache` (built in Module 3) hardcoded `https://` when constructing the `robots.txt` URL to fetch. Module 3 only ever targeted HTTPS directories, so this went unnoticed. Testing this module's crawler against a real **plain-HTTP** local server (see below) surfaced it immediately — every fetch was silently blocked because the robots.txt check was requesting `https://127.0.0.1:PORT/robots.txt`, which nothing was listening on, which `RobotsCache` conservatively treats as "disallow" per its own documented policy for unreachable robots.txt. Fixed by having `RobotsCache.is_allowed(url)` take the actual target URL (deriving scheme+host from it) instead of a bare domain string assumed to be HTTPS. Real company websites are not universally HTTPS-only — older or poorly maintained small-business sites are exactly the kind of long-tail listing this platform needs to handle — so this was a genuine correctness fix, not just a test-environment accommodation.

## Testing

- **Unit** (`tests/unit/`): `test_page_classifier.py`, `test_link_extraction.py`, `test_content_extraction.py`, `test_contact_extraction.py` — pure functions, no I/O. `test_browser.py` runs against the **real** Chromium binary via `data:` URLs (no network, but genuine browser launch/render/screenshot, not a mock) — including a concurrency-limit test proving `BrowserPool`'s semaphore queues rather than drops work.
- **Integration** (`tests/integration/test_crawl_service.py`): runs `CrawlService` against real Postgres, a real Chromium browser, and a real local HTTP server (`http.server.ThreadingHTTPServer`, not proxied — works in this sandbox unlike a live third-party site would) serving `tests/fixtures/site/`, a genuine 4-page company site with real `mailto:`/`tel:` links. Covers: full crawl (snapshot count, storage-key existence, contact aggregation, company/website status updates, the extraction hand-off, per-page log entries), resume (a request-counting HTTP handler proves every page is fetched exactly once across two `service.run()` calls), a company with no website (job fails cleanly), and a broken candidate link (connection-refused on a closed port — proves one bad page doesn't fail the whole crawl).
- **Object storage**: `corelib/tests/test_storage.py` (Module 2/3 area, extended here) covers both backends for real — `LocalFilesystemObjectStorage` against `tmp_path`, and `S3ObjectStorage` against a fully offline mocked S3 via `moto`, not just the local backend.
- **Manual end-to-end**: validated against a real Redis broker and a real `celery worker` subprocess consuming the `crawl` queue — a job was created, dispatched via `.delay()`, picked up, and `CrawlService` ran against the real local fixture site through a real browser, persisting 4 snapshots and the expected contact info, exactly as the automated integration test proves in-process.

## Known simplifications (documented, not accidental)

- **No redirect canonicalization.** `crawl_snapshots.url` and the `visited` checkpoint list use the *requested* URL, not `FetchedPage.final_url`. A page that redirects (e.g. `http://` → `https://`, or `example.com` → `www.example.com`) is tracked by what was asked for, not where it ended up. Acceptable for Module 4's scope; revisit if redirect chains turn out to cause duplicate crawls in practice.
- **One website per company.** `_load_primary_website` picks the primary (or earliest) `Website` row and crawls only that. A company with multiple listed domains only gets the primary one crawled in this module.
- **Candidate-page selection keeps only the first link per category.** If a homepage links to two different "services" pages, only the first (in document order) is crawled. Simple and predictable; revisit only if real sites show this loses meaningfully distinct content.
