from worker.crawling.content_extraction import extract_clean_html, html_to_markdown

ARTICLE_LIKE_HTML = """
<html><body>
<nav><a href="/">Home</a><a href="/about">About</a></nav>
<main>
  <h1>About Acme Realty</h1>
  <p>Acme Realty has been serving Pune homebuyers since 2010, specializing in
  residential resale across Kothrud, Baner, and Koregaon Park.</p>
</main>
<footer>Copyright 2026 Acme Realty. All rights reserved.</footer>
</body></html>
"""

SPARSE_CONTACT_HTML = """
<html><body>
<nav><a href="/">Home</a></nav>
<form><input name="email"><button>Send</button></form>
<address>123 FC Road, Pune</address>
</body></html>
"""


def test_extracts_main_content_and_drops_nav_footer_boilerplate():
    clean = extract_clean_html(ARTICLE_LIKE_HTML, "https://acme-realty.example/about")
    assert "Acme Realty has been serving Pune" in clean
    assert "Copyright 2026" not in clean


def test_falls_back_to_raw_html_for_text_sparse_pages():
    # trafilatura is tuned for article-like content and can return None here;
    # the fallback must still surface the page's actual content (the address).
    clean = extract_clean_html(SPARSE_CONTACT_HTML, "https://acme-realty.example/contact")
    assert "123 FC Road" in clean


def test_html_to_markdown_produces_heading_and_body_text():
    clean = extract_clean_html(ARTICLE_LIKE_HTML, "https://acme-realty.example/about")
    markdown = html_to_markdown(clean)
    assert "Acme Realty has been serving Pune" in markdown
