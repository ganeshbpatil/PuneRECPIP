"""Normalization helpers used for in-run and DB dedup during discovery.
Full fuzzy/cross-field duplicate detection is Module 8 — this module only
needs "is this the same listing I already saw," which domain/slug equality
answers cheaply without a pg_trgm round trip per candidate."""

import re
import unicodedata
from urllib.parse import urlparse

_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")
_INDIA_PHONE_RE = re.compile(r"\D+")


def normalize_domain(url: str) -> str | None:
    """'https://www.Acme-Realty.com/contact?x=1' -> 'acme-realty.com'."""
    if not url:
        return None
    parsed = urlparse(url if "//" in url else f"//{url}")
    host = (parsed.netloc or parsed.path).split(":")[0].lower().strip()
    host = host.removeprefix("www.")
    return host or None


def slugify(name: str, *, suffix: str | None = None) -> str:
    """'Acme Realty & Co.' -> 'acme-realty-co' (optionally 'acme-realty-co-<suffix>'
    to disambiguate two different companies that normalize to the same name)."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = _SLUG_STRIP_RE.sub("-", ascii_name.lower()).strip("-")
    return f"{slug}-{suffix}" if suffix else slug


def normalize_india_phone(raw: str) -> str | None:
    """Best-effort E.164 normalization for Indian numbers: '(020) 2567-8901' or
    '9876543210' or '+91 98765 43210' -> '+919876543210'/'+912025678901'.
    Returns None if the digit count doesn't match a plausible Indian number —
    callers should keep the raw value in `raw_value` regardless of this result.
    """
    digits = _INDIA_PHONE_RE.sub("", raw)
    digits = digits.removeprefix("0")
    if digits.startswith("91") and len(digits) == 12:
        return f"+{digits}"
    if len(digits) == 10:
        return f"+91{digits}"
    return None
