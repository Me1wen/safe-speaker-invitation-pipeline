from __future__ import annotations

from speaker_pipeline.evidence import EvidenceRecord, content_sha256
from speaker_pipeline.targeted import collect_targeted_industry
from speaker_pipeline.targets import Campaign, EmailClaim, IndustryTarget
from speaker_pipeline.web import OfficialWebClient, Page

STAMP = "2026-08-16T12:00:00+00:00"


def _page(url: str, name: str, title: str, extra: str = "") -> Page:
    html = f"""
      <main><article class="person">
        <h1>{name}</h1><div class="title">{title}</div>{extra}
      </article></main>
    """
    return Page(url=url, final_url=url, html=html, retrieved_at=STAMP)


def _target(
    campaign_id: str,
    number: int,
    name: str,
    requested_role: str,
    *,
    relationship: str = "Current Executive",
    aliases: tuple[str, ...] = (),
    notes: str = "",
) -> IndustryTarget:
    return IndustryTarget.create(
        campaign_id,
        name,
        f"Company {number}",
        requested_role,
        name_aliases=aliases,
        canonical_organization=f"Company {number}",
        official_domain="example.com",
        allowed_domains=("example.com",),
        relationship_type=relationship,
        profile_url_hint=f"https://example.com/people/{number}",
        notes=notes,
    )


def test_sixteen_named_targets_each_get_one_terminal_report():
    campaign = Campaign.create(
        "Boss list",
        research_as_of="2026-08-16",
        minimum_direct_email_evidence="E3 Exact Current Authoritative",
    )
    specifications = [
        ("Jensen Huang", "CEO", "Founder, President and CEO", "Current Executive", ""),
        ("Sundar Pichai", "CEO", "CEO", "Current Executive", ""),
        ("Tim Cook", "CEO", "CEO", "Current Executive", ""),
        ("Satya Nadella", "CEO", "Chairman and CEO", "Current Executive", ""),
        ("Andy Jassy", "CEO", "President and CEO", "Current Executive", ""),
        ("C.C. Wei", "CEO", "Chairman and C.E.O.", "Current Executive", ""),
        ("Morris Chang", "Founder", "Founder", "Founder", "retired in 2018"),
        ("Mark Zuckerberg", "CEO;Founder", "Founder, Chairman and CEO", "Current Executive", ""),
        ("Hock Tan", "CEO", "President and CEO", "Current Executive", ""),
        ("Henry Samueli", "Founder", "Co-Founder and Director", "Founder", ""),
        (
            "Henry Nicholas III",
            "Founder",
            "Former CEO and Co-Founder",
            "Historical",
            "former CEO",
        ),
        ("Safra Catz", "CEO", "Executive Vice Chair", "Current Executive", ""),
        ("Larry Ellison", "Founder", "Co-Founder, Executive Chairman and CTO", "Founder", ""),
        ("Bob Miner", "Founder", "Co-Founder", "Historical", "died in 1994"),
        ("Ed Oates", "Founder", "Co-Founder", "Historical", "retired in 1996"),
        ("Elon Musk", "CEO", "CEO", "Current Executive", ""),
    ]
    targets = [
        _target(
            campaign.campaign_id,
            index,
            name,
            requested,
            relationship=relationship,
            notes=notes,
        )
        for index, (name, requested, _title, relationship, notes) in enumerate(
            specifications, start=1
        )
    ]
    pages = {}
    for index, (name, _requested, title, _relationship, notes) in enumerate(
        specifications, start=1
    ):
        extra = f"<p>{notes}</p>" if notes else ""
        if name == "Tim Cook":
            extra += '<a href="mailto:tim@example.com">Email Tim</a>'
        if name == "Jensen Huang":
            extra += '<footer><a href="mailto:careers@example.com">Careers</a></footer>'
        pages[f"https://example.com/people/{index}"] = _page(
            f"https://example.com/people/{index}", name, title, extra
        )

    candidates, evidence, reports, warnings = collect_targeted_industry(
        [campaign],
        targets,
        [],
        [],
        [],
        OfficialWebClient(fetcher=pages.__getitem__),
    )

    assert warnings == []
    assert len(reports) == 16
    assert len({report.target_id for report in reports}) == 16
    assert all(report.target_status != "Pending" for report in reports)
    assert len([record for record in evidence if record.claim_type == "Identity"]) == 16
    assert len([record for record in evidence if record.claim_type == "Role"]) == 16

    reports_by_name = {
        target.full_name: next(report for report in reports if report.target_id == target.target_id)
        for target in targets
    }
    candidates_by_name = {row["Full Name"]: row for row in candidates}
    assert reports_by_name["Jensen Huang"].role_match_status == "Match"
    assert reports_by_name["Safra Catz"].role_match_status == "Different"
    assert reports_by_name["Safra Catz"].target_status == "Needs Review"
    assert reports_by_name["Bob Miner"].person_status == "Deceased"
    assert reports_by_name["Bob Miner"].target_status == "Ineligible"
    assert "Bob Miner" not in candidates_by_name
    assert reports_by_name["Satya Nadella"].email == ""
    assert candidates_by_name["Jensen Huang"]["Email"] == ""
    assert candidates_by_name["Tim Cook"]["Email"] == "tim@example.com"
    assert candidates_by_name["Morris Chang"]["Review Status"] == "Needs Review"
    assert candidates_by_name["Ed Oates"]["Review Status"] == "Needs Review"


