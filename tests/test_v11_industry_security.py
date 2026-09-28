import hashlib

import pytest
import requests
from bs4 import BeautifulSoup

from speaker_pipeline.industry import (
    IndustrySource,
    LeaderLink,
    _senior_title,
    collect_industry,
    extract_leader_links,
    parse_leader_profile,
    parse_target_profile,
)
from speaker_pipeline.names import names_match
from speaker_pipeline.structured_data import extract_structured_people
from speaker_pipeline.web import FetchError, OfficialWebClient


def source(selector=""):
    return IndustrySource(
        "Example Co",
        "example.com",
        "https://www.example.com/leadership",
        ("example.com",),
        selector=selector,
    )


@pytest.mark.parametrize("title", ["CEO", "C.E.O.", "Co-CEO", "Co‑CEO", "Founder & CEO"])
def test_ceo_abbreviations_are_senior_titles(title):
    assert _senior_title(title)


def test_name_matching_requires_first_family_and_exact_suffix_state():
    assert names_match("C.C. Wei", "C. C. Wei")
    assert names_match("Dr. Jensen Huang", "Jensen Huang")
    assert not names_match("Grace Smith", "Ada Smith")
    assert not names_match("Henry Nicholas II", "Henry Nicholas III")
    assert not names_match("Henry Nicholas", "Henry Nicholas III")
    assert not names_match("J. Huang", "Jensen Huang")
    assert names_match("Nicholas, Henry III", "Henry Nicholas III")
    assert names_match("Jensen Huang, Chairman and CEO", "Jensen Huang")


def test_profile_rejects_same_family_with_wrong_given_name_and_suffix():
    wrong_given = LeaderLink("https://example.com/ada", "Ada Smith")
    wrong_suffix = LeaderLink("https://example.com/henry", "Henry Nicholas III")
    assert (
        parse_leader_profile(
            "<main><h1>Grace Smith</h1><div class='title'>CEO</div></main>",
            wrong_given,
            source(),
        )
        is None
    )
    assert (
        parse_leader_profile(
            "<main><h1>Henry Nicholas II</h1><div class='title'>Founder</div></main>",
            wrong_suffix,
            source(),
        )
        is None
    )


def test_configured_investor_profile_link_is_not_blanket_blocked():
    html = "<a class='executive' href='/investor/person-details/tim'>Tim Cook</a>"
    links = extract_leader_links(html, source("a.executive"))
    assert [link.url for link in links] == ["https://www.example.com/investor/person-details/tim"]


def test_default_discovery_allows_founder_and_historical_profile_paths():
    html = """
      <a href='/company/history/morris-chang'>Morris Chang</a>
      <a href='/founders/henry-nicholas'>Henry Nicholas III</a>
    """
    assert [link.name_hint for link in extract_leader_links(html, source())] == [
        "Morris Chang",
        "Henry Nicholas III",
    ]


def test_jsonld_person_drives_identity_title_and_direct_email():
    html = """
      <script type="application/ld+json">
        {"@graph": [
          {"@type": "Organization", "name": "Example Co", "email": "careers@example.com"},
          {"@type": ["Thing", "Person"], "name": "Tim Cook", "jobTitle": "CEO",
           "email": "mailto:tim@example.com", "url": "https://example.com/tim"}
        ]}
      </script>
      <main><h1>Tim Cook</h1></main>
    """
    profile = parse_target_profile(
        html,
        "Tim Cook",
        source_url="https://example.com/tim",
        allowed_domains=("example.com",),
    )
    assert profile.matched
    assert profile.match_type == "Exact"
    assert profile.extraction_method == "JSON-LD Person"
    assert profile.title == "CEO"
    assert [route.email for route in profile.email_routes] == ["tim@example.com"]
    assert profile.email_routes[0].binding == "Person"


def test_jsonld_parser_ignores_malformed_data_and_organization_email():
    html = """
      <script type="application/ld+json">not-json</script>
      <script type="application/ld+json">
        {"@type": "Organization", "name": "Example Co", "email": "info@example.com"}
      </script>
    """
    assert extract_structured_people(BeautifulSoup(html, "html.parser")) == []


