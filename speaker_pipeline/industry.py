"""Conservative industry leader discovery with explicit contact-route metadata."""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from .academic import clean_person_name, looks_like_person_name
from .common import candidate_id, clean, email_allowed, host_allowed, split_domains, today_iso
from .web import FetchError, OfficialWebClient

SENIOR_TITLE_TERMS = (
    "chief ",
    "chief executive",
    "chief technology",
    "chief science",
    "chief research",
    "president",
    "vice president",
    "vice-president",
    "founder",
    "co-founder",
    "chair",
    "managing director",
    "executive director",
    "global head",
    "head of",
    "senior fellow",
)

PROFILE_PATH_SIGNALS = (
    "/leader",
    "/executive",
    "/management",
    "/bio",
    "/profile",
    "/people/",
    "/team/",
)

EXCLUDED_PATH_PARTS = (
    "/contact",
    "/privacy",
    "/terms",
    "/investor",
    "/newsroom",
    "/careers",
    "/products",
    "/services",
    "/events",
)

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:\+\d{1,3}[\s.()-]*)?(?:\(\d{3}\)|\d{3})[\s.-]*\d{3}[\s.-]*\d{4}\b")
GENERIC_EMAIL_PATTERNS = (
    ("Corporate Communications", re.compile(r"corp|corporate|communication|comm", re.I)),
    ("Media Relations", re.compile(r"media|press|news|(^|[._-])pr($|[._-])", re.I)),
    ("Investor Relations", re.compile(r"(^|[._-])ir($|[._-])|investor|shareholder", re.I)),
    ("Public Affairs", re.compile(r"public.?affairs|policy|government", re.I)),
    ("Executive Office", re.compile(r"executive|office.?of.?the|ceo.?office", re.I)),
    ("University Relations", re.compile(r"university|campus|academic", re.I)),
    ("Speaker Inquiry", re.compile(r"speaker|event|conference", re.I)),
    ("General Contact", re.compile(r"info|contact|hello|inquiries|enquiries", re.I)),
)


@dataclass(frozen=True)
class IndustrySource:
    company: str
    official_domain: str
    leadership_page: str
    allowed_domains: tuple[str, ...]
    selector: str = ""
    contact_page: str = ""
    media_contact_page: str = ""
    investor_relations_page: str = ""

    @classmethod
    def from_row(cls, row: dict[str, str]) -> IndustrySource:
        official_domain = clean(row.get("Official Domain"))
        return cls(
            company=clean(row.get("Company")),
            official_domain=official_domain,
            leadership_page=clean(row.get("Leadership Page")),
            allowed_domains=split_domains(row.get("Allowed Domains", ""), official_domain),
            selector=clean(row.get("Profile Link Selector")),
            contact_page=clean(row.get("Contact Page")),
            media_contact_page=clean(row.get("Media Contact Page")),
            investor_relations_page=clean(row.get("Investor Relations Page")),
        )

    @property
    def contact_pages(self) -> list[tuple[str, str]]:
        return [
            ("Corporate Communications", self.contact_page),
            ("Media Relations", self.media_contact_page),
            ("Investor Relations", self.investor_relations_page),
        ]


@dataclass(frozen=True)
class LeaderLink:
    url: str
    name_hint: str


@dataclass(frozen=True)
class EmailRoute:
    email: str
    contact_type: str
    source_url: str

    @property
    def is_direct(self) -> bool:
        return self.contact_type == "Direct"


def _parent_name_hint(anchor) -> str:
    for parent in list(anchor.parents)[:4]:
        if not getattr(parent, "find", None):
            continue
        node = parent.select_one("[data-name], .name, .leader-name, h2, h3, h4")
        if node:
            value = node.get("data-name", "") if node.has_attr("data-name") else node.get_text(" ")
            value = clean_person_name(value)
            if looks_like_person_name(value):
                return value
    return ""


