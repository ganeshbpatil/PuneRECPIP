from worker.crawling.link_extraction import extract_internal_links

HTML = """
<html><body>
<nav>
  <a href="/about">About Us</a>
  <a href="/services">Services</a>
  <a href="https://acme-realty.example/contact">Contact</a>
  <a href="https://external.example/other-broker">A competitor</a>
  <a href="mailto:info@acme-realty.example">Email us</a>
  <a href="tel:+919876543210">Call us</a>
  <a href="#top">Back to top</a>
  <a href="/about#team">About (team anchor)</a>
</nav>
</body></html>
"""


def test_extracts_same_domain_links_only():
    links = extract_internal_links(HTML, "https://acme-realty.example/")
    hrefs = [href for href, _ in links]
    assert "https://external.example/other-broker" not in hrefs
    assert "https://acme-realty.example/about" in hrefs
    assert "https://acme-realty.example/contact" in hrefs


def test_skips_non_navigable_schemes():
    links = extract_internal_links(HTML, "https://acme-realty.example/")
    hrefs = [href for href, _ in links]
    assert not any(href.startswith(("mailto:", "tel:", "#")) for href in hrefs)


def test_fragment_only_variants_dedupe_to_one_entry():
    links = extract_internal_links(HTML, "https://acme-realty.example/")
    about_entries = [href for href, _ in links if href == "https://acme-realty.example/about"]
    assert len(about_entries) == 1


def test_relative_links_resolved_against_base_url():
    links = extract_internal_links(HTML, "https://acme-realty.example/")
    text_by_href = dict(links)
    assert text_by_href["https://acme-realty.example/services"] == "Services"
