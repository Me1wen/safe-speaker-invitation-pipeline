"""Canonical schemas shared by collection, review, drafting, and sending.

The v1.0 column constants are intentionally retained verbatim.  Version 1.1
tables append columns to those schemas so an upgrader can recognize an exact
v1.0 header and hydrate only the new fields without guessing about malformed
or reordered input.
"""

from __future__ import annotations

SCHEMA_VERSION = "1.1"

CANDIDATE_COLUMNS_V1_0 = [
    "Candidate ID",
    "Speaker Type",
    "Review Status",
    "Full Name",
    "Organization",
    "Title",
    "Expertise",
    "Topic Fit",
    "Preferred Salutation",
    "Email",
    "Contact Type",
    "Email Source URL",
    "Phone",
    "Profile URL",
    "Discovery Source URL",
    "Notes",
    "Last Checked",
]

# Both spellings are exported because early v1.1 branches used each form.
V1_0_CANDIDATE_COLUMNS = CANDIDATE_COLUMNS_V1_0

CANDIDATE_COLUMNS_V1_1_ADDITIONS = [
    "Campaign ID",
    "Target ID",
    "Role Temporal Status",
    "Role As Of",
    "Identity Evidence ID",
    "Role Evidence ID",
    "Email Evidence Level",
    "Email Evidence ID",
    "Mailbox Status",
    "Preferred Route Type",
    "Preferred Route URL",
    "Revision",
    "Approval Hash",
    "Approved At",
    "Approved By",
    "Schema Version",
]

CANDIDATE_COLUMNS = [*CANDIDATE_COLUMNS_V1_0, *CANDIDATE_COLUMNS_V1_1_ADDITIONS]

DRAFT_COLUMNS_V1_0 = [
    "Draft ID",
    "Candidate ID",
    "Draft Status",
    "To Email",
    "To Name",
    "Contact Type",
    "Subject",
    "Body Text",
    "Profile URL",
    "Created At",
    "Last Attempt At",
    "Sent At",
    "Message ID",
    "Error",
]

V1_0_DRAFT_COLUMNS = DRAFT_COLUMNS_V1_0

DRAFT_COLUMNS_V1_1_LEGACY_ADDITIONS = [
    "Campaign ID",
    "Revision",
    "Approval Hash",
    "Approved At",
    "Approved By",
    "Schema Version",
]

DRAFT_COLUMNS_V1_1_LEGACY = [
    *DRAFT_COLUMNS_V1_0,
    *DRAFT_COLUMNS_V1_1_LEGACY_ADDITIONS,
]

DRAFT_COLUMNS_V1_1_ADDITIONS = [
    "Delivery Resolution",
    "Reconciled At",
    "Reconciled By",
    "Provider Reference",
    # These immutable-at-approval references make the final delivery decision
    # depend on the reviewed candidate, campaign policy, and sender identity.
    "Candidate Approval Hash",
    "Campaign Policy Hash",
    "Sender Email",
    "Sender Name",
    "Reply-To",
    "Campaign ID",
    "Revision",
    "Approval Hash",
    "Approved At",
    "Approved By",
    "Schema Version",
]

DRAFT_COLUMNS = [*DRAFT_COLUMNS_V1_0, *DRAFT_COLUMNS_V1_1_ADDITIONS]

QA_COLUMNS = [
    "Run Date",
    "Severity",
    "Row Number",
    "Candidate ID",
    "Full Name",
    "Field",
    "Issue",
]

ACADEMIC_SOURCE_COLUMNS = [
    "Organization",
    "Department Directory URL",
    "Allowed Domains",
    "Profile Link Selector",
]

INDUSTRY_SOURCE_COLUMNS = [
    "Company",
    "Official Domain",
    "Leadership Page",
    "Allowed Domains",
    "Profile Link Selector",
    "Contact Page",
    "Media Contact Page",
    "Investor Relations Page",
]

CAMPAIGN_COLUMNS = [
    "Schema Version",
    "Campaign ID",
    "Campaign Name",
    "Campaign Status",
    "Purpose",
    "Owner",
    "Sender Organization",
    "Research As Of",
    "Outreach Not Before",
    "Outreach Not After",
    "Minimum Direct Email Evidence",
    "Allow Historical Targets",
    "Allow Department Routes",
    "Max Messages",
    "Created At",
    "Updated At",
    "Notes",
]

TARGET_COLUMNS = [
    "Schema Version",
    "Target ID",
    "Campaign ID",
    "Priority",
    "Full Name",
    "Name Aliases",
    "Requested Organization",
    "Canonical Organization",
    "Organization Aliases",
    "Official Domain",
    "Allowed Domains",
    "Requested Role",
    "Relationship Type",
    "Profile URL Hint",
    "Created At",
    "Notes",
]

