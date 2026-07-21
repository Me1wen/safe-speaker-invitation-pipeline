## Summary

Describe the problem and the user-visible change.

## Safety and Data Impact

- [ ] No real recipient, customer, event, or credential data is included.
- [ ] Candidate approval, draft approval, and dry-run defaults remain enforced.
- [ ] Website-access, privacy, SMTP, and duplicate-delivery implications were considered.

## Verification

- [ ] Tests were added or updated.
- [ ] `ruff format --check .` passes.
- [ ] `ruff check .` passes.
- [ ] `python -m pytest --cov=speaker_pipeline --cov-report=term-missing` passes.
- [ ] Documentation and changelog were updated when needed.

## Additional Notes

List limitations, migration steps, or follow-up work.
