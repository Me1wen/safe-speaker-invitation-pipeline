import json
from types import MappingProxyType, SimpleNamespace

import pytest

from scripts import create_workspace, doctor, send_approved_emails, verify_industry_targets
from speaker_pipeline.common import read_csv, write_csv
from speaker_pipeline.mailer import DeliveryPreflightContext, MailSettings
from speaker_pipeline.schema import (
    CAMPAIGN_COLUMNS,
    CANDIDATE_COLUMNS,
    DRAFT_COLUMNS,
    EMAIL_CLAIM_COLUMNS,
    EVIDENCE_COLUMNS,
    INDUSTRY_SOURCE_COLUMNS,
    SUPPRESSION_COLUMNS,
    TARGET_COLUMNS,
)


def _workspace_root(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "invitation.example.json").write_text(
        json.dumps({"campaign_id": "YOUR-EVENT-2026"}), encoding="utf-8"
    )
    return tmp_path


def _approved_draft(email="private-recipient@example.com"):
    row = {column: "" for column in DRAFT_COLUMNS}
    row.update(
        {
            "Draft ID": "DRAFT-ONE",
            "Candidate ID": "CANDIDATE-ONE",
            "Draft Status": "Approved",
            "To Email": email,
            "Subject": "Private invitation subject",
            "Campaign ID": "CMP-ONE",
        }
    )
    return row


def test_create_workspace_initializes_blank_active_ledgers(monkeypatch, tmp_path):
    root = _workspace_root(tmp_path)
    monkeypatch.setattr(create_workspace, "PROJECT_ROOT", root)

    create_workspace.main()

    campaigns = read_csv(root / "config" / "campaigns.csv", CAMPAIGN_COLUMNS)
    assert len(campaigns) == 1
    assert campaigns[0]["Campaign Status"] == "Draft"
    assert campaigns[0]["Allow Historical Targets"] == "false"
    assert campaigns[0]["Allow Department Routes"] == "false"
    assert campaigns[0]["Max Messages"] == "0"
    assert "not authorized" in campaigns[0]["Notes"]
    assert read_csv(root / "config" / "industry_targets.csv", TARGET_COLUMNS) == []
    assert read_csv(root / "config" / "email_claims.csv", EMAIL_CLAIM_COLUMNS) == []
    assert read_csv(root / "config" / "email_evidence.csv", EVIDENCE_COLUMNS) == []
    assert read_csv(root / "config" / "industry_sources.csv", INDUSTRY_SOURCE_COLUMNS) == []
    assert read_csv(root / "data" / "suppressions.csv", SUPPRESSION_COLUMNS) == []


def test_verify_defaults_use_active_files_and_reject_empty_configuration(monkeypatch, tmp_path):
    root = _workspace_root(tmp_path)
    monkeypatch.setattr(create_workspace, "PROJECT_ROOT", root)
    monkeypatch.setattr(verify_industry_targets, "PROJECT_ROOT", root)
    create_workspace.main()

    args = verify_industry_targets._parser().parse_args([])
    assert args.campaigns == root / "config" / "campaigns.csv"
    assert args.targets == root / "config" / "industry_targets.csv"
    assert args.claims == root / "config" / "email_claims.csv"
    assert args.evidence == root / "config" / "email_evidence.csv"
    assert args.sources == root / "config" / "industry_sources.csv"

    with pytest.raises(SystemExit, match="no configured rows"):
        verify_industry_targets.main([])


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--max-messages", "-1"], "--max-messages"),
        (["--delay", "-0.1"], "--delay"),
        (["--lock-timeout", "-1"], "--lock-timeout"),
    ],
)
def test_send_rejects_negative_operational_values(arguments, message):
    with pytest.raises(SystemExit, match=message):
        send_approved_emails.main(arguments)


def test_verify_rejects_negative_delay():
    with pytest.raises(SystemExit, match="--delay"):
        verify_industry_targets.main(["--delay", "-0.1"])


def test_dry_run_hides_target_pii_unless_explicitly_requested(tmp_path, capsys):
    drafts = tmp_path / "email_drafts.csv"
    write_csv(drafts, DRAFT_COLUMNS, [_approved_draft()])

    send_approved_emails.main(["--input", str(drafts)])
    hidden = capsys.readouterr().out
    assert "Approved unsent drafts selected: 1" in hidden
    assert "private-recipient@example.com" not in hidden
    assert "Private invitation subject" not in hidden

    send_approved_emails.main(["--input", str(drafts), "--show-targets"])
    shown = capsys.readouterr().out
    assert "private-recipient@example.com" in shown
    assert "Private invitation subject" in shown


