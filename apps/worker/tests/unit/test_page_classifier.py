from corelib.enums import PageType
from worker.crawling.page_classifier import classify_link


def test_classifies_about_page():
    assert classify_link("/about-us", "About Us") == PageType.ABOUT


def test_classifies_services_page():
    assert classify_link("/services", "Our Services") == PageType.SERVICES


def test_classifies_team_page():
    assert classify_link("/team", "Leadership") == PageType.TEAM


def test_classifies_contact_page():
    assert classify_link("/contact", "Contact") == PageType.CONTACT


def test_classifies_projects_page():
    assert classify_link("/portfolio", "Our Portfolio") == PageType.PROJECTS


def test_classifies_developers_page():
    assert classify_link("/builder-partners", "Builder Partners") == PageType.DEVELOPERS


def test_unmatched_link_is_other():
    assert classify_link("/blog/market-trends-2026", "Market Trends") == PageType.OTHER


def test_contact_takes_priority_over_team_when_both_words_present():
    assert classify_link("/contact-our-team", "Contact Our Team") == PageType.CONTACT