EMAIL_CLAIM_COLUMNS = [
    "Schema Version",
    "Claim ID",
    "Campaign ID",
    "Target ID",
    "Email",
    "Claim Origin",
    "Claimed At",
    "Claim Status",
    "Notes",
]

CLAIM_COLUMNS = EMAIL_CLAIM_COLUMNS

EVIDENCE_COLUMNS = [
    "Schema Version",
    "Evidence ID",
    "Campaign ID",
    "Target ID",
    "Claim ID",
    "Candidate ID",
    "Claim Type",
    "Claim Value",
    "Claim Organization",
    "Claim Polarity",
    "Temporal Status",
    "Email Evidence Level",
    "Contact Ownership",
    "Mailbox Status",
    "Source URL",
    "Source Label",
    "Source Publisher",
    "Source Type",
    "Source Authority",
    "Published At",
    "Effective From",
    "Effective To",
    "Retrieved At",
    "Last Confirmed At",
    "HTTP Status",
    "Content SHA256",
    "Source Locator",
    "Evidence Summary",
    "Extractor Version",
    "Review Status",
    "Reviewed By",
    "Reviewed At",
    "Notes",
]

TARGET_REPORT_COLUMNS = [
    "Schema Version",
    "Report ID",
    "Campaign ID",
    "Target ID",
    "Candidate ID",
    "Target Status",
    "Identity Match Status",
    "Role Match Status",
    "Person Status",
    "Verified Current Title",
    "Verified Current Organization",
    "Role As Of",
    "Current Role Evidence ID",
    "Email",
    "Contact Type",
    "Email Evidence Level",
    "Email Evidence ID",
    "Mailbox Status",
    "Preferred Route Type",
    "Preferred Route URL",
    "Last Checked At",
    "Notes",
]

REPORT_COLUMNS = TARGET_REPORT_COLUMNS

SUPPRESSION_COLUMNS = [
    "Schema Version",
    "Suppression ID",
    "Scope",
    "Value",
    "Reason",
    "Status",
    "Created At",
    "Created By",
    "Expires At",
    "Revoked At",
    "Revoked By",
    "Notes",
]

CANDIDATE_STATUSES = {"Draft", "Needs Review", "Approved", "Rejected"}
DRAFT_STATUSES = {"Draft", "Approved", "Rejected", "Sending", "Sent", "Failed"}

SUPPRESSION_SCOPES = {"Email", "Domain", "Target ID", "Candidate ID"}
SUPPRESSION_STATUSES = {"Active", "Revoked"}

CAMPAIGN_STATUSES = {"Draft", "Research", "Review", "Approved", "Active", "Closed", "Cancelled"}
TARGET_STATUSES = {
    "Pending",
    "Matched",
    "Needs Review",
    "Not Found",
    "Blocked",
    "Ineligible",
    "Rejected",
}
CLAIM_STATUSES = {"Unreviewed", "Researching", "Corroborated", "Contradicted", "Rejected"}
EVIDENCE_REVIEW_STATUSES = {"Unreviewed", "Accepted", "Rejected", "Superseded"}
CLAIM_POLARITIES = {"Supports", "Contradicts", "Context"}
TEMPORAL_STATUSES = {
    "Current",
    "Former",
    "Upcoming",
    "Historical Fact",
    "Undated",
    "Not Applicable",
}
EMAIL_EVIDENCE_LEVELS = {
    "E0 Claimed Only",
    "E1 Pattern Only",
    "E2 Exact Historical",
    "E3 Exact Current Authoritative",
    "E4 Exact Current Official",
}
EMAIL_EVIDENCE_RANK = {
    "E0 Claimed Only": 0,
    "E1 Pattern Only": 1,
    "E2 Exact Historical": 2,
    "E3 Exact Current Authoritative": 3,
    "E4 Exact Current Official": 4,
}
MAILBOX_STATUSES = {"Unknown", "Delivered", "Hard Bounce", "Replied", "Suppressed"}
CONTACT_OWNERSHIP_TYPES = {
    "Direct Person",
    "Department Route",
    "Unknown",
    "Not Applicable",
}

DIRECT_CONTACT = "Direct"
GENERIC_CONTACT_TYPES = {
    "Corporate Communications",
    "Media Relations",
    "Investor Relations",
    "Public Affairs",
    "Executive Office",
    "University Relations",
    "Speaker Inquiry",
    "General Contact",
}
