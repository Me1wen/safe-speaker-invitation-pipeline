"""Target-driven industry verification with one auditable result per person.

This module is deliberately separate from broad leadership-page discovery.  It
starts from an explicit :class:`~speaker_pipeline.targets.IndustryTarget`, only
requests pages inside that target's allowlist, and records identity and role
evidence even when no usable email address is published.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from .common import candidate_id, clean, host_allowed, split_domains, today_iso
from .evidence import EvidenceRecord, best_email_evidence, merge_evidence
from .industry import (
    EmailRoute,
    IndustrySource,
    TargetProfile,
    extract_email_routes,
    extract_leader_links,
    parse_target_profile,
    select_route,
)
from .names import clean_person_name, names_match
from .schema import CANDIDATE_COLUMNS, EMAIL_EVIDENCE_RANK, SCHEMA_VERSION
from .targets import Campaign, EmailClaim, IndustryTarget, TargetReport
from .web import FetchError, OfficialWebClient, Page

EXTRACTOR_VERSION = "targeted-industry-v1.1"

_ROLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "CEO",
        re.compile(
            r"(?<![a-z])(?:co[\s-]*)?c\.?\s*e\.?\s*o\.?(?![a-z])|chief executive officer", re.I
        ),
    ),
    ("Founder", re.compile(r"\b(?:co[\s-]*)?founder\b|\bfounded\b", re.I)),
    ("Executive Vice Chair", re.compile(r"\bexecutive vice chair(?:man|woman|person)?\b", re.I)),
    ("Executive Chair", re.compile(r"\bexecutive chair(?:man|woman|person)?\b", re.I)),
    ("Chair", re.compile(r"\bchair(?:man|woman|person)?\b", re.I)),
    ("CTO", re.compile(r"(?<![a-z])c\.?\s*t\.?\s*o\.?(?![a-z])|chief technology officer", re.I)),
    ("President", re.compile(r"\bpresident\b", re.I)),
    ("Director", re.compile(r"\bdirector\b", re.I)),
)
_DECEASED_RE = re.compile(r"\b(?:died|deceased|passed away|late)\b", re.I)
_RETIRED_RE = re.compile(r"\bretir(?:ed|ement)\b", re.I)
_FORMER_RE = re.compile(r"\b(?:former|previously|served as|stepped down)\b", re.I)


@dataclass(frozen=True)
class _ParsedTarget:
    profile: TargetProfile
    context: str
    locator: str


def _matches_target(target: IndustryTarget, observed: str) -> bool:
    return any(names_match(observed, expected) for expected in target.names)


def _roles(value: str) -> set[str]:
    return {label for label, pattern in _ROLE_PATTERNS if pattern.search(clean(value))}


def role_match_status(requested_role: str, observed_title: str, *, person_status: str) -> str:
    """Compare role vocabulary without treating a former CEO as a current CEO."""

    requested = _roles(requested_role)
    observed = _roles(observed_title)
    if not requested or not clean(observed_title):
        return "Unverified"
    if requested.issubset(observed):
        if person_status in {"Former", "Retired", "Historical", "Deceased"}:
            return "Historical Match"
        return "Match"
    if requested & observed:
        return "Partial Match"
    return "Different"


def _person_status(target: IndustryTarget, context: str, title: str) -> str:
    relationship = target.relationship_type.casefold()
    curated = clean(f"{title} {target.notes}")
    bounded = clean(f"{context} {curated}")
    if _DECEASED_RE.search(bounded):
        return "Deceased"
    # Current biographies often say an executive "previously served as" some
    # unrelated role.  Such background prose must not turn a current CEO into a
    # former target; broad temporal words are consulted only for historical or
    # founder records, while current-executive overrides must be explicit.
    temporal_text = bounded if relationship in {"historical", "founder"} else curated
    if _RETIRED_RE.search(temporal_text):
        return "Retired"
    if _FORMER_RE.search(temporal_text):
        return "Former"
    if relationship == "historical":
        return "Historical"
    return "Current"


def _temporal_status(person_status: str) -> str:
    if person_status == "Current":
        return "Current"
    if person_status in {"Former", "Retired"}:
        return "Former"
    return "Historical Fact"


def _extract_title(text: str) -> str:
    labels = [label for label, pattern in _ROLE_PATTERNS if pattern.search(text)]
    if not labels:
        return ""
    prefix = "Former " if _FORMER_RE.search(text) else ""
    return prefix + " and ".join(dict.fromkeys(labels))


def _normalized_contains_name(text: str, expected: str) -> bool:
    haystack = re.sub(r"[^a-z0-9]+", " ", clean(text).casefold()).strip()
    needle = re.sub(r"[^a-z0-9]+", " ", clean(expected).casefold()).strip()
    return bool(needle and re.search(rf"(?:^|\s){re.escape(needle)}(?:$|\s)", haystack))


def _candidate_scopes(soup: BeautifulSoup, target: IndustryTarget):
    selectors = "[data-name], .name, .leader-name, [itemprop='name'], h1, h2, h3, h4"
    for node in soup.select(selectors):
        raw = node.get("data-name", "") if node.has_attr("data-name") else node.get_text(" ")
        observed = clean_person_name(str(raw))
        if not _matches_target(target, observed):
            continue
        scope = (
            node.find_parent(attrs={"itemtype": re.compile(r"Person", re.I)})
            or node.find_parent("article")
            or node.find_parent("li")
            or node.find_parent("section")
            or node.find_parent("div")
            or node.parent
            or node
        )
        yield observed, scope


def _parse_target_page(
    page: Page,
    target: IndustryTarget,
    allowed_domains: tuple[str, ...],
) -> _ParsedTarget | None:
    profile = parse_target_profile(
        page.html,
        target.full_name,
        target.name_aliases,
        source_url=page.final_url,
        allowed_domains=allowed_domains,
    )
    soup = BeautifulSoup(page.html, "html.parser")
    if profile.matched:
        # Status words belonging to another leader on a shared directory page
        # must not leak into this target.  Use an exact-name container when one
        # exists; JSON-LD-only matches fall back to title + curated target notes.
        matched_scope = next(_candidate_scopes(soup, target), None)
        scope_text = (
            clean(matched_scope[1].get_text(" "))
            if matched_scope is not None
            else clean(profile.title)
        )
        return _ParsedTarget(profile, scope_text, profile.extraction_method)

    for observed, scope in _candidate_scopes(soup, target):
        scoped_html = str(scope)
        scoped = parse_target_profile(
            scoped_html,
            target.full_name,
            target.name_aliases,
            source_url=page.final_url,
            allowed_domains=allowed_domains,
        )
        context = clean(scope.get_text(" "))
        if scoped.matched:
            return _ParsedTarget(scoped, context, "Person container")

        # Some history pages use a name heading plus prose instead of a title
        # field.  Identity remains exact because the heading itself was matched.
        title = _extract_title(context)
        routes = tuple(
            extract_email_routes(
                scoped_html,
                page.final_url,
                allowed_domains,
                person_name=observed,
            )
        )
        manual = TargetProfile(
            requested_name=target.full_name,
            name=observed,
            title=title,
            matched=True,
            match_type=("Exact" if names_match(observed, target.full_name) else "Alias"),
            matched_alias=(observed if not names_match(observed, target.full_name) else ""),
            senior_title=bool(_roles(title)),
            extraction_method="Person container",
            email_routes=routes,
        )
        return _ParsedTarget(manual, context, "Person container")

    # Last resort for official history prose: require a complete target name or
    # alias in the same bounded text block.  A surname by itself cannot pass.
    for node in soup.select("article, main, section, li, p"):
        context = clean(node.get_text(" "))
        matched_name = next(
            (name for name in target.names if _normalized_contains_name(context, name)), ""
        )
        if not matched_name:
            continue
        title = _extract_title(context)
        manual = TargetProfile(
            requested_name=target.full_name,
            name=matched_name,
            title=title,
            matched=True,
            match_type=("Exact" if matched_name == target.full_name else "Alias"),
            matched_alias=(matched_name if matched_name != target.full_name else ""),
            senior_title=bool(_roles(title)),
            extraction_method="Bounded official prose",
            email_routes=(),
        )
        return _ParsedTarget(manual, context, "bounded text block")
    return None


def _source_for_target(
    target: IndustryTarget, sources: list[IndustrySource]
) -> IndustrySource | None:
    domains = set(target.allowed_domains) | (
        {target.official_domain} if target.official_domain else set()
    )
    for source in sources:
        if (
            target.matches_organization(source.company)
            or source.official_domain.casefold() in domains
        ):
            return source
    return None


def _target_domains(target: IndustryTarget) -> tuple[str, ...]:
    # The source configuration must never silently widen a target's authority.
    return target.allowed_domains or split_domains("", target.official_domain)


def _candidate_urls(target: IndustryTarget, source: IndustrySource | None) -> list[str]:
    urls: list[str] = []
    for url in (target.profile_url_hint, source.leadership_page if source else ""):
        if url and url not in urls:
            urls.append(url)
    return urls


def _identity_evidence(
    target: IndustryTarget,
    parsed: _ParsedTarget,
    page: Page,
    candidate_identifier: str,
) -> EvidenceRecord:
    return EvidenceRecord.create(
        target.campaign_id,
        target.target_id,
        "Identity",
        parsed.profile.name,
        candidate_id=candidate_identifier,
        claim_organization=target.canonical_organization or target.requested_organization,
        claim_polarity="Supports",
        temporal_status="Not Applicable",
        source_url=page.final_url,
        source_label="Official person page",
        source_publisher=target.canonical_organization or target.requested_organization,
        source_type="Official Company Page",
        source_authority="Official",
        retrieved_at=page.retrieved_at,
        last_confirmed_at=page.retrieved_at,
        http_status=str(page.status_code),
        content_sha256=page.content_sha256,
        source_locator=parsed.locator,
        evidence_summary=f"Exact full-name or configured-alias match for {target.full_name}.",
        extractor_version=EXTRACTOR_VERSION,
        review_status="Unreviewed",
    )


def _role_evidence(
    target: IndustryTarget,
    parsed: _ParsedTarget,
    page: Page,
    candidate_identifier: str,
    role_status: str,
    person_status: str,
) -> EvidenceRecord:
    return EvidenceRecord.create(
        target.campaign_id,
        target.target_id,
        "Role",
        parsed.profile.title or "Role not extracted",
        candidate_id=candidate_identifier,
        claim_organization=target.canonical_organization or target.requested_organization,
        claim_polarity="Supports"
        if role_status in {"Match", "Historical Match"}
        else "Contradicts",
        temporal_status=_temporal_status(person_status),
        source_url=page.final_url,
        source_label="Official person page",
        source_publisher=target.canonical_organization or target.requested_organization,
        source_type="Official Company Page",
        source_authority="Official",
        retrieved_at=page.retrieved_at,
        last_confirmed_at=page.retrieved_at,
        http_status=str(page.status_code),
        content_sha256=page.content_sha256,
        source_locator=parsed.locator,
        evidence_summary=(
            f"Observed title {parsed.profile.title or '[not extracted]'}; "
            f"requested role {target.requested_role}; result {role_status}."
        ),
        extractor_version=EXTRACTOR_VERSION,
        review_status="Unreviewed",
    )


def _official_email_evidence(
    target: IndustryTarget,
    route: EmailRoute,
    page: Page,
    candidate_identifier: str,
    claims: list[EmailClaim],
    *,
    direct: bool,
) -> EvidenceRecord:
    matching_claim = next(
        (claim for claim in claims if claim.email.casefold() == route.email.casefold()), None
    )
    return EvidenceRecord.create(
        target.campaign_id,
        target.target_id,
        "Email Address",
        route.email,
        claim_id=matching_claim.claim_id if matching_claim else "",
        candidate_id=candidate_identifier,
        claim_organization=target.canonical_organization or target.requested_organization,
        claim_polarity="Supports",
        temporal_status="Current",
        email_evidence_level="E4 Exact Current Official",
        contact_ownership="Direct Person" if direct else "Department Route",
        mailbox_status="Unknown",
        source_url=page.final_url,
        source_label="Official person page" if direct else "Official contact page",
        source_publisher=target.canonical_organization or target.requested_organization,
        source_type="Official Company Page",
        source_authority="Official",
        retrieved_at=page.retrieved_at,
        last_confirmed_at=page.retrieved_at,
        http_status=str(page.status_code),
        content_sha256=page.content_sha256,
        source_locator="person-bound email" if direct else "department contact route",
        evidence_summary=(
            "Exact address published inside the matched person's official profile."
            if direct
            else "Exact departmental route published on an official contact page."
        ),
        extractor_version=EXTRACTOR_VERSION,
        review_status="Unreviewed",
    )


def _minimum_email_rank(campaign: Campaign | None) -> int:
    level = campaign.minimum_direct_email_evidence if campaign else "E4 Exact Current Official"
    return EMAIL_EVIDENCE_RANK.get(level, EMAIL_EVIDENCE_RANK["E4 Exact Current Official"])


def _best_seeded_email_evidence(
    target: IndustryTarget,
    claims: list[EmailClaim],
    records: list[EvidenceRecord],
) -> tuple[EmailClaim, EvidenceRecord] | None:
    """Return accepted support for an exact claim without inferring ownership."""

    choices: list[tuple[EmailClaim, EvidenceRecord]] = []
    for claim in claims:
        evidence = best_email_evidence(
            records,
            claim.email,
            target_id_value=target.target_id,
            accepted_only=True,
        )
        if evidence is None:
            continue
        if evidence.claim_id and evidence.claim_id != claim.claim_id:
            continue
        choices.append((claim, evidence))
    return max(choices, key=lambda pair: (pair[1].email_rank, pair[1].published_at), default=None)


def _seeded_direct_email(
    target: IndustryTarget,
    claims: list[EmailClaim],
    records: list[EvidenceRecord],
    minimum_rank: int,
) -> tuple[EmailClaim, EvidenceRecord] | None:
    """Select an exact address only when its evidence also binds the person."""

    choices: list[tuple[EmailClaim, EvidenceRecord]] = []
    for claim in claims:
        evidence = best_email_evidence(
            records,
            claim.email,
            target_id_value=target.target_id,
            accepted_only=True,
        )
        if (
            evidence is None
            or evidence.email_rank < minimum_rank
            or evidence.contact_ownership != "Direct Person"
        ):
            continue
        if evidence.claim_id and evidence.claim_id != claim.claim_id:
            continue
        choices.append((claim, evidence))
    return max(choices, key=lambda pair: (pair[1].email_rank, pair[1].published_at), default=None)


def _blank_candidate() -> dict[str, str]:
    return {column: "" for column in CANDIDATE_COLUMNS}


def _candidate_row(
    target: IndustryTarget,
    campaign: Campaign | None,
    parsed: _ParsedTarget,
    page: Page,
    identity_evidence: EvidenceRecord,
    role_evidence: EvidenceRecord,
    person_status: str,
    route: EmailRoute | None,
    email_evidence: EvidenceRecord | None,
    preferred_route: tuple[str, str],
) -> dict[str, str]:
    organization = target.canonical_organization or target.requested_organization
    identifier = candidate_id("Industry", parsed.profile.name, organization)
    historical = person_status in {"Former", "Retired", "Historical"}
    review_status = "Needs Review" if historical or route is None else "Draft"
    row = _blank_candidate()
    row.update(
        {
            "Candidate ID": identifier,
            "Speaker Type": "Industry",
            "Review Status": review_status,
            "Full Name": parsed.profile.name,
            "Organization": organization,
            "Title": parsed.profile.title,
            "Preferred Salutation": target.full_name,
            "Email": route.email if route else "",
            "Contact Type": route.contact_type if route else "",
            "Email Source URL": route.source_url if route else "",
            "Profile URL": page.final_url,
            "Discovery Source URL": target.profile_url_hint or page.requested_url,
            "Notes": (
                "Human review required for historical/retired status."
                if historical
                else "No qualifying public contact route was found; identity and role remain recorded."
                if route is None
                else ""
            ),
            "Last Checked": (page.retrieved_at[:10] or today_iso()),
            "Campaign ID": target.campaign_id,
            "Target ID": target.target_id,
            "Role Temporal Status": _temporal_status(person_status),
            "Role As Of": campaign.research_as_of if campaign else page.retrieved_at[:10],
            "Identity Evidence ID": identity_evidence.evidence_id,
            "Role Evidence ID": role_evidence.evidence_id,
            "Email Evidence Level": email_evidence.email_evidence_level if email_evidence else "",
            "Email Evidence ID": email_evidence.evidence_id if email_evidence else "",
            "Mailbox Status": email_evidence.mailbox_status if email_evidence else "Unknown",
            "Preferred Route Type": preferred_route[0],
            "Preferred Route URL": preferred_route[1],
            "Revision": "1",
            "Schema Version": SCHEMA_VERSION,
        }
    )
    return row


def _failure_report(
    target: IndustryTarget,
    campaign: Campaign | None,
    status: str,
    note: str,
    *,
    last_checked: str,
) -> TargetReport:
    return TargetReport.create(
        target.campaign_id,
        target.target_id,
        role_as_of=campaign.research_as_of if campaign else last_checked[:10],
        target_status=status,
        last_checked_at=last_checked,
        notes=note,
    )


def _discover_exact_profile_urls(
    page: Page,
    source: IndustrySource,
    target: IndustryTarget,
) -> list[str]:
    links = extract_leader_links(page.html, source)
    return [
        link.url
        for link in links
        if host_allowed(link.url, _target_domains(target))
        and any(names_match(link.name_hint, expected) for expected in target.names)
    ]


def _generic_routes(
    source: IndustrySource | None,
    target: IndustryTarget,
    client: OfficialWebClient,
    warnings: list[str],
) -> tuple[list[EmailRoute], list[tuple[EmailRoute, Page]]]:
    if source is None:
        return [], []
    domains = _target_domains(target)
    routes: list[EmailRoute] = []
    bound: list[tuple[EmailRoute, Page]] = []
    for hint, url in source.contact_pages:
        if not url or not host_allowed(url, domains):
            continue
        try:
            page = client.fetch_page(url, domains)
            found = extract_email_routes(page.html, page.final_url, domains, page_hint=hint)
        except FetchError as exc:
            warnings.append(f"{target.target_id}: optional contact route unavailable: {exc}")
            continue
        for route in found:
            routes.append(route)
            bound.append((route, page))
    return routes, bound


def _collect_one(
    target: IndustryTarget,
    campaign: Campaign | None,
    claims: list[EmailClaim],
    seeded_evidence: list[EvidenceRecord],
    source: IndustrySource | None,
    client: OfficialWebClient,
) -> tuple[dict[str, str] | None, list[EvidenceRecord], TargetReport, list[str]]:
    warnings: list[str] = []
    domains = _target_domains(target)
    checked_at = today_iso()
    if not domains:
        return (
            None,
            [],
            _failure_report(
                target,
                campaign,
                "Blocked",
                "Target has no Allowed Domains.",
                last_checked=checked_at,
            ),
            warnings,
        )

    urls = _candidate_urls(target, source)
    if not urls:
        return (
            None,
            [],
            _failure_report(
                target,
                campaign,
                "Not Found",
                "No profile hint or matching official source.",
                last_checked=checked_at,
            ),
            warnings,
        )

    matched: tuple[_ParsedTarget, Page] | None = None
    identity_only_match: tuple[_ParsedTarget, Page] | None = None
    successful_fetch = False
    parse_failures: list[str] = []
    fetch_failures: list[str] = []
    pending_urls = list(urls)
    seen_urls: set[str] = set()
    while pending_urls and matched is None:
        url = pending_urls.pop(0)
        if url in seen_urls:
            continue
        seen_urls.add(url)
        try:
            page = client.fetch_page(url, domains)
            successful_fetch = True
        except FetchError as exc:
            fetch_failures.append(f"{url}: {exc}")
            continue
        checked_at = page.retrieved_at or checked_at
        try:
            parsed = _parse_target_page(page, target, domains)
            if parsed is not None:
                if clean(parsed.profile.title):
                    matched = (parsed, page)
                    break
                identity_only_match = identity_only_match or (parsed, page)
            if source is not None and url == source.leadership_page:
                pending_urls.extend(
                    exact_url
                    for exact_url in _discover_exact_profile_urls(page, source, target)
                    if exact_url not in seen_urls
                )
        except (TypeError, ValueError) as exc:
            parse_failures.append(f"{url}: {exc}")

    matched = matched or identity_only_match
    if matched is None:
        note_parts = [*parse_failures, *fetch_failures]
        if parse_failures:
            status = "Needs Review"
            prefix = "Profile parse failed."
        elif not successful_fetch:
            status = "Blocked"
            prefix = "All official fetch attempts were blocked or unavailable."
        else:
            status = "Not Found"
            prefix = "No exact full-name or configured-alias match was found."
        note = " ".join([prefix, *note_parts])
        warnings.extend(f"{target.target_id}: {failure}" for failure in note_parts)
        return (
            None,
            [],
            _failure_report(target, campaign, status, note, last_checked=checked_at),
            warnings,
        )

    warnings.extend(
        f"{target.target_id}: earlier attempt did not succeed: {failure}"
        for failure in (*parse_failures, *fetch_failures)
    )
    parsed, page = matched
    organization = target.canonical_organization or target.requested_organization
    identifier = candidate_id("Industry", parsed.profile.name, organization)
    person_status = _person_status(target, parsed.context, parsed.profile.title)
    role_status = role_match_status(
        target.requested_role, parsed.profile.title, person_status=person_status
    )
    identity = _identity_evidence(target, parsed, page, identifier)
    role = _role_evidence(target, parsed, page, identifier, role_status, person_status)
    discovered: list[EvidenceRecord] = [identity, role]

    ineligible = person_status == "Deceased"
    direct_routes = (
        [] if ineligible else [route for route in parsed.profile.email_routes if route.is_direct]
    )
    generic_routes: list[EmailRoute] = []
    generic_with_pages: list[tuple[EmailRoute, Page]] = []
    if (
        not ineligible
        and not direct_routes
        and (campaign is None or campaign.allow_department_routes)
    ):
        generic_routes, generic_with_pages = _generic_routes(source, target, client, warnings)
    selected_route = select_route(direct_routes, generic_routes)
    selected_email_evidence: EvidenceRecord | None = None
    observed_seeded = (
        None if ineligible else _best_seeded_email_evidence(target, claims, seeded_evidence)
    )
    if selected_route is not None:
        email_page = page
        if not selected_route.is_direct:
            email_page = next(
                (
                    candidate_page
                    for route, candidate_page in generic_with_pages
                    if route == selected_route
                ),
                page,
            )
        selected_email_evidence = _official_email_evidence(
            target,
            selected_route,
            email_page,
            identifier,
            claims,
            direct=selected_route.is_direct,
        )
        discovered.append(selected_email_evidence)

    if selected_route is None:
        seeded = _seeded_direct_email(
            target,
            claims,
            seeded_evidence,
            _minimum_email_rank(campaign),
        )
        if seeded is not None:
            claim, selected_email_evidence = seeded
            selected_route = EmailRoute(
                claim.email,
                "Direct",
                selected_email_evidence.source_url,
                "Person",
                selected_email_evidence.evidence_summary,
            )

    preferred_route = ("", "")
    if selected_route is not None:
        preferred_route = (selected_route.contact_type, selected_route.source_url)
    elif source is not None:
        preferred = next(
            (
                (hint, url)
                for hint, url in source.contact_pages
                if url and host_allowed(url, domains)
            ),
            ("", ""),
        )
        preferred_route = preferred

    historical = person_status in {"Former", "Retired", "Historical"}
    role_mismatch = role_status not in {"Match", "Historical Match"}
    status = (
        "Ineligible" if ineligible else "Needs Review" if historical or role_mismatch else "Matched"
    )

    candidate: dict[str, str] | None = None
    if not ineligible:
        candidate = _candidate_row(
            target,
            campaign,
            parsed,
            page,
            identity,
            role,
            person_status,
            selected_route,
            selected_email_evidence,
            preferred_route,
        )
        if role_mismatch:
            candidate["Review Status"] = "Needs Review"
            candidate["Notes"] = clean(
                f"Requested role did not match the verified current title. {candidate['Notes']}"
            )

    note_parts: list[str] = []
    if ineligible:
        note_parts.append("Deceased person; no candidate or outreach route was created.")
    elif historical:
        note_parts.append("Historical, former, or retired status requires human review.")
    if role_mismatch:
        note_parts.append("Requested role differs from the title found on the official page.")
    if selected_route is None:
        note_parts.append(
            "No qualifying public email route was found; claimed addresses remain isolated."
        )
    report_email = (
        selected_route.email
        if selected_route
        else observed_seeded[0].email
        if observed_seeded
        else ""
    )
    report_email_evidence = (
        selected_email_evidence
        if selected_email_evidence is not None
        else observed_seeded[1]
        if observed_seeded is not None
        else None
    )
    report = TargetReport.create(
        target.campaign_id,
        target.target_id,
        role_as_of=campaign.research_as_of if campaign else page.retrieved_at[:10],
        candidate_id=identifier if candidate is not None else "",
        target_status=status,
        identity_match_status=parsed.profile.match_type,
        role_match_status=role_status,
        person_status=person_status,
        verified_current_title=parsed.profile.title,
        verified_current_organization=organization,
        current_role_evidence_id=role.evidence_id,
        email=report_email,
        contact_type=selected_route.contact_type if selected_route else "",
        email_evidence_level=(
            report_email_evidence.email_evidence_level
            if report_email_evidence
            else "E0 Claimed Only"
        ),
        email_evidence_id=report_email_evidence.evidence_id if report_email_evidence else "",
        mailbox_status=report_email_evidence.mailbox_status if report_email_evidence else "Unknown",
        preferred_route_type=preferred_route[0],
        preferred_route_url=preferred_route[1],
        last_checked_at=page.retrieved_at,
        notes=" ".join(note_parts),
    )
    return candidate, discovered, report, warnings


def collect_targeted_industry(
    campaigns: list[Campaign],
    targets: list[IndustryTarget],
    claims: list[EmailClaim],
    seeded_evidence: list[EvidenceRecord],
    sources: list[IndustrySource],
    client: OfficialWebClient,
) -> tuple[list[dict[str, str]], list[EvidenceRecord], list[TargetReport], list[str]]:
    """Verify explicit targets and return exactly one terminal report per target."""

    campaign_by_id = {campaign.campaign_id: campaign for campaign in campaigns}
    claims_by_target: dict[str, list[EmailClaim]] = {}
    for claim in claims:
        claims_by_target.setdefault(claim.target_id, []).append(claim)

    candidates: list[dict[str, str]] = []
    discovered_evidence: list[EvidenceRecord] = []
    reports: list[TargetReport] = []
    warnings: list[str] = []
    for target in targets:
        try:
            candidate, evidence, report, target_warnings = _collect_one(
                target,
                campaign_by_id.get(target.campaign_id),
                claims_by_target.get(target.target_id, []),
                seeded_evidence,
                _source_for_target(target, sources),
                client,
            )
        except Exception as exc:  # Defensive per-target isolation is intentional.
            candidate = None
            evidence = []
            report = _failure_report(
                target,
                campaign_by_id.get(target.campaign_id),
                "Needs Review",
                f"Unexpected parse failure: {exc}",
                last_checked=today_iso(),
            )
            target_warnings = [f"{target.target_id}: unexpected parse failure: {exc}"]
        if candidate is not None:
            candidates.append(candidate)
        discovered_evidence.extend(evidence)
        reports.append(report)
        warnings.extend(target_warnings)

    if len(reports) != len(targets):  # pragma: no cover - invariant guard
        raise RuntimeError("Target collection did not produce exactly one report per target.")
    return candidates, merge_evidence(seeded_evidence, discovered_evidence), reports, warnings


verify_industry_targets = collect_targeted_industry

__all__ = [
    "EXTRACTOR_VERSION",
    "collect_targeted_industry",
    "role_match_status",
    "verify_industry_targets",
]
