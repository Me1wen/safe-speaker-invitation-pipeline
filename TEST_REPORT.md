# Test Report — 2026-07-21

## Original packages

- Academic package: 1/1 test passed.
- Industry package: 12/12 tests passed.
- Speaker-lead/Google Sheets workflow: 15/15 tests passed.
- Total original tests: 28 passed.

The original tests did not cover several real-page false positives or the incompatible industry-to-workflow schema. Those problems motivated the integrated rewrite.

## Integrated package

The project was installed from `requirements.txt` into a new Python 3.12 virtual environment and tested there.

```text
23 passed
```

GitHub-release hardening added repository-metadata tests, Ruff formatting/static checks, and branch-aware coverage reporting. The current core package coverage is 71%, with a repository minimum of 70% enforced through `pyproject.toml` and CI.

Coverage includes:

- exclusion of staff, administration, memorial, navigation, and third-party links;
- academic name/title/email agreement checks;
- senior industry title and profile-name checks;
- failure isolation between source organizations;
- separation of a plain email from its contact-route type;
- preservation of manually Approved candidates during recollection;
- high-severity QA blocking before draft generation;
- separate direct and routed invitation templates;
- recipient changes forcing a new draft approval;
- preservation of Sent/Sending ledger rows;
- dry-run making no SMTP connection;
- mandatory live-send confirmation phrase;
- Sending → Sent status persistence with Message-ID;
- protection against selecting Sent messages again;
- legacy email-label migration;
- exact CSV/XLSX review-schema round trips.

## Live academic sample

The revised academic collector was run against the configured official MIT, UC Berkeley, and Princeton department pages with a maximum of two profile checks per source.

- Four structurally valid professor rows were retained.
- `Technical Staff`, `Administrative Staff`, and `In Memoriam` were no longer accepted.
- The previous malformed `Pieter Abbeel: Faculty Home Page` result was normalized to `Pieter Abbeel` with the correct salutation.
- Research extraction no longer used navigation/header/footer text.

The live result remains a draft for human fact-checking; the software does not approve candidates automatically.

## Industry and SMTP boundaries

- No live industry crawl was performed because no real target companies were supplied. Industry behavior was tested with deterministic official-site fixtures.
- No real SMTP credentials were used and no real email was sent.
- A full draft-generation test produced one personalized invitation.
- An unapproved draft selected zero delivery targets.
- An Approved draft appeared in dry-run, while an incorrect confirmation phrase blocked live delivery before SMTP configuration was read.
