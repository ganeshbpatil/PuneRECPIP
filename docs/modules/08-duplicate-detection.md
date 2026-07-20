# Module 8 — Duplicate Detection

**Status:** Implemented — schema (from Module 2), scoring/merge service, Celery task, and tests are in this PR.
**Depends on:** [Module 2 — Database](02-database.md) (`merge_history`, `change_history`, `companies.is_duplicate`/`merged_into_company_id`), and loosely on every prior module, since it's the cross-cutting pass that reconciles what Modules 3–7 independently added.

## What's in this module

- `apps/worker/src/worker/dedup/service.py` — `DedupService`, the scoring/merge orchestrator.
- `apps/worker/src/worker/dedup/jobs.py` — `create_dedup_job`.
- `apps/worker/src/worker/tasks/dedup.py` — `run_dedup_job`, on the pre-existing `dedup` queue (`celery_app.py` already routed `worker.tasks.dedup.*` there since Module 1).

## Where this sits relative to Module 3's discovery-time dedup

Discovery (Module 3) already refuses to save an *exact* duplicate at ingestion time — same domain, or same name-slug — see `worker/discovery/service.py`'s own docstring: "Full fuzzy/cross-field duplicate detection is Module 8." This module is what catches everything that check doesn't: the same company discovered through two different directories with slightly different name spellings ("Acme Realty Pune" vs "Acme Realty Pune LLP"), crawled under `www.` vs a bare domain before normalization caught up, or entered once via directory discovery and again via a later Google Maps or RERA sync pass.

## The scoring model

Given a company, `DedupService` finds candidate duplicates among every *other* non-merged company and scores each pair on four signals:

- **Structural signals** — an exact match on website domain, phone number, or email address. Two unrelated real estate businesses essentially never coincidentally share a phone number or email address, so these are strong, low-false-positive evidence.
- **Name similarity** (pg_trgm `similarity()`) — the opposite: real estate business names are full of generic, widely-reused tokens ("Realty", "Properties", "Estates", a locality name), so two genuinely *different* businesses can score high on name alone.

Weights are chosen so a single structural signal can cross the auto-merge bar by itself, but name similarity never can:

| Signal | Weight | Crosses `AUTO_MERGE_THRESHOLD` (0.6) alone? |
|---|---|---|
| Domain match | 0.6 | Yes |
| Phone match | 0.5 | No — needs a second signal or high name similarity |
| Email match | 0.4 | No — needs a second signal or high name similarity |
| Name similarity | up to 0.4 (× similarity score) | Never, by construction |

This is a deliberate precision-over-recall choice, consistent with Module 7's own reasoning about RERA match confidence: an incorrect merge folds one real business's data into another's, which is worse than leaving two duplicate rows unmerged for a later pass to catch. Candidate *generation* itself uses a looser, recall-oriented bar (`NAME_CANDIDATE_THRESHOLD = 0.3`, or any structural signal at all) — that only decides what gets scored, not what gets merged.

### Why RERA registration number isn't a scoring signal

It's tempting to treat a shared `rera_details.registration_number` as the strongest possible signal — a government-issued registration number is about as unambiguous an identifier as this dataset has. But `rera_details.registration_number` already carries a database-level `UNIQUE` constraint (Module 7's own schema), so two different companies can never simultaneously hold a `RERADetail` row with the same number — there is no "shared registration number" state for this module to detect; it's structurally impossible. (An earlier version of this module tried to score it as a signal anyway, and the integration test proving it promptly failed on a real unique-constraint violation — a good example of the schema itself catching a design mistake.)

The genuinely interesting related case is different: `RERAEnrichmentService` (Module 7) searches the registry by company name and links whatever registration number scores best — if two *different* companies in this database are actually the same business, a second `RERAEnrichmentService` run for the "duplicate" company could find and re-link the *same* registration number, silently stealing it from the first company (Module 7's own docs already flagged this as "last-match-wins, plausibly Module 8 territory"). Resolving that properly means detecting a registration-number reassignment event (visible in `change_history`, since Module 7 doesn't currently write one — see Recommendations) and treating it as a strong dedup signal after the fact, not a duplicate-registration-number scoring signal on `RERADetail` directly. Left as designed-but-not-built, documented here rather than silently dropped.

