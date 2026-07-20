"""robots.txt compliance, cached per origin for the lifetime of a job. Shared
by discovery (worker.discovery.sources) and crawling (worker.crawling) —
every outbound fetch this worker makes to a third-party site goes through
this.

Follows RFC 9309 conventions: a fetchable robots.txt (200) is parsed and obeyed;
a confirmed-missing one (4xx) means no restrictions were published, so crawling
is allowed; a server error or timeout (5xx / network failure) is treated as a
temporary block rather than assumed permissive, since we can't tell whether
restrictions exist.
"""

from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx


class RobotsCache:
    def __init__(self, client: httpx.AsyncClient, user_agent: str):
        self._client = client
        self._user_agent = user_agent
        self._parsers: dict[str, RobotFileParser | None] = {}

    async def _get_parser(self, origin: str) -> RobotFileParser | None:
        if origin in self._parsers:
            return self._parsers[origin]

        parser: RobotFileParser | None
        robots_url = f"{origin}/robots.txt"
        try:
            response = await self._client.get(robots_url, timeout=10.0)
        except httpx.HTTPError:
            parser = None  # network failure -> conservative full-disallow
        else:
            if response.status_code == 200:
                parser = RobotFileParser()
                parser.parse(response.text.splitlines())
            elif 400 <= response.status_code < 500:
                parser = RobotFileParser()
                parser.parse([])  # no published rules -> allow-all
            else:
                parser = None  # 5xx -> conservative full-disallow

        self._parsers[origin] = parser
        return parser

    async def is_allowed(self, url: str) -> bool:
        """`url` is the actual target being fetched — its scheme and host
        (including a non-default port, if any) determine which robots.txt
        applies. Passing a bare domain here would silently assume https,
        which breaks for http-only sites (and for any local test server)."""
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        parser = await self._get_parser(origin)
        if parser is None:
            return False
        return parser.can_fetch(self._user_agent, url)