def test_live_send_requires_explicit_policy_inputs(tmp_path):
    drafts = tmp_path / "email_drafts.csv"
    write_csv(drafts, DRAFT_COLUMNS, [_approved_draft()])

    with pytest.raises(SystemExit, match="--campaigns"):
        send_approved_emails.main(
            [
                "--input",
                str(drafts),
                "--send",
                "--confirm",
                "SEND_APPROVED_EMAILS",
                "--campaign-id",
                "CMP-ONE",
            ]
        )


def test_live_policy_ledgers_lock_in_deterministic_order(monkeypatch, tmp_path):
    events = []

    class FakeLock:
        def __init__(self, path, *, timeout):
            self.path = path
            self.timeout = timeout

        def __enter__(self):
            events.append(("enter", self.path, self.timeout))
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            events.append(("exit", self.path, self.timeout))

    monkeypatch.setattr(send_approved_emails, "LedgerLock", FakeLock)
    paths = [tmp_path / "z.csv", tmp_path / "a.csv", tmp_path / "z.csv"]

    with send_approved_emails._live_input_locks(paths, timeout=3.0):
        events.append(("body", None, None))

    entered = [path for action, path, _ in events if action == "enter"]
    exited = [path for action, path, _ in events if action == "exit"]
    assert entered == sorted({path.resolve() for path in paths}, key=str)
    assert exited == list(reversed(entered))


def test_live_send_rechecks_policy_with_mailer_snapshot_and_reports_uncertain(
    monkeypatch, tmp_path, capsys
):
    drafts = tmp_path / "email_drafts.csv"
    campaigns = tmp_path / "campaigns.csv"
    suppressions = tmp_path / "suppressions.csv"
    candidates = tmp_path / "candidates.csv"
    evidence = tmp_path / "evidence.csv"
    write_csv(drafts, DRAFT_COLUMNS, [_approved_draft()])
    write_csv(candidates, CANDIDATE_COLUMNS, [])
    for path in (campaigns, suppressions, evidence):
        path.write_text("placeholder\n", encoding="utf-8")

    campaign = SimpleNamespace(campaign_id="CMP-ONE")
    settings = MailSettings(
        host="smtp.example.org",
        port=587,
        username="user",
        password="secret",
        from_email="sender@example.org",
    )
    policy_calls = []

    monkeypatch.setattr(send_approved_emails, "load_campaigns", lambda _path: [campaign])
    monkeypatch.setattr(send_approved_emails, "load_evidence", lambda _path: [])
    monkeypatch.setattr(send_approved_emails, "load_suppressions", lambda _path: [])
    monkeypatch.setattr(
        send_approved_emails.MailSettings,
        "from_environment",
        classmethod(lambda _cls: settings),
    )

    def fake_policy(rows, *args, **kwargs):
        policy_calls.append(rows)
        return SimpleNamespace(attempted=0, remaining_after_batch=4)

    def fake_delivery(rows, active_settings, **kwargs):
        assert kwargs["lock_held"] is True
        assert callable(kwargs["persist"])
        context = DeliveryPreflightContext(
            rows=tuple(MappingProxyType(dict(row)) for row in rows),
            selected=tuple(MappingProxyType(dict(row)) for row in rows),
            settings=active_settings,
            campaign_id=kwargs["campaign_id"],
            max_messages=kwargs["max_messages"],
        )
        kwargs["preflight"](context)
        return {"selected": 1, "sent": 0, "failed": 0, "uncertain": 1}

    monkeypatch.setattr(send_approved_emails, "validate_delivery_policy", fake_policy)
    monkeypatch.setattr(send_approved_emails, "deliver_approved_drafts", fake_delivery)

    send_approved_emails.main(
        [
            "--input",
            str(drafts),
            "--send",
            "--confirm",
            "SEND_APPROVED_EMAILS",
            "--campaign-id",
            "CMP-ONE",
            "--campaigns",
            str(campaigns),
            "--suppressions",
            str(suppressions),
            "--candidates",
            str(candidates),
            "--evidence",
            str(evidence),
        ]
    )

    assert len(policy_calls) == 2
    assert policy_calls[1] == [dict(row) for row in policy_calls[0]]
    assert "Uncertain: 1" in capsys.readouterr().out


def test_doctor_is_offline_and_fails_closed_on_draft_workspace(monkeypatch, tmp_path, capsys):
    root = _workspace_root(tmp_path)
    monkeypatch.setattr(create_workspace, "PROJECT_ROOT", root)
    monkeypatch.setattr(doctor, "PROJECT_ROOT", root)
    create_workspace.main()
    capsys.readouterr()
    for name in ("SMTP_HOST", "SMTP_PORT", "SMTP_FROM_EMAIL"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(SystemExit) as raised:
        doctor.main([])

    assert raised.value.code == 1
    output = capsys.readouterr().out
    assert "no network connection was attempted" in output
    assert "SMTP configuration is not ready" in output
    assert "Readiness: FAILED" in output
