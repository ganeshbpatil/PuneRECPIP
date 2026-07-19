"""Classifies outbound links found on a company's own crawled pages into
social platform profile URLs (Module 6). Pure URL-string logic, no network —
deliberately conservative and whitelist-based per platform: only account/
company/channel-level URLs count as a "profile." A link to a specific video,
post, share dialog, or hashtag lives on the same domain but is not evidence
of a profile, so it's rejected rather than guessed at.

Only the target platforms' own domains are ever inspected here, and only
links a company already published on its own site — no platform is visited,
searched, or scraped. See docs/modules/06-social-discovery.md for why this
module doesn't do platform-native search/scraping (LinkedIn, Facebook, and
Instagram all prohibit automated access to their search/profile pages in
their terms of service).
"""

from dataclasses import dataclass
from urllib.parse import urlsplit

from corelib.enums import SocialPlatform

_LINKEDIN_HOSTS = {"linkedin.com", "www.linkedin.com"}
_FACEBOOK_HOSTS = {"facebook.com", "www.facebook.com", "m.facebook.com", "fb.com"}
_INSTAGRAM_HOSTS = {"instagram.com", "www.instagram.com"}
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
_X_HOSTS = {"twitter.com", "www.twitter.com", "x.com", "www.x.com"}

# First path segment values that indicate a utility/widget/action URL rather
# than an actual profile, even though they share the platform's domain.
_FACEBOOK_NON_PROFILE_FIRST_SEGMENTS = {
    "sharer",
    "dialog",
    "plugins",
    "policies",
    "help",
    "login",
    "l.php",
    "tr",
    "privacy",
    "terms",
    "ads",
    "profile.php",  # personal profile by numeric id, not a business Page
    "groups",
    "events",
    "watch",
}
_INSTAGRAM_NON_PROFILE_FIRST_SEGMENTS = {
    "p",
    "reel",
    "reels",
    "explore",
    "accounts",
    "stories",
    "tv",
    "direct",
}
_X_NON_PROFILE_FIRST_SEGMENTS = {
    "i",
    "hashtag",
    "search",
    "home",
    "intent",
    "share",
    "messages",
    "notifications",
    "settings",
}


@dataclass(frozen=True, slots=True)
class SocialLinkMatch:
    platform: SocialPlatform
    url: str
    handle: str


def classify_social_link(url: str) -> SocialLinkMatch | None:
    parts = urlsplit(url)
    host = parts.netloc.lower().split(":")[0]
    segments = [seg for seg in parts.path.split("/") if seg]

    if host in _LINKEDIN_HOSTS:
        # Only /company/<slug> counts as a business profile; /in/<slug> is a
        # personal profile (could be any team member's, not the company's).
        if len(segments) >= 2 and segments[0] == "company":
            return SocialLinkMatch(SocialPlatform.LINKEDIN, url, segments[1])
        return None

    if host in _FACEBOOK_HOSTS:
        if not segments:
            return None
        if segments[0].lower() in _FACEBOOK_NON_PROFILE_FIRST_SEGMENTS:
            return None
        return SocialLinkMatch(SocialPlatform.FACEBOOK, url, segments[0])

    if host in _INSTAGRAM_HOSTS:
        if not segments:
            return None
        if segments[0].lower() in _INSTAGRAM_NON_PROFILE_FIRST_SEGMENTS:
            return None
        return SocialLinkMatch(SocialPlatform.INSTAGRAM, url, segments[0])

    if host in _YOUTUBE_HOSTS:
        if not segments:
            return None
        first = segments[0]
        if first in {"channel", "c", "user"} and len(segments) >= 2:
            return SocialLinkMatch(SocialPlatform.YOUTUBE, url, segments[1])
        if first.startswith("@"):
            return SocialLinkMatch(SocialPlatform.YOUTUBE, url, first)
        return None  # /watch, /playlist, /shorts, etc. — a video, not a channel
    if host == "youtu.be":
        return None  # always a video short-link, never a channel

    if host in _X_HOSTS:
        if not segments:
            return None
        if segments[0].lower() in _X_NON_PROFILE_FIRST_SEGMENTS:
            return None
        return SocialLinkMatch(SocialPlatform.X, url, segments[0])

    return None
