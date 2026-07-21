"""Conservative academic profile discovery and extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from .common import candidate_id, clean, email_allowed, host_allowed, split_domains, today_iso
from .web import FetchError, OfficialWebClient

ACADEMIC_TITLES = (
    "Distinguished Professor",
    "Institute Director",
    "Department Chair",
    "Laboratory Director",
    "Lab Director",
    "Associate Professor",
    "Assistant Professor",
    "Professor Emeritus",
    "Professor",
)

RESEARCH_CATEGORIES = {
    "Artificial intelligence": ("artificial intelligence", "intelligent systems"),
    "Machine learning": ("machine learning", "deep learning", "reinforcement learning"),
    "Computer vision": ("computer vision", "visual recognition", "image understanding"),
    "Robotics": ("robotics", "robot learning", "autonomous robots"),
    "Human-computer interaction": (
        "human-computer interaction",
        "human computer interaction",
        "hci",
    ),
    "Computer systems": ("computer systems", "operating systems", "cloud computing"),
    "Distributed computing": ("distributed computing", "distributed systems"),
    "Security and privacy": ("computer security", "cybersecurity", "privacy", "cryptography"),
    "Databases": ("database systems", "databases", "data management"),
    "Networks": ("computer networks", "networking", "network systems"),
    "Computer architecture": ("computer architecture", "processor architecture"),
    "Semiconductors": ("semiconductor", "microelectronics", "electronic devices"),
    "Circuits": ("integrated circuits", "circuit design", "vlsi", "analog circuits"),
    "Signal processing": ("signal processing", "image processing", "speech processing"),
    "Wireless systems": ("wireless systems", "wireless communication", "mobile systems"),
    "Data science": ("data science", "data analytics", "data mining"),
}

BLOCKED_NAME_PHRASES = {
    "administrative staff",
    "associated faculty",
    "faculty",
    "faculty home page",
    "faculty profile",
    "in memoriam",
    "people",
    "read bio",
    "read more",
    "research staff",
    "staff",
    "technical staff",
    "view profile",
}

EXCLUDED_PATH_PARTS = (
    "/admissions",
    "/alumni",
    "/calendar",
    "/courses",
    "/events",
    "/news",
    "/publications",
    "/staff",
    "/students",
    "/in-memoriam",
    "/admins",
    "/restech",
)

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:\+\d{1,3}[\s.()-]*)?(?:\(\d{3}\)|\d{3})[\s.-]*\d{3}[\s.-]*\d{4}\b")
GENERIC_EMAIL_TOKENS = {
    "admissions",
    "communications",
    "contact",
    "department",
    "events",
    "help",
    "info",
    "media",
    "office",
    "press",
    "privacy",
    "search",
    "support",
    "webmaster",
}


@dataclass(frozen=True)
class AcademicSource:
    organization: str
    directory_url: str
    allowed_domains: tuple[str, ...]
    selector: str = ""

    @classmethod
    def from_row(cls, row: dict[str, str]) -> AcademicSource:
        return cls(
            organization=clean(row.get("Organization")),
            directory_url=clean(row.get("Department Directory URL")),
            allowed_domains=split_domains(row.get("Allowed Domains", "")),
            selector=clean(row.get("Profile Link Selector")),
        )


@dataclass(frozen=True)
class ProfileLink:
    url: str
    name_hint: str
    source: AcademicSource


def clean_person_name(value: str) -> str:
    value = clean(value)
    for separator in (" | ", " - ", " – ", " — ", ":"):
        if separator in value:
            value = value.split(separator, 1)[0]
    value = re.sub(r"^(?:Dr|Prof|Professor)\.?\s+", "", value, flags=re.I)
    value = re.sub(
        r",?\s+(?:Ph\.?D\.?|Professor|Associate Professor|Assistant Professor).*$",
        "",
        value,
        flags=re.I,
    )
    if value.count(",") == 1:
        family, given = [clean(part) for part in value.split(",", 1)]
        if family and given:
            value = f"{given} {family}"
    return clean(value.strip(" ,"))


def looks_like_person_name(value: str) -> bool:
    value = clean_person_name(value)
    if value.casefold() in BLOCKED_NAME_PHRASES:
        return False
    words = value.split()
    if not 2 <= len(words) <= 6:
        return False
    if any(
        word.casefold() in {"staff", "faculty", "department", "office", "team", "administration"}
        for word in words
    ):
        return False
    return all(re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ'’.\-]+", word) for word in words)


def _name_matches_hint(name: str, hint: str) -> bool:
    if not hint:
        return True
    left = {
        word.casefold().strip(".'-") for word in clean_person_name(name).split() if len(word) > 1
    }
    right = {
        word.casefold().strip(".'-") for word in clean_person_name(hint).split() if len(word) > 1
    }
    return (
        bool(left and right and left & right)
        and clean_person_name(name).split()[-1].casefold()
        == clean_person_name(hint).split()[-1].casefold()
    )


def discover_profile_links(html: str, source: AcademicSource) -> list[ProfileLink]:
    soup = BeautifulSoup(html, "html.parser")
    try:
        anchors = soup.select(source.selector) if source.selector else soup.find_all("a", href=True)
    except Exception as exc:
        raise ValueError(f"Invalid Profile Link Selector {source.selector!r}: {exc}") from exc
    output: list[ProfileLink] = []
    seen: set[str] = set()
    directory = urldefrag(source.directory_url)[0].rstrip("/")
    for anchor in anchors:
        href = clean(anchor.get("href", ""))
        label = clean_person_name(anchor.get_text(" "))
        if not href or not looks_like_person_name(label):
            continue
        url = urldefrag(urljoin(source.directory_url, href))[0]
        parsed = urlparse(url)
        path = parsed.path.casefold().rstrip("/")
        if url.rstrip("/") == directory or not host_allowed(url, source.allowed_domains):
            continue
        if any(part in path for part in EXCLUDED_PATH_PARTS):
            continue
        profile_signal = any(
            signal in path
            for signal in (
                "/people/",
                "/person/",
                "/profile/",
                "/faculty/",
                "/faculty/homepages/",
                "~",
            )
        )
        if not source.selector and not profile_signal:
            continue
        if url not in seen:
            seen.add(url)
            output.append(ProfileLink(url, label, source))
    return output


def _content_text(soup: BeautifulSoup) -> str:
    copy = BeautifulSoup(str(soup), "html.parser")
    for tag in copy(["script", "style", "noscript", "svg", "nav", "header", "footer", "aside"]):
        tag.decompose()
    main = copy.find("main") or copy.find("article") or copy.body or copy
    return clean(main.get_text(" "))


def _find_name(soup: BeautifulSoup, hint: str) -> str:
    candidates: list[str] = []
    for attrs in ({"property": "og:title"}, {"name": "twitter:title"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            candidates.append(str(tag["content"]))
    for heading in soup.find_all("h1", limit=3):
        candidates.append(heading.get_text(" "))
    candidates.append(hint)
    for candidate in candidates:
        name = clean_person_name(candidate)
        if looks_like_person_name(name) and _name_matches_hint(name, hint):
            return name
    return ""


def _find_title(soup: BeautifulSoup, content: str) -> str:
    focused: list[str] = []
    pattern = re.compile(r"title|position|role|appointment", re.I)
    for tag in soup.find_all(class_=pattern, limit=20):
        focused.append(clean(tag.get_text(" ")))
    haystacks = [" ".join(focused), content[:2500]]
    for haystack in haystacks:
        for title in ACADEMIC_TITLES:
            if title.casefold() in haystack.casefold():
                return title
    return ""


def _find_email(soup: BeautifulSoup, content: str, domains: tuple[str, ...]) -> str:
    candidates: list[str] = []
    for link in soup.find_all("a", href=True):
        href = str(link.get("href", ""))
        if href.casefold().startswith("mailto:"):
            candidates.extend(EMAIL_RE.findall(href[7:].split("?", 1)[0]))
    deobfuscated = re.sub(r"\s*(?:\[at\]|\(at\))\s*", "@", content, flags=re.I)
    deobfuscated = re.sub(r"\s*(?:\[dot\]|\(dot\))\s*", ".", deobfuscated, flags=re.I)
    candidates.extend(EMAIL_RE.findall(deobfuscated))
    for email in candidates:
        email = email.casefold().strip(".,;:")
        local = email.split("@", 1)[0]
        tokens = set(re.split(r"[._+\-]+", local))
        if not tokens & GENERIC_EMAIL_TOKENS and email_allowed(email, domains):
            return email
    return ""


def _find_expertise(soup: BeautifulSoup, content: str) -> str:
    focused: list[str] = []
    pattern = re.compile(r"research|expertise|interest|bio|about", re.I)
    for tag in soup.find_all(class_=pattern, limit=20):
        focused.append(clean(tag.get_text(" ")))
    search_text = " ".join(focused) or content
    lowered = search_text.casefold()
    categories = [
        label
        for label, phrases in RESEARCH_CATEGORIES.items()
        if any(phrase in lowered for phrase in phrases)
    ]
    return "; ".join(categories[:6])


def _salutation(name: str) -> str:
    return f"Dr. {name.split()[-1]}" if name else ""


def extract_profile(html: str, link: ProfileLink) -> dict[str, str] | None:
    soup = BeautifulSoup(html, "html.parser")
    content = _content_text(soup)
    name = _find_name(soup, link.name_hint)
    title = _find_title(soup, content)
    email = _find_email(soup, content, link.source.allowed_domains)
    if not name or not title or not email:
        return None
    phone_match = PHONE_RE.search(content)
    return {
        "Candidate ID": candidate_id("Academic", name, link.source.organization),
        "Speaker Type": "Academic",
        "Review Status": "Draft",
        "Full Name": name,
        "Organization": link.source.organization,
        "Title": title,
        "Expertise": _find_expertise(soup, content),
        "Topic Fit": "",
        "Preferred Salutation": _salutation(name),
        "Email": email,
        "Contact Type": "Direct",
        "Email Source URL": link.url,
        "Phone": clean(phone_match.group(0)) if phone_match else "",
        "Profile URL": link.url,
        "Discovery Source URL": link.source.directory_url,
        "Notes": "",
        "Last Checked": today_iso(),
    }


def collect_academic(
    sources: list[AcademicSource],
    client: OfficialWebClient,
    *,
    limit_per_source: int = 0,
) -> tuple[list[dict[str, str]], list[str]]:
    rows: list[dict[str, str]] = []
    warnings: list[str] = []
    seen_urls: set[str] = set()
    for source in sources:
        if not source.organization or not source.directory_url or not source.allowed_domains:
            warnings.append(
                f"Skipped incomplete academic source: {source.organization or '[blank]'}"
            )
            continue
        try:
            directory_html = client.fetch(source.directory_url, source.allowed_domains)
            links = discover_profile_links(directory_html, source)
        except (FetchError, ValueError) as exc:
            warnings.append(f"{source.organization}: {exc}")
            continue
        if limit_per_source > 0:
            links = links[:limit_per_source]
        if not links:
            warnings.append(f"{source.organization}: no plausible person profile links found")
        for link in links:
            if link.url in seen_urls:
                continue
            seen_urls.add(link.url)
            try:
                html = client.fetch(link.url, source.allowed_domains)
                row = extract_profile(html, link)
            except FetchError as exc:
                warnings.append(str(exc))
                continue
            if row:
                rows.append(row)
    return rows, warnings
