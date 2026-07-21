from copy import deepcopy

import pytest

from speaker_pipeline.common import merge_candidates
from speaker_pipeline.drafts import generate_drafts
from speaker_pipeline.mailer import MailSettings, deliver_approved_drafts
from speaker_pipeline.schema import CANDIDATE_COLUMNS
from speaker_pipeline.validation import approved_candidates, validate_candidates


def candidate(**changes):
    row = {column: "" for column in CANDIDATE_COLUMNS}
    row.update(
        {
            "Candidate ID": "ACAD-123",
            "Speaker Type": "Academic",
            "Review Status": "Approved",
            "Full Name": "Ada Lovelace",
            "Organization": "Example University",
            "Title": "Professor",
            "Expertise": "Machine learning",
            "Topic Fit": "responsible artificial intelligence",
            "Preferred Salutation": "Dr. Lovelace",
            "Email": "ada@example.edu",
            "Contact Type": "Direct",
            "Email Source URL": "https://example.edu/ada",
            "Profile URL": "https://example.edu/ada",
            "Discovery Source URL": "https://example.edu/faculty",
            "Last Checked": "2026-07-21",
        }
    )
    row.update(changes)
    return row


def config():
    return {
        "event_name": "AI Forum",
        "event_host": "Example Host",
        "event_date": "October 1, 2026",
        "event_location": "San Francisco",
        "event_description": "a forum for researchers and industry leaders",
        "sender_name": "Alex Chen",
        "sender_title": "Program Director",
        "sender_organization": "Example Host",
        "sender_email": "alex@example.org",
        "subject_template": "Invitation for {full_name} to {event_name}",
        "direct_body_template": "Dear {salutation},\n\nPlease join {event_name} to discuss {topic_fit}.\n\n{sender_name}",
        "routed_body_template": "Dear {route_greeting},\n\nPlease forward our invitation to {full_name} at {organization}.\n\n{sender_name}",
    }


def settings():
    return MailSettings(
        host="smtp.example.org",
        port=587,
        username="user",
        password="secret",
        from_email="alex@example.org",
        from_name="Alex Chen",
        starttls=True,
    )


def test_approved_record_is_never_overwritten_by_recollection():
    old = candidate(**{"Topic Fit": "human-centered AI", "Notes": "Manually checked"})
    fresh = candidate(
        **{"Title": "Wrong refreshed title", "Email": "new@example.edu", "Topic Fit": ""}
    )
    merged = merge_candidates([old], [fresh])
    assert merged[0]["Title"] == "Professor"
    assert merged[0]["Email"] == "ada@example.edu"
    assert merged[0]["Topic Fit"] == "human-centered AI"


def test_high_severity_issue_blocks_draft_generation():
    invalid = candidate(**{"Topic Fit": ""})
    issues = validate_candidates([invalid])
    assert any(issue["Severity"] == "High" and issue["Field"] == "Topic Fit" for issue in issues)
    assert approved_candidates([invalid]) == []
    assert generate_drafts([invalid], config()) == []


def test_direct_and_routed_templates_are_different():
    direct = candidate()
    routed = candidate(
        **{
            "Candidate ID": "IND-456",
            "Speaker Type": "Industry",
            "Full Name": "Jane Rivera",
            "Organization": "Example Co",
            "Title": "Chief AI Officer",
            "Preferred Salutation": "Jane Rivera",
            "Email": "media@example.com",
            "Contact Type": "Media Relations",
            "Email Source URL": "https://example.com/media",
            "Profile URL": "https://example.com/leaders/jane",
        }
    )
    drafts = generate_drafts([direct, routed], config())
    assert len(drafts) == 2
    assert drafts[0]["Body Text"].startswith("Dear Dr. Lovelace")
    assert drafts[1]["Body Text"].startswith("Dear Media Relations Team")
    assert drafts[1]["To Email"] == "media@example.com"


def test_sent_ledger_is_preserved_when_template_changes():
    first = generate_drafts([candidate()], config())
    first[0]["Draft Status"] = "Sent"
    changed = config()
    changed["subject_template"] = "A changed invitation for {full_name}"
    result = generate_drafts([candidate()], changed, first)
    assert len(result) == 1
    assert result[0]["Draft Status"] == "Sent"
    assert result[0]["Draft ID"] == first[0]["Draft ID"]


def test_recipient_change_requires_new_draft_approval():
    first = generate_drafts([candidate()], config())
    first[0]["Draft Status"] = "Approved"
    changed_candidate = candidate(**{"Email": "ada-new@example.edu"})
    result = generate_drafts([changed_candidate], config(), first)
    assert result[0]["Draft ID"] != first[0]["Draft ID"]
    assert result[0]["Draft Status"] == "Draft"


class FakeServer:
    def __init__(self):
        self.messages = []
        self.quit_called = False

    def send_message(self, message):
        self.messages.append(message)

    def quit(self):
        self.quit_called = True


def test_mailer_is_dry_run_by_default_and_never_connects():
    rows = generate_drafts([candidate()], config())
    rows[0]["Draft Status"] = "Approved"
    called = False

    def connector(_settings):
        nonlocal called
        called = True
        return FakeServer()

    result = deliver_approved_drafts(rows, settings(), connector=connector)
    assert result == {"selected": 1, "sent": 0, "failed": 0}
    assert not called
    assert rows[0]["Draft Status"] == "Approved"


def test_live_send_requires_phrase_and_records_sending_then_sent():
    rows = generate_drafts([candidate()], config())
    rows[0]["Draft Status"] = "Approved"
    with pytest.raises(ValueError, match="SEND_APPROVED_EMAILS"):
        deliver_approved_drafts(rows, settings(), send=True, confirmation="wrong")

    snapshots = []
    server = FakeServer()
    result = deliver_approved_drafts(
        rows,
        settings(),
        send=True,
        confirmation="SEND_APPROVED_EMAILS",
        delay_seconds=0,
        persist=lambda updated: snapshots.append(deepcopy(updated)),
        connector=lambda _settings: server,
    )
    assert result == {"selected": 1, "sent": 1, "failed": 0}
    assert snapshots[0][0]["Draft Status"] == "Sending"
    assert snapshots[-1][0]["Draft Status"] == "Sent"
    assert rows[0]["Sent At"]
    assert rows[0]["Message ID"]
    assert len(server.messages) == 1
    assert server.quit_called


def test_sent_message_is_not_selected_again():
    rows = generate_drafts([candidate()], config())
    rows[0]["Draft Status"] = "Sent"
    result = deliver_approved_drafts(rows, settings())
    assert result["selected"] == 0
