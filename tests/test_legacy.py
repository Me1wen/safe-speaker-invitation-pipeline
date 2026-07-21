from speaker_pipeline.legacy import migrate_legacy_rows


def legacy_row(email="Media Relations media@example.com", status="Approved"):
    return {
        "Highest Level": "Chief AI Officer",
        "Award Year": "",
        "Full Name": "Jane Rivera",
        "University/Institute": "Example Co",
        "Research Field": "Artificial intelligence",
        "Placeholder": "",
        "Title and Last Name": "Jane Rivera,",
        "Email": email,
        "Phone": "",
        "Link": "https://example.com/leaders/jane",
        "Notes": "Media Relations contact.",
        "Review Status": status,
    }


def test_legacy_industry_email_label_is_split_and_reapproval_required():
    row = migrate_legacy_rows([legacy_row()], "industry")[0]
    assert row["Email"] == "media@example.com"
    assert row["Contact Type"] == "Media Relations"
    assert row["Email Source URL"] == ""
    assert row["Review Status"] == "Needs Review"
    assert "reapproval required" in row["Notes"]


def test_legacy_academic_direct_email_uses_profile_as_source():
    row = migrate_legacy_rows([legacy_row("jane@example.edu", "")], "academic")[0]
    assert row["Contact Type"] == "Direct"
    assert row["Email Source URL"] == "https://example.com/leaders/jane"
