# Module 6 — Social Discovery

**Status:** Implemented — schema (from Module 2), classifier, service, Celery task, and tests are in this PR.
**Depends on:** [Module 2 — Database](02-database.md) (`social_profiles`) and [Module 4 — Website Crawling](04-crawling.md) (consumes the raw HTML Module 4 already stored — this module doesn't fetch anything itself).

## What's in this module

- `apps/worker/src/worker/social/link_classification.py` — `classify_social_link(url)`, pure URL-string logic (no network) that decides whether a URL is an actual LinkedIn/Facebook/Instagram/YouTube/X **profile**, as opposed to a post, video, share dialog, or other same-domain link that isn't evidence of a profile.
- `apps/worker/src/worker/social/service.py` — `SocialDiscoveryService`, the orchestrator.
- `apps/worker/src/worker/social/jobs.py` — `create_social_discovery_job`.
- `apps/worker/src/worker/tasks/enrichment.py` — the Celery task, registered on the `enrichment` queue (the queue name Module 1's architecture doc already assigned to social + RERA enrichment).

## Why this module doesn't scrape LinkedIn, Facebook, Instagram, YouTube, or X

The master spec for this module says "locate publicly listed business profiles on" those five platforms. The natural reading of that — searching each platform for a company by name and scraping the results — isn't something this module does, for two independent reasons:

1. **Terms of service.** LinkedIn, Facebook, and Instagram all explicitly prohibit automated access to their search and profile pages in their terms of service. Building a scraper against those pages would mean building something whose normal operation requires evading that prohibition (rotating IPs/user-agents, solving or avoiding bot challenges, etc.) — that's not something this build takes on.
2. **Sandbox reachability.** Even for the platforms without an explicit ToS blocker, this sandbox's network proxy only allows a small domain allowlist (`pypi.org`, `npmjs.org`, `anthropic.com`) — `linkedin.com`, `facebook.com`, `instagram.com`, `youtube.com`, and `x.com` are all unreachable here regardless.

**What this module does instead:** every company Module 4 crawled already has its own website's raw HTML sitting in object storage. Real businesses routinely link out to their own official social profiles from their own site (header/footer social icons, an "About" or "Contact" page, etc.) — that's public information the company itself chose to publish, no different in kind from the phone numbers and emails Module 4 already extracts from the same pages. `SocialDiscoveryService` re-parses that already-fetched HTML for outbound links, classifies each one against a conservative whitelist per platform, and records the ones that are real profile/company/channel URLs.

**What this means concretely:**
- `SocialProfile.url` and `SocialProfile.handle` are populated from what the company's own site links to.
- `SocialProfile.description`, `follower_count`, and `is_verified` are left `NULL`/`false` — populating them would require actually visiting the platform page, which is exactly the access this module avoids. A future module could add that (e.g. an approved, ToS-compliant data provider or official platform API with real credentials), but that's a distinct build with its own compliance review, not something to fake here.
- Companies that don't link to their own social profiles from their website simply get zero `SocialProfile` rows from this module — there's no fallback "guess the handle from the company name" heuristic, since that would risk attaching a URL to the wrong business.

## Why the classifier is whitelist-based, not "any link on that domain"

A company's site often links to `facebook.com/sharer/...` (a share button), `youtube.com/watch?v=...` (an embedded video), or `instagram.com/p/...` (a specific post) — all on the right domain, none of them the company's own profile. `classify_social_link` only accepts:

- **LinkedIn:** `/company/<slug>` (a business Page). `/in/<slug>` (a personal profile) is rejected — it could be any team member's, not necessarily the company's.
- **Facebook:** any first path segment except a blacklist of known utility/action paths (`sharer`, `dialog`, `plugins`, `profile.php` — a personal profile by numeric id, not a business Page — `login`, `groups`, `events`, `watch`, etc.).
- **Instagram:** any first path segment except a blacklist of non-profile paths (`p`, `reel`, `reels`, `explore`, `stories`, `accounts`, `direct`, `tv`).
- **YouTube:** `/channel/<id>`, `/c/<name>`, `/user/<name>`, or `/@handle`. `/watch`, `/playlist`, `/shorts`, and `youtu.be` links are always rejected — those are videos, not channels.
- **X:** any first path segment except a blacklist of non-profile paths (`i`, `hashtag`, `search`, `intent`, `share`, `home`, `messages`, `notifications`, `settings`).

Facebook/Instagram/X use a blacklist rather than a whitelist (unlike LinkedIn/YouTube, which have a clean structural marker for "this is a profile") because a business Page's own path segment is just its slug — there's no fixed prefix to whitelist. The blacklist is deliberately conservative and will misclassify some obscure app-specific paths as profiles rather than reject a real business Page; false positives there are self-correcting (a bad URL is just a `SocialProfile` row that leads nowhere), whereas rejecting a real profile silently loses information.

## How social discovery works

1. `SocialDiscoveryService.run(job)` loads the company and every `is_current` `CrawlSnapshot` Module 4 left for it.
2. For each snapshot with a `raw_html_key`, fetches the stored raw HTML from object storage and extracts every outbound `<a href>` (absolute-resolved) — deliberately **not** filtered to same-domain links the way Module 4's `extract_internal_links` is, since a social profile link always points to a different domain.
3. Classifies each link via `classify_social_link`; links that don't classify (internal nav, unrelated external links, non-profile platform paths) are silently dropped.
4. Dedupes by URL across all of a company's snapshots (the same footer social icons often appear on every page) and upserts one `SocialProfile` row per distinct platform URL, keyed on `(company_id, url)` — re-running the job updates `handle`/`platform` on existing rows rather than duplicating them.
5. A missing `raw_html_key` artifact (evicted from storage, etc.) is logged and skipped, not fatal to the job — mirrors how Module 5 handles a missing `markdown_key`.
6. A company with no crawled snapshots at all fails the job (nothing to discover from); a company with crawled snapshots but zero matching links succeeds with `profiles_recorded: 0` — that's a normal, expected outcome, not a failure.

## Testing

- **Unit** (`tests/unit/test_link_classification.py`): all 5 platforms — the accepted profile-URL shape and every rejected non-profile shape (personal LinkedIn profiles, Facebook share/dialog/profile.php links, Instagram posts/reels, YouTube watch/short links, X hashtag/intent/search links), plus case-insensitive host matching.
- **Integration** (`tests/integration/test_social_discovery_service.py`), against real Postgres and a real `LocalFilesystemObjectStorage`: classification end-to-end across multiple snapshots, cross-snapshot URL dedup, upsert-not-duplicate on re-run, the no-crawled-content failure path, the zero-matches success path, and the missing-artifact-is-skipped-not-fatal path.
- **Manual end-to-end**: a real Redis broker and a real `celery worker` subprocess consuming the `enrichment` queue, dispatching a `run_social_discovery_job` task via `.delay()` against a company with real LinkedIn/Instagram links (plus a decoy Instagram post link) and confirming the persisted `social_profiles` rows and `scrape_jobs.result` directly in Postgres.

Unlike Module 5, there's no credential-related bug class to find here — this module makes no external API/network calls at all, so there's nothing that can fail only in a "real credentials present" environment.

## Recommendations / open questions

1. **No fallback discovery path.** A company that never links to its own social profiles from its website gets nothing from this module. A future enhancement, if a ToS-compliant and adequately-credentialed data source becomes available (an official Platform API, or a licensed third-party data provider), could attempt to fill that gap — but that's a new, separately-scoped capability, not a gap in this module's stated purpose.
2. **`description`/`follower_count`/`is_verified` stay unpopulated by this module.** Documented above; flagged again here so it's clear this is a deliberate scope boundary if a later module or reviewer expects those columns to already be populated.
3. **Blacklist maintenance.** The Facebook/Instagram/X non-profile path blacklists are a reasonable starting set based on each platform's documented URL structure, not an exhaustive audit — worth revisiting if real crawled data surfaces a path segment that's being misclassified either direction.
