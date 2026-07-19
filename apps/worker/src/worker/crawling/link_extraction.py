"""Extracts same-domain, navigable links from a fetched page's HTML."""

from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

_SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "#")


def extract_internal_links(html: str, base_url: str) -> list[tuple[str, str]]:
    """Returns deduplicated `(absolute_url, link_text)` pairs for every same-
    domain `<a href>` on the page, in document order. Fragment-only differences
    (`/about#team` vs `/about`) collapse to one entry."""
    base_domain = urlparse(base_url).netloc.lower()
    tree = HTMLParser(html)
    seen: set[str] = set()
    links: list[tuple[str, str]] = []

    for anchor in tree.css("a[href]"):
        href = (anchor.attributes.get("href") or "").strip()
        if not href or href.startswith(_SKIP_SCHEMES):
            continue

        absolute = urljoin(base_url, href).split("#", 1)[0]
        if not absolute or urlparse(absolute).netloc.lower() != base_domain:
            continue
        if absolute in seen:
            continue

        seen.add(absolute)
        links.append((absolute, anchor.text(strip=True)))

    return links
