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
database schema, and [`docs/modules/03-discovery.md`](docs/modules/03-discovery.md) for
company discovery.

## Development setup

```bash
uv sync --all-packages
createdb punerecpip   # then, as a superuser: citext, pg_trgm, postgis, vector extensions
cp .env.example .env  # fill in DATABASE_URL, REDIS_URL, etc.
cd apps/api && uv run alembic upgrade head
uv run pytest apps/api/tests packages/core/tests apps/worker/tests

# to run a discovery job for real: redis-server, then from apps/worker
uv run celery -A worker.celery_app worker --loglevel=info -Q discovery
```

## Modules

1. Architecture — **in review**
2. Database — **in review**
3. Company Discovery — **in review**
4. Website Crawling
5. AI Enrichment
6. Social Discovery
7. Public RERA Enrichment
8. Duplicate Detection
9. Geographic Intelligence
10. Lead Scoring
11. Search Platform
12. Automation