## Picking the primary in a merge

Given a pair that clears the auto-merge threshold, the company further along the pipeline (`DISCOVERED` → `CRAWLING` → `CRAWLED` → `ENRICHING` → `ENRICHED` → `VERIFIED`) becomes the primary — more pipeline progress means more real data (crawled content, AI summary, social profiles, RERA match) likely already hangs off it. Ties break toward the older record (`discovered_at`, falling back to `created_at`), on the theory that the first-discovered listing is more likely the canonical one. Neither heuristic is a substitute for actually merging child data (see below) — it only decides which `company_id` survives as the one future enrichment passes target.

## What "merge" actually does — and doesn't do

Per `Company`'s own schema (`is_duplicate`, `merged_into_company_id`) and `MergeHistory`'s docstring ("Companies are never hard-deleted on merge... kept for audit"), a merge is intentionally lightweight:

1. The duplicate's `status` becomes `merged`, `is_duplicate` becomes `true`, `merged_into_company_id` points at the primary.
2. A `MergeHistory` row records `match_score` and the full `match_criteria` JSON for audit.
3. A `ChangeHistory` row records the status transition with `change_source=dedup_merge` — this is the first module to actually write to `change_history`; every column and the `ChangeSource.DEDUP_MERGE` enum value existed since Module 2 specifically for this.
4. The duplicate's own child rows (contacts, crawl snapshots, social profiles, RERA details, ...) are **not** moved, re-pointed, or deleted. They stay attached to the now-`merged` company for audit continuity.

Presenting a single, de-duplicated view of a merged pair (i.e., resolving `merged_into_company_id` chains and surfacing the primary's combined data) is a read-time/query-layer concern, not something this module needs to do — flagged as Module 11 (Search Platform)'s job, the same way Module 5 flagged geo-resolution as Module 9's.

## Testing

- **Integration** (`tests/integration/test_dedup_service.py`), against real Postgres (real `pg_trgm` similarity, and the real unique constraint on `merge_history.duplicate_company_id`): each structural signal in isolation (auto-merges alone for domain, doesn't for phone/email alone), a weak signal plus name similarity crossing the threshold together, name similarity alone never merging even at a perfect score, primary selection by pipeline status and by `discovered_at` tie-break, the subject company itself becoming the duplicate and the job correctly stopping rather than evaluating further candidates against a company that's no longer active, an already-`merged` job subject being skipped entirely, and an already-`merged` candidate being excluded from candidate generation.
- **Manual end-to-end**: a real Redis broker and a real `celery worker` subprocess consuming the `dedup` queue — created two companies sharing a website domain, dispatched `run_dedup_job` via `.delay()`, and confirmed the persisted `companies`, `merge_history`, and `change_history` rows directly in Postgres.

## Recommendations / open questions

1. **RERA reassignment isn't tracked as a signal yet.** As described above, `RERAEnrichmentService` doesn't currently write a `ChangeHistory` row when it re-links an already-linked registration number to a different company — adding that (and having this module watch for it) is the natural way to close the gap description above leaves open.
2. **All weights/thresholds are untuned defaults**, same caveat as every prior module's matching logic (category matching's 0.4, RERA's 0.5) — reasonable starting points, not empirically validated ones.
3. **No merge undo.** `merge_history.duplicate_company_id` is unique, so a company can only ever be merged once; there's no built-in "unmerge" if a false positive slips through. Given the precision-biased threshold this should be rare, but a manual unmerge path (reset `status`/`is_duplicate`/`merged_into_company_id`, delete the `MergeHistory` row) is a reasonable one-time admin operation to support later rather than something this module needs to automate.
4. **No geographic signal yet.** Two companies at the same physical address are plausibly the same business even with dissimilar names — a strong additional signal Module 9 (Geographic Intelligence) will make available once addresses are geo-resolved; worth revisiting this module's signal set once that lands.
