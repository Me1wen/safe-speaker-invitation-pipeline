from speaker_pipeline.industry import (
    IndustrySource,
    LeaderLink,
    collect_industry,
    extract_email_routes,
    extract_leader_links,
    parse_leader_profile,
)
from speaker_pipeline.web import OfficialWebClient


def source(company="Example Co", host="example.com"):
    return IndustrySource(
        company,
        host,
        f"https://www.{host}/leadership",
        (host,),
        contact_page=f"https://www.{host}/contact",
        media_contact_page=f"https://www.{host}/media",
    )


def test_leader_links_reject_navigation_and_use_card_name():
    html = """
    <nav><a href='/products'>Products</a><a href='/about'>About Us</a></nav>
    <div class='leader-card'><h2>Jane Rivera</h2><a href='/leaders/jane'>Read bio</a></div>
    <a href='/leaders/lee'>Lee Chen</a>
    <a href='https://linkedin.com/in/jane'>Jane Rivera</a>
    """
    links = extract_leader_links(html, source())
    assert [(link.name_hint, link.url) for link in links] == [
        ("Jane Rivera", "https://www.example.com/leaders/jane"),
        ("Lee Chen", "https://www.example.com/leaders/lee"),
    ]


def test_profile_requires_name_match_and_senior_title():
    link = LeaderLink("https://www.example.com/leaders/jane", "Jane Rivera")
    valid = "<main><h1>Jane Rivera</h1><div class='title'>Chief AI Officer</div><p>machine learning</p></main>"
    junior = "<main><h1>Jane Rivera</h1><div class='title'>Product Manager</div></main>"
    wrong = "<main><h1>John Smith</h1><div class='title'>Chief AI Officer</div></main>"
    assert parse_leader_profile(valid, link, source())["Full Name"] == "Jane Rivera"
    assert parse_leader_profile(junior, link, source()) is None
    assert parse_leader_profile(wrong, link, source()) is None


def test_contact_type_is_separate_from_plain_email():
    routes = extract_email_routes(
        "<main>Media inquiries <a href='mailto:media@example.com'>media@example.com</a></main>",
        "https://www.example.com/media",
        ("example.com",),
        page_hint="Media Relations",
    )
    assert routes[0].email == "media@example.com"
    assert routes[0].contact_type == "Media Relations"


def test_industry_collection_keeps_working_after_one_company_fails():
    bad = source("Bad Co", "bad.example")
    good = source()
    pages = {
        good.leadership_page: "<a href='/leaders/jane'>Jane Rivera</a>",
        "https://www.example.com/leaders/jane": """
          <main><h1>Jane Rivera</h1><div class='title'>Chief AI Officer</div>
          <p>Artificial intelligence</p></main>
        """,
        good.contact_page: "<main><a href='mailto:info@example.com'>Contact</a></main>",
        good.media_contact_page: "<main><a href='mailto:media@example.com'>Media</a></main>",
    }
    rows, warnings = collect_industry([bad, good], OfficialWebClient(fetcher=pages.__getitem__))
    assert len(rows) == 1
    assert rows[0]["Email"] == "media@example.com"
    assert rows[0]["Contact Type"] == "Media Relations"
    assert any("Bad Co" in warning for warning in warnings)
