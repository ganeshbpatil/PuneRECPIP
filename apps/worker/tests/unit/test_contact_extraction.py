from worker.crawling.contact_extraction import extract_emails, extract_phones

HTML = """
<html><body>
<a href="mailto:info@acme-realty.example">Mail us</a>
<p>Email: sales@acme-realty.example for enquiries.
Icons: background-image url(sprite@2x.png) is not an email.
Call us at +91 98765 43210 or (020) 2567-8901.</p>
<a href="tel:+919000011111">Call</a>
</body></html>
"""


def test_extracts_mailto_and_visible_text_emails():
    emails = extract_emails(HTML)
    assert "info@acme-realty.example" in emails
    assert "sales@acme-realty.example" in emails


def test_ignores_image_filenames_shaped_like_emails():
    emails = extract_emails(HTML)
    assert not any(e.endswith(".png") for e in emails)
    assert "sprite@2x.png" not in emails


def test_extracts_tel_link_and_visible_text_phones():
    phones = extract_phones(HTML)
    assert "+919000011111" in phones  # from tel: link
    assert "+919876543210" in phones  # mobile in visible text
    assert "+912025678901" in phones  # landline with STD code in visible text


def test_deduplicates_repeated_numbers():
    html_with_dupe = HTML + '<a href="tel:+919000011111">Call again</a>'
    phones = extract_phones(html_with_dupe)
    assert phones.count("+919000011111") == 1
