"""Canonical schemas shared by collection, review, drafting, and sending."""

from __future__ import annotations

CANDIDATE_COLUMNS = [
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

DRAFT_COLUMNS = [
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

CANDIDATE_STATUSES = {"Draft", "Needs Review", "Approved", "Rejected"}
DRAFT_STATUSES = {"Draft", "Approved", "Rejected", "Sending", "Sent", "Failed"}

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
