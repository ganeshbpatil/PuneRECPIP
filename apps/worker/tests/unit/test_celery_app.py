"""Regression test for a real bug hit during development: autodiscover_tasks
with a package name matching this project's layout registered zero tasks
silently. Fixed by explicitly importing worker.tasks from celery_app.py."""

from worker.celery_app import app


def test_discovery_task_is_registered():
    assert "worker.tasks.discovery.run_discovery_job" in app.tasks


def test_discovery_task_routes_to_discovery_queue():
    route = app.conf.task_routes["worker.tasks.discovery.*"]
    assert route == {"queue": "discovery"}
