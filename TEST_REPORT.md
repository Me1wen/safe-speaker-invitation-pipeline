# Test Report

## GitHub Publication Re-verification — 2026-09-27

The v1.2.0 publication candidate was independently retested in a fresh Python 3.13.2 environment
on macOS, using the runtime versions in `constraints.txt`. Development tools included pytest
9.1.1, Ruff 0.16.9 and coverage 7.16.2.

| Check | Result |
| --- | --- |
| Working-tree test suite | 176 passed |
| Branch-aware package coverage | 81.67%; configured floor 80% |
| Ruff formatting and static checks | Passed |
| Python compilation and dependency consistency | Passed |
| Source distribution and wheel build/integrity | Passed |
| Private-fixture and operational-data archive exclusions | Passed |
| Independently extracted source test suite | 176 passed; 81.67% coverage |
| Clean wheel installation and module imports | Passed; version 1.2.0 |
| Empty-workspace initialization | Blank recipient/evidence ledgers; Draft campaign, cap 0 |
| Offline doctor and blank-target verifier | Refused unconfigured workspaces as expected |
| Default send dry run | Zero drafts; no SMTP connection |

The CLI smoke checks blocked socket network activity. Tests used simulated pages and SMTP, not
live recipients or credentials. Build and dependency downloads were the only network installation
steps. Release-file inspection found no private research workbook, real recipient address,
operational ledger or recognizable credential. This is not a production SMTP/inbox-delivery test
or a formal security certification. GitHub's required multi-version checks run separately on the
pull request and main branch; their live results are available in the repository's Actions tab.

The detailed August 22 release report below is retained as historical verification evidence.

## Original Release Verification — 2026-08-22

## Scope

Version 1.2.0 was hardened for a controlled, low-volume outreach pilot. The supported objective is
human-reviewed discovery, evidence, approval, suppression and delivery tracking. It is not an
unattended bulk-mailer and it does not treat guessed addresses or an SMTP hand-off as proof of
recipient delivery.

All verification used deterministic fixtures, fake SMTP objects or offline CLI runs. No real email
was sent and no live company-page crawl was performed.

## Release gates

The final source tree was tested with Python 3.13.2 on macOS:

```text
176 passed
81.67% branch-aware speaker_pipeline coverage
Configured coverage floor: 80%
Ruff static check: passed
Ruff format check: passed
compileall: passed
sdist build: passed
wheel build: passed
```

The configured coverage gate measures the reusable `speaker_pipeline` package. A separate
diagnostic run that also put every thin `scripts/` entry point in the coverage denominator executed
the same 176 tests successfully and measured 76.87%; that broader number is not substituted for or
presented as the package gate. CLI behavior is exercised directly by dedicated tests and by the
clean-package smoke tests below.

## Safety behavior verified

- Only one exact, `Active`, in-window campaign can authorize a live batch.
- Campaign limits count attempted rows, including `Sending`, `Sent`, `Failed` and rows with an
  attempt timestamp; a zero limit authorizes no live delivery.
- Current-role, identity and exact-address evidence must be accepted, supportive, temporally valid,
  linked to the same target/candidate and fresh relative to the campaign research date.
- Historical roles remain review-only unless the campaign explicitly allows them.
- Candidate approval cannot be rebound to another campaign. Live delivery requires a v2 draft seal
  binding reviewer, approval time, candidate approval, campaign policy and sender identity.
- Readable legacy v1 approvals cannot authorize live delivery.
- Global suppressions block email, domain, target ID or candidate ID and are rechecked inside the
  final locked preflight.
- Duplicate recipient checks are global by default, not merely campaign-local.
- The canonical campaign, candidate, evidence, suppression and draft ledgers are locked and reread
  before SMTP is opened.
- TLS is mandatory except for explicit localhost tests. A persistence failure before SMTP aborts
  delivery.
- Ambiguous SMTP outcomes remain `Sending`; they are never silently changed to `Failed` and retried.
  Reconciliation requires a human decision, actor, provider reference and exact confirmation text.
- Permanent 5xx refusal is recorded as `Failed`. `Sent` means provider acceptance only, not inbox
  placement or readership.
- Recipient addresses stay hidden in normal CLI output unless `--show-targets` is explicitly used.
- Negative limits/delays/timeouts are rejected, dry-run opens no SMTP connection, and the offline
  doctor opens no network connection.

## Clean-package verification

The sdist was extracted into a fresh temporary directory and tested independently of the working
tree:

```text
176 passed
81.67% branch-aware speaker_pipeline coverage
```

Additional smoke checks:

- sdist gzip integrity and wheel ZIP integrity passed;
- the wheel installed with `--no-deps` into a new virtual environment and imported as version
  `1.2.0`;
- `create_workspace.py` created blank active configuration plus all four operational ledgers;
- `doctor.py` failed closed when targets, sources, SMTP settings and an active campaign were absent;
- `verify_industry_targets.py` failed closed on blank active targets instead of falling back to a
  packaged example;
- `send_approved_emails.py` selected zero drafts in dry-run, opened no SMTP connection and sent no
  email; and
- archive inspection found zero private named-recipient fixtures, claimed-address fixtures or the
  private named-recipient verification report.

## Explicit limits

- No real SMTP account, provider log, bounce feed or inbox was available, so real delivery is not
  claimed.
- No live crawl was used in release verification. Official-source retrieval remains opt-in and
  should be rerun immediately before a real campaign.
- Public evidence can support an address assertion; it cannot prove current mailbox existence,
  personal readership or consent.
- Approval hashes detect stale or accidental changes. They are not cryptographic signatures against
  an operator who can edit both code and canonical ledgers.
- A process interruption after an SMTP hand-off cannot be made transactionally idempotent with SMTP
  alone. The row intentionally remains `Sending` until provider-log reconciliation.
- Private target lists and operational suppression data are excluded from distributable archives.
  They must be managed in the deployment workspace and backed up separately.
