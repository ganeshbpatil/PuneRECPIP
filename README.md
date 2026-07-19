# India Real Estate Intelligence Platform (Pune-first)

Production-grade platform that discovers, crawls, enriches, classifies, validates, and
continuously updates publicly available business information about real estate companies,
channel partners, brokers, consultants, developers, leasing firms, and property management
companies — starting in Pune, designed to expand across India.

Only publicly available business information is collected, in compliance with applicable
website terms of service and privacy laws.

## Status

Built module by module, with explicit approval required between modules. See
[`docs/architecture/01-architecture.md`](docs/architecture/01-architecture.md) for the
architecture, [`docs/modules/02-database.md`](docs/modules/02-database.md) for the
database schema, [`docs/modules/03-discovery.md`](docs/modules/03-discovery.md) for
company discovery, [`docs/modules/04-crawling.md`](docs/modules/04-crawling.md) for
website crawling, [`docs/modules/05-ai-enrichment.md`](docs/modules/05-ai-enrichment.md)
for AI enrichment, [`docs/modules/06-social-discovery.md`](docs/modules/06-social-discovery.md)
for social discovery, [`docs/modules/07-rera-enrichment.md`](docs/modules/07-rera-enrichment.md)
for public RERA enrichment, and [`docs/modules/08-duplicate-detection.md`](docs/modules/08-duplicate-detection.md)
for duplicate detection.

## Development setup

```bash
uv sync --all-packages
createdb punerecpip   # then, as a superuser: citext, pg_trgm, postgis, vector extensions
cp .env.example .env  # fill in DATABASE_URL, REDIS_URL, ANTHROPIC_API_KEY/OPENAI_API_KEY, etc.
cd apps/api && uv run alembic upgrade head
uv run --project apps/worker playwright install chromium  # needed once, for crawling
uv run pytest apps/api/tests packages/core/tests apps/worker/tests

# to run discovery/crawl/extraction/enrichment jobs for real: start redis-server, then
# from apps/worker
uv run celery -A worker.celery_app worker --loglevel=info -Q discovery,crawl,extraction,enrichment
```

## Modules

1. Architecture — **in review**
2. Database — **in review**
3. Company Discovery — **in review**
4. Website Crawling — **in review**
5. AI Enrichment — **in review**
6. Social Discovery — **in review**
7. Public RERA Enrichment — **in review**
8. Duplicate Detection — **in review**
9. Geographic Intelligence
10. Lead Scoring
11. Search Platform
12. Automation
