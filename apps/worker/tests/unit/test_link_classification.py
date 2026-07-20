from corelib.enums import SocialPlatform
from worker.social.link_classification import classify_social_link


def test_linkedin_company_page_matches():
    match = classify_social_link("https://www.linkedin.com/company/acme-realty/")
    assert match is not None
    assert match.platform == SocialPlatform.LINKEDIN
    assert match.handle == "acme-realty"


def test_linkedin_personal_profile_rejected():
    assert classify_social_link("https://www.linkedin.com/in/jane-doe/") is None


def test_linkedin_bare_domain_rejected():
    assert classify_social_link("https://www.linkedin.com/") is None


def test_facebook_page_matches():
    match = classify_social_link("https://www.facebook.com/AcmeRealtyPune")
    assert match is not None
    assert match.platform == SocialPlatform.FACEBOOK
    assert match.handle == "AcmeRealtyPune"


def test_facebook_sharer_rejected():
    assert (
        classify_social_link("https://www.facebook.com/sharer/sharer.php?u=https://example.com")
        is None
    )


def test_facebook_numeric_profile_php_rejected():
    assert classify_social_link("https://www.facebook.com/profile.php?id=100012345") is None


def test_facebook_dialog_and_plugins_rejected():
    assert classify_social_link("https://www.facebook.com/dialog/share") is None
    assert classify_social_link("https://www.facebook.com/plugins/like.php") is None


def test_instagram_profile_matches():
    match = classify_social_link("https://www.instagram.com/acmerealty/")
    assert match is not None
    assert match.platform == SocialPlatform.INSTAGRAM
    assert match.handle == "acmerealty"


def test_instagram_post_rejected():
    assert classify_social_link("https://www.instagram.com/p/Cxyz123/") is None


def test_instagram_reel_rejected():
    assert classify_social_link("https://www.instagram.com/reel/Cxyz123/") is None


def test_instagram_bare_domain_rejected():
    assert classify_social_link("https://www.instagram.com/") is None


def test_youtube_channel_matches():
    match = classify_social_link("https://www.youtube.com/channel/UC12345")
    assert match is not None
    assert match.platform == SocialPlatform.YOUTUBE
    assert match.handle == "UC12345"


def test_youtube_c_and_user_match():
    c_match = classify_social_link("https://www.youtube.com/c/AcmeRealty")
    assert c_match is not None
    assert c_match.handle == "AcmeRealty"

    user_match = classify_social_link("https://www.youtube.com/user/acmerealty")
    assert user_match is not None
    assert user_match.handle == "acmerealty"


def test_youtube_handle_syntax_matches():
    match = classify_social_link("https://www.youtube.com/@AcmeRealty")
    assert match is not None
    assert match.platform == SocialPlatform.YOUTUBE
    assert match.handle == "@AcmeRealty"


def test_youtube_watch_link_rejected():
    assert classify_social_link("https://www.youtube.com/watch?v=abc123") is None


def test_youtube_short_link_rejected():
    assert classify_social_link("https://youtu.be/abc123") is None


def test_x_handle_matches():
    match = classify_social_link("https://x.com/AcmeRealty")
    assert match is not None
    assert match.platform == SocialPlatform.X
    assert match.handle == "AcmeRealty"


def test_x_legacy_twitter_domain_matches():
    match = classify_social_link("https://twitter.com/AcmeRealty")
    assert match is not None
    assert match.platform == SocialPlatform.X


def test_x_hashtag_and_search_rejected():
    assert classify_social_link("https://x.com/hashtag/realestate") is None
    assert classify_social_link("https://x.com/search?q=acme") is None


def test_x_intent_and_share_rejected():
    assert classify_social_link("https://x.com/intent/tweet?text=hi") is None
    assert classify_social_link("https://twitter.com/share?url=https://example.com") is None


def test_unrelated_domain_returns_none():
    assert classify_social_link("https://acme-realty.example/about") is None


def test_case_insensitive_host_matching():
    match = classify_social_link("https://WWW.LINKEDIN.COM/company/acme-realty/")
    assert match is not None
    assert match.platform == SocialPlatform.LINKEDIN