def test_claims_are_isolated_until_exact_accepted_evidence_exists():
    campaign = Campaign.create(
        "Exact email",
        research_as_of="2026-08-16",
        minimum_direct_email_evidence="E3 Exact Current Authoritative",
    )
    target = _target(campaign.campaign_id, 1, "Ada Smith", "CEO")
    other_target = _target(campaign.campaign_id, 2, "Grace Smith", "CEO")
    claim = EmailClaim.create(campaign.campaign_id, target.target_id, "ada@example.com")
    page = _page(target.profile_url_hint, "Ada Smith", "CEO")
    client = OfficialWebClient(fetcher=lambda _url: page)

    candidates, _evidence, reports, _warnings = collect_targeted_industry(
        [campaign], [target], [claim], [], [], client
    )
    assert candidates[0]["Email"] == ""
    assert reports[0].email == ""

    wrong_target_evidence = EvidenceRecord.create(
        campaign.campaign_id,
        other_target.target_id,
        "Email Address",
        claim.email,
        source_url="https://records.example/wrong-person",
        content_sha256=content_sha256("wrong target"),
        claim_polarity="Supports",
        temporal_status="Current",
        email_evidence_level="E4 Exact Current Official",
        review_status="Accepted",
    )
    wrong_address_evidence = EvidenceRecord.create(
        campaign.campaign_id,
        target.target_id,
        "Email Address",
        "other@example.com",
        source_url="https://records.example/wrong-address",
        content_sha256=content_sha256("wrong address"),
        claim_polarity="Supports",
        temporal_status="Current",
        email_evidence_level="E4 Exact Current Official",
        review_status="Accepted",
    )
    candidates, _evidence, reports, _warnings = collect_targeted_industry(
        [campaign],
        [target],
        [claim],
        [wrong_target_evidence, wrong_address_evidence],
        [],
        client,
    )
    assert candidates[0]["Email"] == ""
    assert reports[0].email == ""

    exact = EvidenceRecord.create(
        campaign.campaign_id,
        target.target_id,
        "Email Address",
        claim.email,
        claim_id=claim.claim_id,
        source_url="https://records.example/exact",
        content_sha256=content_sha256("exact address"),
        claim_polarity="Supports",
        temporal_status="Current",
        email_evidence_level="E3 Exact Current Authoritative",
        contact_ownership="Unknown",
        mailbox_status="Unknown",
        review_status="Accepted",
    )
    candidates, _evidence, reports, _warnings = collect_targeted_industry(
        [campaign], [target], [claim], [exact], [], client
    )
    # Exact-address evidence and contact ownership are independent.  Unknown
    # ownership is visible in the report but cannot be promoted to Direct.
    assert candidates[0]["Email"] == ""
    assert candidates[0]["Email Evidence ID"] == ""
    assert reports[0].email == claim.email
    assert reports[0].contact_type == ""
    assert reports[0].email_evidence_id == exact.evidence_id
    assert reports[0].mailbox_status == "Unknown"

    person_bound = EvidenceRecord.create(
        campaign.campaign_id,
        target.target_id,
        "Email Address",
        claim.email,
        claim_id=claim.claim_id,
        source_url="https://example.com/people/ada",
        content_sha256=content_sha256("person-bound exact address"),
        claim_polarity="Supports",
        temporal_status="Current",
        email_evidence_level="E4 Exact Current Official",
        contact_ownership="Direct Person",
        mailbox_status="Unknown",
        review_status="Accepted",
    )
    candidates, _evidence, reports, _warnings = collect_targeted_industry(
        [campaign], [target], [claim], [exact, person_bound], [], client
    )
    assert candidates[0]["Email"] == claim.email
    assert candidates[0]["Email Evidence ID"] == person_bound.evidence_id
    assert reports[0].contact_type == "Direct"


def test_same_surname_is_not_identity_and_fetch_disabled_is_terminal():
    campaign = Campaign.create("No guessing", research_as_of="2026-08-16")
    target = _target(campaign.campaign_id, 1, "Ada Smith", "CEO")
    wrong = _page(target.profile_url_hint, "Grace Smith", "CEO")
    candidates, evidence, reports, _warnings = collect_targeted_industry(
        [campaign],
        [target],
        [],
        [],
        [],
        OfficialWebClient(fetcher=lambda _url: wrong),
    )
    assert candidates == []
    assert evidence == []
    assert reports[0].target_status == "Not Found"
    assert reports[0].identity_match_status == "Unverified"

    candidates, evidence, reports, warnings = collect_targeted_industry(
        [campaign], [target], [], [], [], OfficialWebClient()
    )
    assert candidates == []
    assert evidence == []
    assert reports[0].target_status == "Blocked"
    assert len(reports) == 1
    assert warnings
