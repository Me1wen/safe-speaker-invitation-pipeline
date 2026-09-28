# Changelog

All notable changes to this project are documented in this file. The project follows Semantic Versioning.

## Repository publication update - 2026-09-27

- Publish the existing v1.2.0 implementation over the original v1.0.0 GitHub snapshot, preserving
  repository history. No new runtime feature or version bump is introduced by this publication.
- Clarify installation, workspace upgrades, and the boundary between separate awards/academy
  research workbooks and supported pipeline imports.
- Exclude the internal campaign fixture from Git as well as package manifests; retain only
  reviewed public configuration and simulated test data.

## [1.2.0] - 2026-08-22

### Added

- Fail-closed campaign delivery policy requiring `Active` status, a current outreach window, a
  positive `Max Messages` cap, current candidate/evidence validity and remaining attempt capacity.
- Global email/domain/target/candidate suppression ledger and `manage_suppressions.py` CLI.
- Offline `doctor.py` checks for active workspace, relational, policy and SMTP readiness without a
  network connection.
- Provider-evidence `reconcile_delivery.py` workflow for one uncertain `Sending` attempt.
- Delivery-resolution, reconciliation, candidate-approval, campaign-policy and sender-identity
  fields in the canonical draft ledger.

### Changed

- New v2 approval seals bind reviewer/time; draft seals also bind the current candidate approval,
  full campaign policy, recipient/message and Sender Email/Name/Reply-To. Legacy v1 seals remain
  readable but cannot authorize live delivery.
- Targeted candidate approval now requires matching `Accepted`, supporting evidence with the
  required current temporal state. Live policy also checks Campaign Research As Of, Candidate Role
  As Of, evidence confirmation/retrieval freshness, and evidence effective dates. Historical targets
  require explicit policy permission.
- Live send requires explicit draft, campaign, candidate, evidence and suppression files. All five
  are locked in deterministic order and policy is run again in the final preflight before SMTP.
- Duplicate and attempted-recipient protection is global across campaigns by default.
- `create_workspace.py` creates blank active industry-outreach/data tables and a non-authorizing Draft
  campaign with `Max Messages = 0`; only a placeholder invitation template is copied, while
  example recipient/research fixtures remain separate.
- Dry run remains the default and hides recipient details unless `--show-targets` is explicit.
- The documented objective is low-volume, relevant, human-reviewed outreach. Scheduling,
  unattended retries, inbox monitoring and mass outreach remain out of scope.

### Fixed

- SMTP timeouts, disconnects and other ambiguous outcomes remain durably `Sending` and stop the
  batch instead of becoming retryable `Failed`; only explicit permanent refusal is marked `Failed`.
- Runtime SMTP From/Reply-To identity must match the sender identity covered by draft approval.
- Negative message limits and delays, unsafe in-memory live sends and live calls without a held-lock
  and persistence/preflight contract are rejected.

### Delivery Semantics

- `Sent` means SMTP acceptance only; it does not assert inbox placement, reading or reply.
- Automated tests use simulated SMTP behavior. This release does not claim that real SMTP or inbox
  delivery was tested.

## [1.1.0] - 2026-08-16

### Added

- Explicit, one-person-per-row industry target and claimed-email inputs.
- Evidence and per-target collection ledgers that keep identity, role, exact-address evidence,
  and mailbox state separate.
- Exact/alias/suffix-aware name matching, JSON-LD Person parsing, and CEO abbreviation support.
- Page retrieval metadata with final-URL allowlist checks, public-address checks, and content hashes.
- Campaign-bound candidate and draft approval hashes, recipient deduplication, and ledger locks.
- A development-private 16-person CEO/founder verification fixture based on the requested test set
  (excluded from package/release artifacts).

### Changed

- Legacy 1.0 candidate and draft tables are readable but are upgraded with blank 1.1 control fields.
- Review workbooks preserve body paragraphs, reject formulas on import, and write literal text cells.
- Plaintext SMTP configurations are rejected; dry-run remains the default.

### Security

- Cross-domain redirects and private/link-local/reserved targets are rejected before content is used.
- A claimed address, naming pattern, MX record, or historical record can no longer be represented as
  a currently verified personal mailbox.

## [1.0.0] - 2026-07-21

### Added

- Unified academic and industry candidate schema.
- Official-domain allowlists, robots checks, throttling, and conservative profile extraction.
- Candidate review validation and exact CSV/XLSX round trips.
- Safe migration from the three original workflow packages.
- Separate direct-contact and departmental-route invitation templates.
- Candidate approval and draft approval gates.
- Dry-run default with explicit live-send confirmation.
- SMTP delivery ledger with `Sending`, `Sent`, `Failed`, timestamp, and Message-ID fields.
- Duplicate-delivery protections and recipient-change reapproval.
- Automated tests using simulated websites and SMTP.
- English documentation, operational safety guidance, and test report.
- GitHub community, security, CI, dependency-update, and release files.
