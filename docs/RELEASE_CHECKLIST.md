# Release Checklist

## Repository Hygiene

- [ ] Confirm all customer, recipient, event, and credential data is absent.
- [ ] Confirm only example configuration is tracked.
- [ ] Run a secret scan and inspect every match.
- [ ] Confirm generated CSV/XLSX files and local virtual environments are ignored.
- [ ] Run `python scripts/create_workspace.py` in a clean extraction and confirm active targets,
      claims, evidence, industry sources, candidates, drafts, and suppressions are blank; the only campaign
      is `Draft` with `Max Messages = 0`.
- [ ] Confirm the named boss/CEO development fixture is absent from package/release artifacts and
      cannot become an active delivery input implicitly.
- [ ] Confirm the copyright name in `LICENSE` is acceptable.

## Quality

- [ ] Run `ruff format --check .`.
- [ ] Run `ruff check .`.
- [ ] Run `python -m pytest --cov=speaker_pipeline --cov-report=term-missing`.
- [ ] Run `python -m compileall -q speaker_pipeline scripts`.
- [ ] Test installation from a clean Python environment.
- [ ] Run `python -m build` and inspect the source and wheel archives.
- [ ] Test the final archive after extraction.
- [ ] Exercise `doctor.py`, `manage_suppressions.py`, and `reconcile_delivery.py` with fictional
      ledgers and simulated/provider-free evidence.
- [ ] Confirm dry run opens no SMTP connection and hides recipient details without `--show-targets`.
- [ ] Confirm live API/CLI refuses a missing ledger, missing lock/preflight, negative limit/delay,
      legacy approval, sender mismatch, suppression, duplicate recipient, inactive/out-of-window
      campaign, and zero/exceeded campaign cap.
- [ ] Confirm ambiguous simulated SMTP exceptions remain `Sending` and an explicit simulated 5xx
      refusal becomes `Failed`.

## Documentation

- [ ] Verify README commands on macOS/Linux and Windows where applicable.
- [ ] Update `CHANGELOG.md` and `speaker_pipeline.__version__` together.
- [ ] Review Active campaign/date/positive-cap, Research-As-Of evidence freshness,
      accepted-current-evidence, global-suppression, five-ledger lock, v2 approval, SMTP acceptance,
      and reconciliation guidance.
- [ ] Confirm every live-send example supplies draft, campaign, candidate, evidence, and suppression
      paths plus campaign ID and confirmation phrase.
- [ ] Confirm `SMTP_FROM_EMAIL`, `SMTP_FROM_NAME`, and `SMTP_REPLY_TO` exactly match the invitation
      identity sealed into drafts; omitted invitation `reply_to` requires blank SMTP Reply-To.
- [ ] Confirm documentation does not describe `Sent` as inbox delivery and does not claim a
      scheduler, automatic retry, webhook, inbox monitor, or mass-outreach capability.
- [ ] Confirm operational examples use fictional addresses and domains; confirm development-private
      research fixtures containing real claimed addresses are excluded from release artifacts.

## GitHub Settings

- [ ] Enable private vulnerability reporting.
- [ ] Enable Dependabot alerts and security updates.
- [ ] Enable secret scanning and push protection when available.
- [ ] Require the CI checks before merging into the default branch.
- [ ] Use least-privilege Actions permissions.
- [ ] Add a repository description and topics.

## Release

- [ ] Create a signed or annotated version tag.
- [ ] Generate release notes from `CHANGELOG.md`.
- [ ] Attach the tested source archive and SHA-256 checksum.
- [ ] Perform a one-message dry run in the deployment environment.
- [ ] If live SMTP validation is authorized, use a test-owned recipient, `--max-messages 1`, and the
      exact five-ledger command outside GitHub Actions. Record the provider evidence privately.
- [ ] Do not state that real SMTP or inbox delivery was tested unless that separate validation was
      actually performed and documented; automated tests use simulated SMTP behavior only.
- [ ] Re-run `python scripts/doctor.py --campaign-id ...` immediately before any authorized pilot.
