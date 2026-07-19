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
architecture and [`docs/modules/02-database.md`](docs/modules/02-database.md) for the
database schema.

## Development setup (Module 2+)

```bash
uv sync --all-packages
createdb punerecpip   # then, as a superuser: citext, pg_trgm, postgis, vector extensions
cp .env.example .env  # fill in DATABASE_URL etc.
cd apps/api && uv run alembic upgrade head
uv run pytest apps/api/tests packages/core/tests
```

## Modules

1. Architecture — **in review**
2. Database — **in review**
3. Company Discovery
4. Website Crawling
5. AI Enrichment
6. Social Discovery
7. Public RERA Enrichment
8. Duplicate Detection
9. Geographic Intelligence
10. Lead Scoring
11. Search Platform
12. Automation
