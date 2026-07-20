"""Deterministic, keyword-based per-page classification (Module 4) — decides
which internal links a crawl follows and how a CrawlSnapshot is labeled. Not
the AI-driven business classification of Module 5, which reasons about the
*company* as a whole from this raw content, not about individual page roles.
"""

from corelib.enums import PageType

_KEYWORDS: dict[PageType, tuple[str, ...]] = {
    PageType.CONTACT: ("contact", "reach-us", "get-in-touch", "reach us", "get in touch"),
    PageType.ABOUT: ("about", "who-we-are", "who we are", "our-story", "our story"),
    PageType.TEAM: ("team", "people", "leadership", "our-team", "management"),
    PageType.SERVICES: ("service", "what-we-do", "what we do", "offerings"),
    PageType.DEVELOPERS: ("developer", "builder", "partners", "partnership"),
    PageType.PROJECTS: ("project", "portfolio", "properties", "listings"),
}


def classify_link(href: str, link_text: str) -> PageType:
    """Order matters: checked most-specific-first so e.g. "Contact Our Team"
    (a contact page) doesn't get misclassified as TEAM."""
    haystack = f"{href} {link_text}".lower()
    for page_type, keywords in _KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            return page_type
    return PageType.OTHER
