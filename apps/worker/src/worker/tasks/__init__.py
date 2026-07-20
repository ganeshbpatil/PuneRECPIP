"""Importing this package registers every task module with the shared Celery
`app` instance. New task modules (enrichment, dedup, geo, scoring, indexing,
scheduling) get added here as their module lands."""

from worker.tasks import crawling, dedup, discovery, enrichment, extraction, geo  # noqa: F401