def extract_leader_links(html: str, source: IndustrySource) -> list[LeaderLink]:
    soup = BeautifulSoup(html, "html.parser")
    try:
        anchors = soup.select(source.selector) if source.selector else soup.find_all("a", href=True)
    except Exception as exc:
        raise ValueError(f"Invalid Profile Link Selector {source.selector!r}: {exc}") from exc
    output: list[LeaderLink] = []
    seen: set[str] = set()
    for anchor in anchors:
        href = clean(anchor.get("href", ""))
        if not href:
            continue
        url = urldefrag(urljoin(source.leadership_page, href))[0]
        path = urlparse(url).path.casefold()
        if not host_allowed(url, source.allowed_domains) or any(
            part in path for part in EXCLUDED_PATH_PARTS
        ):
            continue
        label = clean_person_name(anchor.get_text(" "))
        hint = label if looks_like_person_name(label) else _parent_name_hint(anchor)
        if not hint:
            continue
        if not source.selector and not any(signal in path for signal in PROFILE_PATH_SIGNALS):
            continue
        if url not in seen:
            seen.add(url)
            output.append(LeaderLink(url, hint))
    return output


def _first_value(*nodes) -> str:
    for node in nodes:
        if not node:
            continue
        if getattr(node, "name", None) == "meta":
            value = node.get("content", "")
        elif node.has_attr("data-name"):
            value = node.get("data-name", "")
        elif node.has_attr("data-title"):
            value = node.get("data-title", "")
        elif node.has_attr("data-expertise"):
            value = node.get("data-expertise", "")
        else:
            value = node.get_text(" ")
        value = clean(html_lib.unescape(str(value)))
        if value:
            return value
    return ""


def _name_matches(name: str, hint: str) -> bool:
    name = clean_person_name(name)
    hint = clean_person_name(hint)
    return bool(name and hint and name.split()[-1].casefold() == hint.split()[-1].casefold())


def _senior_title(value: str) -> bool:
    lowered = clean(value).casefold()
    return any(term in lowered for term in SENIOR_TITLE_TERMS)


def _focused_content(soup: BeautifulSoup) -> str:
    copy = BeautifulSoup(str(soup), "html.parser")
    for tag in copy(["script", "style", "noscript", "svg", "nav", "header", "footer", "aside"]):
        tag.decompose()
    main = copy.find("main") or copy.find("article") or copy.body or copy
    return clean(main.get_text(" "))


def _infer_expertise(text: str) -> str:
    buckets = [
        ("artificial intelligence", "Artificial intelligence"),
        ("machine learning", "Machine learning"),
        ("cloud", "Cloud computing"),
        ("semiconductor", "Semiconductors"),
        ("finance", "Financial markets"),
        ("investment", "Investment strategy"),
        ("biotech", "Biotechnology"),
        ("genomics", "Genomics"),
        ("sustainability", "Sustainability"),
        ("renewable", "Renewable energy"),
        ("product", "Product innovation"),
        ("research", "Research leadership"),
        ("engineering", "Engineering leadership"),
    ]
    lowered = text.casefold()
    return "; ".join(label for needle, label in buckets if needle in lowered)[:500]


def parse_leader_profile(
    html: str, link: LeaderLink, source: IndustrySource
) -> dict[str, str] | None:
    soup = BeautifulSoup(html, "html.parser")
    name = clean_person_name(
        _first_value(
            soup.select_one("[data-name]"),
            soup.select_one(".name"),
            soup.select_one(".leader-name"),
            soup.find("meta", attrs={"name": "person:name"}),
            soup.select_one("h1"),
        )
    )
    title = _first_value(
        soup.select_one("[data-title]"),
        soup.select_one(".title"),
        soup.select_one(".leader-title"),
        soup.find("meta", attrs={"name": "person:title"}),
        soup.select_one("h2"),
    )
    if (
        not looks_like_person_name(name)
        or not _name_matches(name, link.name_hint)
        or not _senior_title(title)
    ):
        return None
    focused = _focused_content(soup)
    expertise = _first_value(
        soup.select_one("[data-expertise]"),
        soup.select_one(".expertise"),
        soup.find("meta", attrs={"name": "keywords"}),
    ) or _infer_expertise(focused)
    phone_match = PHONE_RE.search(focused)
    return {
        "Candidate ID": candidate_id("Industry", name, source.company),
        "Speaker Type": "Industry",
        "Review Status": "Draft",
        "Full Name": name,
        "Organization": source.company,
        "Title": title,
        "Expertise": expertise,
        "Topic Fit": "",
        "Preferred Salutation": name,
        "Email": "",
        "Contact Type": "",
        "Email Source URL": "",
        "Phone": clean(phone_match.group(0)) if phone_match else "",
        "Profile URL": link.url,
        "Discovery Source URL": source.leadership_page,
        "Notes": "",
        "Last Checked": today_iso(),
    }


