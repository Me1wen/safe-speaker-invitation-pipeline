# Release Checklist

## Repository Hygiene

- [ ] Confirm all customer, recipient, event, and credential data is absent.
- [ ] Confirm only example configuration is tracked.
- [ ] Run a secret scan and inspect every match.
- [ ] Confirm generated CSV/XLSX files and local virtual environments are ignored.
- [ ] Confirm the copyright name in `LICENSE` is acceptable.

## Quality

- [ ] Run `ruff format --check .`.
- [ ] Run `ruff check .`.
- [ ] Run `python -m pytest --cov=speaker_pipeline --cov-report=term-missing`.
- [ ] Run `python -m compileall -q speaker_pipeline scripts`.
- [ ] Test installation from a clean Python environment.
- [ ] Run `python -m build` and inspect the source and wheel archives.
- [ ] Test the final archive after extraction.

## Documentation

- [ ] Verify README commands on macOS/Linux and Windows where applicable.
- [ ] Update `CHANGELOG.md` and `speaker_pipeline.__version__` together.
- [ ] Review safety, data, SMTP, and interrupted-delivery guidance.
- [ ] Confirm examples use fictional addresses and domains.

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
- [ ] Perform one-message dry-run and live-delivery validation in the deployment environment; do not use real SMTP credentials in GitHub Actions.
