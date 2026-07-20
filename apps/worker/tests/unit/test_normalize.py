from worker.discovery.normalize import normalize_domain, normalize_india_phone, slugify


def test_normalize_domain_strips_scheme_www_and_path():
    assert normalize_domain("https://www.Acme-Realty.com/contact?x=1") == "acme-realty.com"


def test_normalize_domain_handles_bare_host():
    assert normalize_domain("acme-realty.com") == "acme-realty.com"


def test_normalize_domain_empty_returns_none():
    assert normalize_domain("") is None


def test_slugify_strips_punctuation_and_lowercases():
    assert slugify("Acme Realty & Co.") == "acme-realty-co"


def test_slugify_with_suffix_disambiguates():
    assert slugify("Acme Realty", suffix="a1b2c3d4") == "acme-realty-a1b2c3d4"


def test_normalize_india_phone_ten_digits():
    assert normalize_india_phone("98765 43210") == "+919876543210"


def test_normalize_india_phone_with_country_code():
    assert normalize_india_phone("+91 98765 43210") == "+919876543210"


def test_normalize_india_phone_landline_with_std_code():
    assert normalize_india_phone("(020) 2567-8901") == "+912025678901"


def test_normalize_india_phone_implausible_returns_none():
    assert normalize_india_phone("12345") is None