def test_jsonld_person_accepts_an_absolute_schema_type():
    html = """
      <script type="application/ld+json">
        {"@type": "https://schema.org/Person", "name": "Tim Cook", "jobTitle": "CEO"}
      </script>
    """
    assert extract_structured_people(BeautifulSoup(html, "html.parser"))[0].name == "Tim Cook"


def test_jsonld_identity_does_not_bind_an_unrelated_dom_email():
    html = """
      <script type="application/ld+json">
        {"@type": "Person", "name": "Tim Cook", "jobTitle": "CEO"}
      </script>
      <main><p><a href="mailto:bob@example.com">Email Bob</a></p></main>
    """
    profile = parse_target_profile(
        html,
        "Tim Cook",
        source_url="https://example.com/tim",
        allowed_domains=("example.com",),
    )
    assert profile.matched
    assert profile.email_routes == ()


def test_profile_email_binding_excludes_global_page_chrome():
    html = """
      <header><a href="mailto:press@example.com">Press</a></header>
      <nav><a href="mailto:jobs@example.com">Jobs</a></nav>
      <main>
        <h1>Tim Cook</h1><div class="title">CEO</div>
        <p class="contact"><a href="mailto:tim@example.com">Email Tim</a></p>
        <footer><a href="mailto:careers@example.com">Careers</a></footer>
      </main>
      <aside><a href="mailto:legal@example.com">Legal</a></aside>
    """
    profile = parse_target_profile(
        html,
        "Tim Cook",
        source_url="https://example.com/tim",
        allowed_domains=("example.com",),
    )
    assert [route.email for route in profile.email_routes] == ["tim@example.com"]
    assert profile.email_routes[0].is_direct


def test_target_parser_uses_the_matching_card_and_its_local_email():
    html = """
      <main>
        <h1>Executive Leadership</h1>
        <section class="leader-card">
          <h2>Ada Smith</h2><p class="title">CFO</p>
          <a href="mailto:ada@example.com">Email Ada</a>
        </section>
        <section class="leader-card">
          <h2>Tim Cook</h2><p class="title">Co-CEO</p>
          <a href="mailto:tim@example.com">Email Tim</a>
        </section>
      </main>
    """
    profile = parse_target_profile(
        html,
        "Tim Cook",
        source_url="https://example.com/leadership",
        allowed_domains=("example.com",),
    )
    assert profile.name == "Tim Cook"
    assert profile.title == "Co-CEO"
    assert [route.email for route in profile.email_routes] == ["tim@example.com"]


def test_target_helper_reports_alias_match():
    html = "<main><h1>Bill Gates</h1><div class='title'>Co-Founder</div></main>"
    profile = parse_target_profile(html, "William Gates", ("Bill Gates",))
    assert profile.matched
    assert profile.match_type == "Alias"
    assert profile.matched_alias == "Bill Gates"


def test_industry_limit_is_applied_after_profile_validation():
    leadership_url = "https://www.example.com/leadership"
    pages = {
        leadership_url: """
          <a href='/leaders/junior'>Junior Person</a>
          <a href='/leaders/senior'>Senior Person</a>
          <a href='/leaders/extra'>Extra Person</a>
        """,
        "https://www.example.com/leaders/junior": (
            "<main><h1>Junior Person</h1><div class='title'>Engineer</div></main>"
        ),
        "https://www.example.com/leaders/senior": (
            "<main><h1>Senior Person</h1><div class='title'>CEO</div></main>"
        ),
        "https://www.example.com/leaders/extra": (
            "<main><h1>Extra Person</h1><div class='title'>Founder</div></main>"
        ),
    }
    rows, _warnings = collect_industry(
        [source()],
        OfficialWebClient(fetcher=pages.__getitem__),
        limit_per_source=1,
    )
    assert [row["Full Name"] for row in rows] == ["Senior Person"]


def response(url, status, text="", headers=None):
    result = requests.Response()
    result.url = url
    result.status_code = status
    result.headers.update(headers or {})
    result._content = text.encode("utf-8")
    result.encoding = "utf-8"
    return result


class FakeSession:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses[url]


def public_resolver(host, _port):
    if host == "internal.example.com":
        return ("127.0.0.1",)
    return ("93.184.216.34",)


