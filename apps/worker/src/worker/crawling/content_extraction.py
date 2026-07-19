"""Raw HTML -> clean HTML -> Markdown, using both approved "Data Extraction"
tools for what each is actually good at: trafilatura for boilerplate removal
(nav/ads/footer stripped, main content identified), markdownify for the
HTML-to-Markdown syntax conversion. (readability-lxml is not used alongside
trafilatura — the two do materially the same job, and trafilatura is the more
actively maintained, modern choice; adding both would be redundant, not
complementary.)
"""

import trafilatura
from markdownify import markdownify as _html_to_markdown
from selectolax.parser import HTMLParser

_STRIP_TAGS = ("script", "style", "noscript", "svg", "iframe")


def extract_clean_html(raw_html: str, url: str) -> str:
    """trafilatura is tuned for article-like content and returns None on
    text-sparse pages (a "Contact Us" page with a form and an address has
    little prose) — exactly the kind of page this crawler most needs to keep.
    Falls back to a naive script/style-stripped version of the raw HTML rather
    than losing the page."""
    extracted = trafilatura.extract(
        raw_html,
        url=url,
        output_format="html",
        favor_recall=True,
        include_links=True,
        include_images=False,
        include_tables=True,
    )
    if extracted:
        return extracted
    return _strip_boilerplate_tags(raw_html)


def _strip_boilerplate_tags(raw_html: str) -> str:
    tree = HTMLParser(raw_html)
    for tag in _STRIP_TAGS:
        for node in tree.css(tag):
            node.decompose()
    body = tree.css_first("body")
    return body.html if body is not None else tree.html or raw_html


def html_to_markdown(clean_html: str) -> str:
    return _html_to_markdown(clean_html, heading_style="ATX", strip=list(_STRIP_TAGS))
