"""Celery application. Queue names match docs/architecture/01-architecture.md §2 —
each pipeline stage gets its own queue so a crawl backlog can never starve
lightweight extraction/enrichment work, and each can be scaled independently."""

from celery import Celery

from worker.core.config import get_settings

settings = get_settings()

app = Celery("punerecpip_worker", broker=settings.redis_url, backend=settings.redis_url)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_default_queue="discovery",
    task_routes={
        "worker.tasks.discovery.*": {"queue": "discovery"},
        "worker.tasks.crawling.*": {"queue": "crawl"},
        "worker.tasks.extraction.*": {"queue": "extraction"},
        "worker.tasks.enrichment.*": {"queue": "enrichment"},
        "worker.tasks.dedup.*": {"queue": "dedup"},
        "worker.tasks.geo.*": {"queue": "geo"},
        "worker.tasks.scoring.*": {"queue": "scoring"},
        "worker.tasks.indexing.*": {"queue": "indexing"},
        "worker.tasks.scheduling.*": {"queue": "scheduled"},
    },
    # Applies to the queues that exist today; new task modules should set their
    # own bounded retry policy per docs/architecture/01-architecture.md §4.2
    # rather than relying on this default once crawl-scale tasks land.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)

# Explicit import, not app.autodiscover_tasks(): autodiscover_tasks(pkgs) looks
# for "<pkg>.tasks" submodules, which doesn't match this project's layout where
# worker.tasks *is* the tasks package — that mismatch silently registered zero
# tasks. worker/tasks/__init__.py imports every task module, so importing the
# package here (after `app` exists, avoiding a circular-import failure) is
# enough for each @app.task-decorated function to register itself.
import worker.tasks  # noqa: E402,F401