def classify_email(email: str) -> str:
    local = email.split("@", 1)[0]
    for contact_type, pattern in GENERIC_EMAIL_PATTERNS:
        if pattern.search(local):
            return contact_type
    return "Direct"


def extract_email_routes(
    html: str,
    source_url: str,
    domains: tuple[str, ...],
    *,
    page_hint: str = "",
) -> list[EmailRoute]:
    soup = BeautifulSoup(html, "html.parser")
    content = _focused_content(soup)
    candidates: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href", ""))
        if href.casefold().startswith("mailto:"):
            candidates.extend(EMAIL_RE.findall(href[7:].split("?", 1)[0]))
    candidates.extend(EMAIL_RE.findall(content))
    output: list[EmailRoute] = []
    seen: set[str] = set()
    for email in candidates:
        email = email.casefold().strip(".,;:")
        if email in seen or not email_allowed(email, domains):
            continue
        seen.add(email)
        contact_type = page_hint or classify_email(email)
        if page_hint == "Corporate Communications" and classify_email(email) != "Direct":
            contact_type = classify_email(email)
        output.append(EmailRoute(email, contact_type, source_url))
    return output


def select_route(
    profile_routes: list[EmailRoute], generic_routes: list[EmailRoute]
) -> EmailRoute | None:
    direct = [route for route in profile_routes if route.is_direct]
    if direct:
        return direct[0]
    ranking = {
        "Speaker Inquiry": 0,
        "Executive Office": 1,
        "Public Affairs": 2,
        "Corporate Communications": 3,
        "Media Relations": 4,
        "Investor Relations": 5,
        "General Contact": 6,
    }
    routes = [*profile_routes, *generic_routes]
    return min(routes, key=lambda route: ranking.get(route.contact_type, 99)) if routes else None


def collect_industry(
    sources: list[IndustrySource],
    client: OfficialWebClient,
    *,
    limit_per_source: int = 0,
) -> tuple[list[dict[str, str]], list[str]]:
    rows: list[dict[str, str]] = []
    warnings: list[str] = []
    seen_profiles: set[str] = set()
    for source in sources:
        if not source.company or not source.leadership_page or not source.allowed_domains:
            warnings.append(f"Skipped incomplete industry source: {source.company or '[blank]'}")
            continue
        try:
            leadership_html = client.fetch(source.leadership_page, source.allowed_domains)
            links = extract_leader_links(leadership_html, source)
        except (FetchError, ValueError) as exc:
            warnings.append(f"{source.company}: {exc}")
            continue
        if limit_per_source > 0:
            links = links[:limit_per_source]
        generic_routes: list[EmailRoute] = []
        for hint, url in source.contact_pages:
            if not url:
                continue
            try:
                contact_html = client.fetch(url, source.allowed_domains)
                generic_routes.extend(
                    extract_email_routes(contact_html, url, source.allowed_domains, page_hint=hint)
                )
            except FetchError as exc:
                warnings.append(str(exc))
        if not links:
            warnings.append(f"{source.company}: no plausible senior-leader profile links found")
        for link in links:
            normalized = urldefrag(link.url)[0]
            if normalized in seen_profiles:
                continue
            seen_profiles.add(normalized)
            try:
                profile_html = client.fetch(link.url, source.allowed_domains)
            except FetchError as exc:
                warnings.append(str(exc))
                continue
            row = parse_leader_profile(profile_html, link, source)
            if not row:
                continue
            profile_routes = extract_email_routes(profile_html, link.url, source.allowed_domains)
            route = select_route(profile_routes, generic_routes)
            if route:
                row["Email"] = route.email
                row["Contact Type"] = route.contact_type
                row["Email Source URL"] = route.source_url
            else:
                row["Review Status"] = "Needs Review"
                row["Notes"] = (
                    "No public official email route was found. Add a verified route before approval."
                )
            rows.append(row)
    return rows, warnings