def live_client(responses):
    client = OfficialWebClient(
        allow_live_fetch=True,
        delay_seconds=0,
        resolver=public_resolver,
    )
    client.session = FakeSession(responses)
    return client


def test_manual_redirects_preserve_allowlist_and_page_metadata():
    client = live_client(
        {
            "https://example.com/robots.txt": response("https://example.com/robots.txt", 404),
            "https://example.com/start": response(
                "https://example.com/start", 302, headers={"Location": "/final"}
            ),
            "https://example.com/final": response(
                "https://example.com/final", 200, "<main>ok</main>", {"Content-Type": "text/html"}
            ),
        }
    )
    page = client.fetch_page("https://example.com/start", ("example.com",))
    assert page.requested_url == "https://example.com/start"
    assert page.final_url == "https://example.com/final"
    assert page.status_code == 200
    assert page.retrieved_at
    assert page.content_sha256 == hashlib.sha256(b"<main>ok</main>").hexdigest()
    assert all(call[1]["allow_redirects"] is False for call in client.session.calls)


def test_cross_allowlist_redirect_is_blocked_before_second_request():
    client = live_client(
        {
            "https://example.com/robots.txt": response("https://example.com/robots.txt", 404),
            "https://example.com/start": response(
                "https://example.com/start",
                302,
                headers={"Location": "https://evil.test/secret"},
            ),
        }
    )
    with pytest.raises(FetchError, match="outside Allowed Domains"):
        client.fetch("https://example.com/start", ("example.com",))
    assert [url for url, _ in client.session.calls] == [
        "https://example.com/robots.txt",
        "https://example.com/start",
    ]


def test_allowlisted_redirect_to_private_address_is_blocked_before_request():
    client = live_client(
        {
            "https://example.com/robots.txt": response("https://example.com/robots.txt", 404),
            "https://example.com/start": response(
                "https://example.com/start",
                302,
                headers={"Location": "https://internal.example.com/secret"},
            ),
        }
    )
    with pytest.raises(FetchError, match="non-public address"):
        client.fetch("https://example.com/start", ("example.com",))
    assert [url for url, _ in client.session.calls] == [
        "https://example.com/robots.txt",
        "https://example.com/start",
    ]


def test_live_fetch_rejects_nonstandard_ports_before_request():
    client = live_client({})
    with pytest.raises(FetchError, match="disallowed port"):
        client.fetch("https://example.com:8443/profile", ("example.com",))
    assert client.session.calls == []


@pytest.mark.parametrize("declared_size, body", [(9, b"ok"), (2, b"123456789")])
def test_response_size_limit_checks_declared_and_actual_bytes(monkeypatch, declared_size, body):
    monkeypatch.setattr("speaker_pipeline.web.MAX_RESPONSE_BYTES", 8)
    oversized = response(
        "https://example.com/profile",
        200,
        headers={"Content-Length": str(declared_size), "Content-Type": "text/html"},
    )
    oversized._content = body
    client = live_client(
        {
            "https://example.com/robots.txt": response("https://example.com/robots.txt", 404),
            "https://example.com/profile": oversized,
        }
    )
    with pytest.raises(FetchError, match="exceeds"):
        client.fetch("https://example.com/profile", ("example.com",))


def test_response_size_limit_also_applies_to_robots(monkeypatch):
    monkeypatch.setattr("speaker_pipeline.web.MAX_RESPONSE_BYTES", 8)
    robots = response("https://example.com/robots.txt", 200, "123456789")
    client = live_client({"https://example.com/robots.txt": robots})
    with pytest.raises(FetchError, match="exceeds"):
        client.fetch("https://example.com/profile", ("example.com",))
    assert [url for url, _kwargs in client.session.calls] == ["https://example.com/robots.txt"]


def test_fetch_compatibility_wrapper_still_returns_html_for_fixtures():
    client = OfficialWebClient(fetcher=lambda _url: "<main>fixture</main>")
    assert client.fetch("https://example.com/profile", ("example.com",)) == ("<main>fixture</main>")
    page = client.fetch_page("https://example.com/profile", ("example.com",))
    assert page.final_url == "https://example.com/profile"
    assert page.content_sha256
