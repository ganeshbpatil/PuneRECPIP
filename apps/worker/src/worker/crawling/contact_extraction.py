"""Deterministic email/phone extraction from a crawled page's raw HTML.
Regex-based extraction from free text is inherently heuristic — `mailto:`/
`tel:` links are high-confidence (an explicit author signal) and checked
first on both; plain-visible-text pattern matches are best-effort, filtered
through `worker.discovery.normalize.normalize_india_phone`'s digit-count
validation to cut down on phone false positives (prices, dates, pincodes)."""

import re

from selectolax.parser import HTMLParser

from worker.discovery.normalize import normalize_india_phone

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_EMAIL_ASSET_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".avif")

# Loosely matches Indian numbers (10-digit mobile, optionally +91-prefixed, or
# an STD-code + local-number landline with common separators). Deliberately
# permissive here; normalize_india_phone does the real validation.
_PHONE_CANDIDATE_RE = re.compile(r"(?:\+?91[-\s]?)?(?:\(?\d{2,5}\)?[-\s]?)?\d{4,6}[-\s]?\d{3,5}")


def _clean_email(raw: str) -> str | None:
    email = raw.strip(".,;:").lower()
    if not email or email.endswith(_EMAIL_ASSET_SUFFIXES):
        return None
    return email


def extract_emails(html: str) -> list[str]:
    tree = HTMLParser(html)
    seen: set[str] = set()
    emails: list[str] = []

    for anchor in tree.css('a[href^="mailto:"]'):
        raw = (anchor.attributes.get("href") or "")[len("mailto:") :].split("?", 1)[0]
        email = _clean_email(raw)
        if email and email not in seen:
            seen.add(email)
            emails.append(email)

    for match in _EMAIL_RE.findall(tree.text(separator=" ")):
        email = _clean_email(match)
        if email and email not in seen:
            seen.add(email)
            emails.append(email)

    return emails


def extract_phones(html: str) -> list[str]:
    tree = HTMLParser(html)
    seen: set[str] = set()
    phones: list[str] = []

    for anchor in tree.css('a[href^="tel:"]'):
        raw = (anchor.attributes.get("href") or "")[len("tel:") :]
        normalized = normalize_india_phone(raw)
        if normalized and normalized not in seen:
            seen.add(normalized)
            phones.append(normalized)

    for match in _PHONE_CANDIDATE_RE.findall(tree.text(separator=" ")):
        normalized = normalize_india_phone(match)
        if normalized and normalized not in seen:
            seen.add(normalized)
            phones.append(normalized)

    return phones
