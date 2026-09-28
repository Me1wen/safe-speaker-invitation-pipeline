"""Conservative industry leader discovery with explicit contact-route metadata."""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag

from .common import candidate_id, clean, email_allowed, host_allowed, split_domains, today_iso
from .names import clean_person_name, looks_like_person_name, names_match
from .structured_data import StructuredPerson, extract_structured_people
from .web import FetchError, OfficialWebClient

SENIOR_TITLE_PATTERNS = (
    re.compile(r"(?<![A-Za-z])(?:co[\s-]*)?c\.?\s*e\.?\s*o\.?(?![A-Za-z])", re.I),
    re.compile(r"\bchief\b", re.I),
    re.compile(r"\bpresident\b", re.I),
    re.compile(r"\bvice[\s-]+president\b", re.I),
    re.compile(r"\b(?:co[\s-]*)?founder\b", re.I),
    re.compile(r"\bchair(?:man|woman|person)?\b", re.I),
    re.compile(r"\bmanaging director\b", re.I),
    re.compile(r"\bexecutive director\b", re.I),
    re.compile(r"\bglobal head\b", re.I),
    re.compile(r"\bhead of\b", re.I),
    re.compile(r"\bsenior fellow\b", re.I),
)

PROFILE_PATH_SIGNALS = (
    "/leader",
    "/executive",
    "/management",
    "founder",
    "/history/",
    "history/",
    "/investor",
    "/bio",
    "/profile",
    "/people/",
    "/team/",
)

