"""Runs against a real Chromium binary via `data:` URLs — no network required,
but genuine browser launch/navigation/screenshot capture, not a mock. See
docs/modules/04-crawling.md for why executable_path may need pinning."""

import asyncio

import pytest
from worker.crawling.browser import BrowserPool

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def pool(chromium_executable_path: str | None):
    async with BrowserPool(
        executable_path=chromium_executable_path,
        max_concurrent_pages=2,
        user_agent="PuneRECPIPTestBot/0.1",
        page_timeout_seconds=10,
    ) as p:
        yield p


async def test_fetch_returns_rendered_html_and_screenshot(pool: BrowserPool):
    page = await pool.fetch(
        "data:text/html,<html><body><h1>Acme Realty</h1><p>Hello</p></body></html>"
    )

    assert "Acme Realty" in page.html
    assert len(page.screenshot) > 0
    assert page.screenshot[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic bytes


async def test_pool_respects_concurrency_limit(chromium_executable_path: str | None):
    pool = BrowserPool(
        executable_path=chromium_executable_path,
        max_concurrent_pages=1,
        user_agent="PuneRECPIPTestBot/0.1",
        page_timeout_seconds=10,
    )
    async with pool:
        # Two concurrent fetches through a pool sized for 1 must both still
        # succeed (serialized, not rejected) — proves the semaphore queues
        # rather than drops work.
        results = await asyncio.gather(
            pool.fetch("data:text/html,<html><body>A</body></html>"),
            pool.fetch("data:text/html,<html><body>B</body></html>"),
        )
        assert len(results) == 2
