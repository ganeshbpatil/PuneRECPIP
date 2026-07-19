"""Playwright-backed page fetcher with a bounded concurrency pool.

Explicitly pins the browser via `executable_path` rather than letting
Playwright resolve its own managed install: this repo's sandbox ships a
pre-installed Chromium at a fixed revision that doesn't match what a fresh
`pip install playwright` expects internally (Playwright checks browser
revisions, not just "is chromium present"), and `playwright install` isn't
available to fetch a matching one. Passing `executable_path` bypasses that
revision check entirely and launches the given binary directly — verified
working in docs/modules/04-crawling.md. In a normal deployment where
`playwright install chromium` has run, leave `executable_path=None` and
Playwright manages its own browser as usual.
"""

import asyncio
import logging
from dataclasses import dataclass

from playwright.async_api import Browser, Playwright, async_playwright
from playwright.async_api import Error as PlaywrightError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FetchedPage:
    url: str
    final_url: str
    http_status: int | None
    html: str
    screenshot: bytes


class BrowserPool:
    """Owns one shared Playwright `Browser` process. Each fetch gets its own
    isolated `BrowserContext` (fresh cookies/storage per page, so one
    company's crawl never leaks session state into another's) but overall
    concurrency across every fetch sharing this pool is capped by a
    semaphore — a crawl job can't spawn unbounded browser tabs."""

    def __init__(
        self,
        *,
        executable_path: str | None,
        max_concurrent_pages: int,
        user_agent: str,
        page_timeout_seconds: float,
        max_retries: int = 2,
    ):
        self._executable_path = executable_path
        self._user_agent = user_agent
        self._page_timeout_ms = page_timeout_seconds * 1000
        self._max_retries = max_retries
        self._semaphore = asyncio.Semaphore(max_concurrent_pages)
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            executable_path=self._executable_path,
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

    async def stop(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def __aenter__(self) -> "BrowserPool":
        await self.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.stop()

    async def fetch(self, url: str) -> FetchedPage:
        if self._browser is None:
            raise RuntimeError("BrowserPool not started — use 'async with BrowserPool(...)'")

        attempt = 0
        while True:
            try:
                return await self._fetch_once(url)
            except PlaywrightError as exc:
                if attempt >= self._max_retries:
                    raise
                delay = 1.0 * (2**attempt)
                logger.warning("fetch of %s failed (%s), retrying in %.1fs", url, exc, delay)
                attempt += 1
                await asyncio.sleep(delay)

    async def _fetch_once(self, url: str) -> FetchedPage:
        assert self._browser is not None  # narrowed by fetch()'s check
        async with self._semaphore:
            context = await self._browser.new_context(user_agent=self._user_agent)
            try:
                page = await context.new_page()
                response = await page.goto(
                    url, timeout=self._page_timeout_ms, wait_until="domcontentloaded"
                )
                html = await page.content()
                screenshot = await page.screenshot(full_page=True, type="png")
                return FetchedPage(
                    url=url,
                    final_url=page.url,
                    http_status=response.status if response else None,
                    html=html,
                    screenshot=screenshot,
                )
            finally:
                await context.close()
