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
company discovery, and [`docs/modules/04-crawling.md`](docs/modules/04-crawling.md) for
website crawling.

## Development setup

```bash
uv sync --all-packages
createdb punerecpip   # then, as a superuser: citext, pg_trgm, postgis, vector extensions
cp .env.example .env  # fill in DATABASE_URL, REDIS_URL, etc.
cd apps/api && uv run alembic upgrade head
uv run --project apps/worker playwright install chromium  # needed once, for crawling
uv run pytest apps/api/tests packages/core/tests apps/worker/tests

# to run discovery/crawl jobs for real: start redis-server, then from apps/worker
uv run celery -A worker.celery_app worker --loglevel=info -Q discovery,crawl
```

## Modules

1. Architecture — **in review**
2. Database — **in review**
3. Company Discovery — **in review**
4. Website Crawling — **in review**
5. AI Enrichment
6. Social Discovery
7. Public RERA Enrichment
8. Duplicate Detection
9. Geographic Intelligence
10. Lead Scoring
11. Search Platform
12. Automation