EXCLUDED_PATH_PARTS = (
    "/contact",
    "/privacy",
    "/terms",
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
    ("General Contact", re.compile(r"careers|jobs|recruit|(^|[._-])hr($|[._-])", re.I)),
    ("General Contact", re.compile(r"support|legal|privacy|webmaster", re.I)),
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
    binding: str = ""
    evidence_text: str = ""

    @property
    def is_direct(self) -> bool:
        return self.contact_type == "Direct" and self.binding in {"", "Person"}


@dataclass(frozen=True)
class TargetProfile:
    """Stable targeted-parser result independent of candidate-table schemas."""

    requested_name: str
    name: str
    title: str
    matched: bool
    match_type: str
    matched_alias: str
    senior_title: bool
    extraction_method: str
    email_routes: tuple[EmailRoute, ...]


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
    return names_match(name, hint)


def _senior_title(value: str) -> bool:
    title = re.sub(r"[‐‑‒–—−]", "-", clean(value))
    return any(pattern.search(title) for pattern in SENIOR_TITLE_PATTERNS)


def _matching_dom_name(
    soup: BeautifulSoup, expected_names: tuple[str, ...]
) -> tuple[str, str, Tag | None]:
    """Resolve the requested identity instead of trusting the first page heading."""

    nodes = [
        *soup.select("[data-name], .name, .leader-name, [itemprop='name'], h1, h2, h3, h4"),
        *soup.find_all("meta", attrs={"name": "person:name"}),
    ]
    seen: set[int] = set()
    for node in nodes:
        if id(node) in seen:
            continue
        seen.add(id(node))
        observed = clean_person_name(_first_value(node))
        if not looks_like_person_name(observed):
            continue
        for expected in expected_names:
            if names_match(observed, expected):
                return observed, expected, node
    return "", "", None


def _profile_title(
    soup: BeautifulSoup,
    matched_node: Tag | None,
    structured_title: str = "",
) -> str:
    if clean(structured_title):
        return clean(structured_title)

    selectors = (
        "[data-title]",
        "[itemprop='jobTitle']",
        ".title",
        ".leader-title",
        ".role",
        ".position",
    )
    scopes: list[Tag | BeautifulSoup] = []
    if matched_node is not None:
        current = matched_node.parent
        while isinstance(current, Tag) and len(scopes) < 6:
            scopes.append(current)
            if current.name in {"main", "article", "body"}:
                break
            current = current.parent
    scopes.append(soup)

    seen: set[int] = set()
    for scope in scopes:
        if id(scope) in seen:
            continue
        seen.add(id(scope))
        for selector in selectors:
            value = _first_value(scope.select_one(selector))
            if value:
                return value

    # Historical founder pages commonly express the role in a short prose line.
    for scope in scopes:
        for node in scope.find_all(("p", "span", "div", "h2", "h3"), limit=40):
            value = _first_value(node)
            if 0 < len(value) <= 240 and _senior_title(value):
                return value
    return _first_value(soup.find("meta", attrs={"name": "person:title"}))


def _focused_content(soup: BeautifulSoup) -> str:
    copy = BeautifulSoup(str(soup), "html.parser")
    for tag in copy(["script", "style", "noscript", "svg", "nav", "header", "footer", "aside"]):
        tag.decompose()
    main = copy.find("main") or copy.find("article") or copy.body or copy
    return clean(main.get_text(" "))


def _matching_structured_people(soup: BeautifulSoup, expected_name: str) -> list[StructuredPerson]:
    return [
        person
        for person in extract_structured_people(soup)
        if not expected_name or names_match(person.name, expected_name)
    ]


def _identity_count(scope: Tag) -> int:
    identities: set[str] = set()
    for node in scope.select("[data-name], .name, .leader-name, [itemprop='name'], h1, h2, h3, h4"):
        value = clean_person_name(_first_value(node))
        if looks_like_person_name(value) and not _senior_title(value):
            identities.add(value.casefold())
    return len(identities)


def _contains_email(scope: Tag) -> bool:
    return bool(
        scope.find("a", href=re.compile(r"^mailto:", re.I)) or EMAIL_RE.search(scope.get_text(" "))
    )


def _profile_scope(soup: BeautifulSoup, person_name: str) -> tuple[BeautifulSoup, bool]:
    """Return a chrome-free person container and whether its identity was bound."""

    matched_node: Tag | None = None
    if person_name:
        _observed, _expected, matched_node = _matching_dom_name(soup, (person_name,))

    scope: Tag | BeautifulSoup
    if matched_node is not None:
        person_container = matched_node.find_parent(attrs={"itemtype": re.compile(r"Person", re.I)})
        boundary = matched_node.find_parent(["article", "main"])
        if person_container is not None:
            scope = person_container
        elif boundary is not None and _identity_count(boundary) <= 1:
            scope = boundary
        elif boundary is not None:
            scope = matched_node.parent or boundary
            for ancestor in matched_node.parents:
                if ancestor is boundary:
                    break
                marker = clean(
                    " ".join(
                        [
                            str(ancestor.get("id", "")),
                            *[str(value) for value in ancestor.get("class", [])],
                        ]
                    )
                )
                semantic_container = bool(
                    ancestor.name in {"article", "li", "section"}
                    or re.search(
                        r"person|profile|bio|leader|executive|member|card|tile",
                        marker,
                        re.I,
                    )
                )
                if _identity_count(ancestor) <= 1 and (
                    _contains_email(ancestor) or semantic_container
                ):
                    scope = ancestor
                    break
        else:
            scope = matched_node.find_parent("article") or matched_node.parent or soup
    else:
        scope = soup.find("main") or soup.find("article") or soup.body or soup

    copy = BeautifulSoup(str(scope), "html.parser")
    for tag in copy(["script", "style", "noscript", "svg", "nav", "header", "footer", "aside"]):
        tag.decompose()
    return copy, matched_node is not None


def _email_candidates(scope: BeautifulSoup) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    for anchor in scope.find_all("a", href=True):
        href = str(anchor.get("href", ""))
        if not href.casefold().startswith("mailto:"):
            continue
        for email in EMAIL_RE.findall(href[7:].split("?", 1)[0]):
            context = clean(anchor.parent.get_text(" ") if anchor.parent else anchor.get_text(" "))
            candidates.append((email, context[:500]))
    content = _focused_content(scope)
    for email in EMAIL_RE.findall(content):
        position = content.casefold().find(email.casefold())
        start = max(0, position - 120)
        end = min(len(content), position + len(email) + 120)
        candidates.append((email, clean(content[start:end])))
    return candidates


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
    structured_people = _matching_structured_people(soup, link.name_hint)
    structured = structured_people[0] if structured_people else None
    dom_name, _matched_expected, matched_node = _matching_dom_name(soup, (link.name_hint,))
    name = clean_person_name(structured.name if structured else dom_name)
    title = _profile_title(
        soup,
        matched_node,
        structured.title if structured else "",
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
    person_name: str = "",
) -> list[EmailRoute]:
    soup = BeautifulSoup(html, "html.parser")
    structured_people = _matching_structured_people(soup, person_name) if person_name else []
    scope, scope_bound = _profile_scope(soup, person_name)
    candidates: list[tuple[str, str, str]] = []
    if not page_hint:
        for person in structured_people:
            if person.email:
                evidence = clean(f"{person.name} {person.title} {person.email}")
                candidates.append((person.email, "Person", evidence))
    # A JSON-LD Person record binds only the email embedded in that same record.
    # DOM emails must still be located inside a visible, name-bound profile scope.
    dom_binding = "Department" if page_hint else "Person" if scope_bound else ""
    candidates.extend(
        (email, dom_binding, evidence) for email, evidence in _email_candidates(scope)
    )
    output: list[EmailRoute] = []
    seen: set[str] = set()
    for email, binding, evidence in candidates:
        email = email.casefold().strip(".,;:")
        if email in seen or not email_allowed(email, domains):
            continue
        seen.add(email)
        contact_type = page_hint or classify_email(email)
        if page_hint == "Corporate Communications" and classify_email(email) != "Direct":
            contact_type = classify_email(email)
        if not page_hint and contact_type != "Direct":
            binding = "Department"
        if person_name and contact_type == "Direct" and binding != "Person":
            continue
        output.append(EmailRoute(email, contact_type, source_url, binding, evidence))
    return output


def parse_target_profile(
    html: str,
    target_name: str,
    aliases: tuple[str, ...] = (),
    *,
    source_url: str = "",
    allowed_domains: tuple[str, ...] = (),
) -> TargetProfile:
    """Parse one requested person and report exactly how the identity matched.

    ``source_url`` and ``allowed_domains`` are optional for identity-only parsing.
    Email routes are returned only when an official domain can be established.
    """

    soup = BeautifulSoup(html, "html.parser")
    requested_names = (target_name, *aliases)
    structured_people = extract_structured_people(soup)
    structured_match: StructuredPerson | None = None
    matched_against = ""
    for expected in requested_names:
        structured_match = next(
            (person for person in structured_people if names_match(person.name, expected)),
            None,
        )
        if structured_match:
            matched_against = expected
            break

    dom_name, dom_match, matched_node = _matching_dom_name(soup, requested_names)
    extraction_method = "JSON-LD Person" if structured_match else "DOM"
    observed_name = clean_person_name(structured_match.name if structured_match else dom_name)
    if not matched_against:
        matched_against = dom_match
    title = _profile_title(
        soup,
        matched_node,
        structured_match.title if structured_match else "",
    )
    matched = bool(matched_against and looks_like_person_name(observed_name))
    match_type = "Exact" if matched_against == target_name else "Alias" if matched else "No Match"
    route_domains = allowed_domains
    if not route_domains and source_url:
        route_domains = split_domains("", urlparse(source_url).hostname or "")
    routes = (
        tuple(
            extract_email_routes(
                html,
                source_url,
                route_domains,
                person_name=observed_name,
            )
        )
        if matched and route_domains
        else ()
    )
    return TargetProfile(
        requested_name=target_name,
        name=observed_name,
        title=title,
        matched=matched,
        match_type=match_type,
        matched_alias=matched_against if matched_against != target_name else "",
        senior_title=_senior_title(title),
        extraction_method=extraction_method,
        email_routes=routes,
    )


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
        accepted_for_source = 0
        for link in links:
            if limit_per_source > 0 and accepted_for_source >= limit_per_source:
                break
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
            profile_routes = extract_email_routes(
                profile_html,
                link.url,
                source.allowed_domains,
                person_name=row["Full Name"],
            )
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
            accepted_for_source += 1
    return rows, warnings
