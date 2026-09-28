# Safe Speaker Invitation Pipeline

**Version:** 1.2.0

**Status:** Beta; suitable only for controlled research and a low-volume, human-reviewed pilot

**License:** MIT

A Python 3.10–3.13 workflow for researching potential academic and industry speakers, recording
official-source evidence, reviewing candidates and invitation drafts, and tracking explicitly
authorized SMTP attempts. This repository contains reusable code and fictional configuration,
not a recipient database or an approved contact list.

Version 1.2.0 supersedes the original v1.0.0 GitHub snapshot. Its main additions are campaign-bound
approvals, evidence freshness checks, global do-not-contact rules, an offline readiness check, and
manual reconciliation of uncertain delivery attempts. See the [changelog](CHANGELOG.md).

The objective is verified, relevant and suppressible speaker outreach through an appropriate
official route. It is not an email-finding service, a mass-mailer, or an unattended campaign
system. The workflow is:

1. Collect potential speakers from configured official websites.
2. Keep the requested person/role separate from the role verified as of a stated date.
3. Record identity, role, and exact-address evidence independently; never treat an MX record or naming pattern as mailbox verification.
4. Generate personalized invitation email drafts from evidence-bound, approved candidates.
5. Review and approve each email draft separately with a v2 seal covering the candidate approval,
   campaign policy, sender identity, reviewer and approval time.
6. Revalidate the five authoritative ledgers under locks immediately before an explicitly confirmed
   SMTP attempt.
7. Record attempts for human reconciliation; `Sent` means SMTP accepted the message, not that it
   reached an inbox or was read.

There is intentionally no scheduler, background worker, automatic retry loop, inbox tracking, or
mass-outreach mode.

## Documentation

- [Architecture and trust boundaries](docs/ARCHITECTURE.md)
- [Data, website access, and outreach guidance](docs/DATA_AND_COMPLIANCE.md)
- [Security policy](SECURITY.md)
- [Contribution guide](CONTRIBUTING.md)
- [GitHub publication guide](docs/GITHUB_SETUP.md)
- [Release checklist](docs/RELEASE_CHECKLIST.md)
- [Changelog](CHANGELOG.md)
- [Verification report](TEST_REPORT.md)

## Important Safety Rules

- Collectors may access only public official pages on the configured `Allowed Domains`, and they check `robots.txt` before live requests.
- The software never guesses email addresses and does not use third-party contact databases.
- A claimed email, address pattern, historical message, MX result, and current official publication are different evidence levels. `Mailbox Status` remains independent.
- Historical founders, retired people, deceased people, and current executives are represented separately. A deceased target never becomes an outreach draft.
- Running collection again does not overwrite a manually approved candidate.
- An `Approved` status from a legacy package is not automatically trusted. Migrated records become `Needs Review` and must be approved again.
- Evidence used by a targeted candidate must be human `Accepted`, must `Support` the exact claim,
  and must have the required current temporal status. Direct email requires E3 or E4 exact-current
  evidence; a pattern or old document is insufficient.
- A candidate must have `Review Status = Approved` with a valid v2 approval before an email draft
  can be generated for live delivery.
- A draft must separately have `Draft Status = Approved` before it can be selected for sending.
- v1.2 draft approval binds the exact candidate approval, campaign policy, recipient, message,
  sender email/name/reply-to, reviewer and time. Any change requires review and approval again.
- A legacy v1 approval can be inspected but cannot authorize live delivery.
- Only an `Active` campaign inside its outreach date window and with a positive `Max Messages` may
  send. `Draft`, `Research`, `Review`, `Approved`, `Closed`, `Cancelled`, and `Max Messages = 0`
  all fail closed.
- Global suppressions are checked by email, domain, target ID and candidate ID. They must be
  recorded in `data/suppressions.csv`, not only in free-text notes.
- `send_approved_emails.py` does not open an SMTP connection by default.
- Live delivery requires `--send`, the exact confirmation phrase, an explicit campaign ID, and
  explicit paths for the draft, campaign, candidate, evidence and suppression ledgers.
- SMTP passwords are read only from environment variables. They are never stored in configuration files, CSV files, or logs.
- Live SMTP requires SSL or STARTTLS. Plaintext is rejected except for an explicit localhost-only test mode.
- Immediately before an attempt, the draft is durably saved as `Sending`. A timeout, disconnect or
  other ambiguous result remains `Sending`; only an explicit permanent SMTP refusal becomes
  `Failed`. Uncertain attempts are never automatically retried.
- Always comply with applicable anti-spam, privacy, institutional, and email-provider rules. Use the workflow only for relevant, individually reviewed outreach.

## Installation

Clone the repository, then create an isolated environment:

```bash
git clone https://github.com/Me1wen/safe-speaker-invitation-pipeline.git
cd safe-speaker-invitation-pipeline
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -c constraints.txt
python scripts/create_workspace.py
```

On Windows PowerShell, activate the virtual environment with:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
```

Use the Windows commands instead of the `python3 -m venv` and `source` lines, then continue with
the same `python -m pip` and workspace-initialization commands.

Initialization creates the following files without overwriting existing review work:

- `data/candidates.csv`
- `data/email_drafts.csv`
- `data/evidence.csv`
- `data/suppressions.csv`
- `config/industry_sources.csv`
- `config/invitation.json`
- `config/campaigns.csv`
- `config/industry_targets.csv`
- `config/email_claims.csv`
- `config/email_evidence.csv`

The active outreach workspace is intentionally blank: industry sources, targets, claims, evidence,
candidates, drafts and suppressions start empty. The only campaign row is a non-authorizing `Draft` template
with `Max Messages = 0`. A placeholder invitation template is copied for editing; no example
recipient/research rows or boss-test rows are copied into active files.

After replacing every placeholder and preparing the active ledgers, run the offline readiness
check. It validates files, relations, current policy and SMTP settings but makes no network call:

```bash
python scripts/doctor.py --campaign-id YOUR-EVENT-2026
```

`Readiness: FAILED` is expected until all required evidence, approvals, sender settings and an
authorized campaign are in place. Do not work around a doctor failure by editing hashes or statuses.

### Upgrading an Existing Workspace

Back up the entire private workspace before replacing code. Keep active configuration and the
candidate, evidence, draft and suppression ledgers together; do not replace them with repository
examples. Workspace initialization does not overwrite existing files, but it is not an approval
migration or a guarantee that historical records satisfy the current policy.

Legacy tables remain readable where supported. An old `Approved` cell or v1 approval seal does
not authorize delivery in v1.2.0. Review the evidence and current campaign policy again, import
candidate approvals, regenerate affected drafts, and approve the drafts separately. Run the
offline doctor and a dry run before considering any independently authorized live pilot.

## Step 1: Configure and Collect Academic Candidates

Edit `config/academic_sources.csv`. Each row must identify an official department directory and its approved official-domain allowlist.

Start with a small test run:

```bash
python scripts/collect_academic.py \
  --allow-live-fetch \
  --limit-per-source 3
```

Without `--allow-live-fetch`, the command does not access live websites.

The collector requires a plausible person-profile link, a matching person name, an academic title, and a public non-generic email address before creating a candidate row. Every collected row is still a draft and requires human verification.

## Step 2: Configure and Verify Industry Targets

The explicit target and evidence layer uses:

- `config/campaigns.csv` defines the research date and outreach policy.
- `config/industry_targets.csv` stores one requested person per row.
- `config/email_claims.csv` stores each exact claimed address independently.
- `config/email_evidence.csv` stores reviewed evidence; it never stores mailbox guesses.
- `config/industry_sources.csv` remains the company-page and allowed-domain policy.

The named CEO/founder/boss fixture is development-private, is excluded from the package/release
manifest, and is never copied into an active workspace. Do not distribute it or treat it as a
recipient authorization list.

Whenever possible, set `Profile Link Selector` to a CSS selector that targets person-profile links on the official leadership page. A specific selector substantially reduces false positives from ordinary site navigation.

Run a no-network verification first:

```bash
python scripts/verify_industry_targets.py
```

When the configuration and allowed domains have been reviewed, enable public-page retrieval explicitly:

```bash
python scripts/verify_industry_targets.py --allow-live-fetch
```

The command emits one terminal report row per target, even when a page is blocked, JavaScript-only, ambiguous, or has no person-bound email. It also writes source timestamps, final URLs, and page hashes to the evidence ledger.

The older `collect_industry.py` company-wide discovery command remains available for compatibility, but the target-driven command is preferred when testing a named list.

Name matching requires the complete normalized given/family name or an explicit alias; sharing a surname is not enough. CEO, C.E.O., Co-CEO, Founder, Chair, and related senior-role forms are recognized. The requested role is preserved even when current evidence shows a different role.

Direct and departmental contact routes are stored separately:

- `Email` always contains one plain email address.
- `Contact Type` records `Direct`, `Media Relations`, `Public Affairs`, or another route type.
- `Email Source URL` records the official page where that email address was published.

If no exact, person-bound official contact route is found, the target remains in the report but cannot silently become a direct-email candidate. Footer, navigation, and departmental addresses are not treated as personal mailboxes.

## Step 3: Review and Approve Candidates

You may edit `data/candidates.csv` directly or export it to Excel:

```bash
python scripts/export_review_workbook.py --kind candidates
```

This creates `outputs/candidate_review.xlsx`.

After editing the workbook, import it back into the canonical CSV:

```bash
python scripts/import_review_workbook.py \
  --kind candidates \
  --input outputs/candidate_review.xlsx \
  --approver "reviewer@example.org"
```

For every candidate, manually verify:

- full name;
- organization;
- title;
- expertise;
- profile URL;
- email address and official email source;
- whether a departmental route is appropriate for the intended outreach; and
- the custom `Topic Fit` explaining why this person is relevant to the event.

Every referenced identity, role and email evidence row must belong to the same campaign, target and
candidate; contain the exact claim; use `Claim Polarity = Supports`; and have
`Review Status = Accepted`. Current people require current role and email evidence. Historical
targets remain blocked unless the campaign explicitly permits them; deceased people are ineligible.
For live policy, Campaign `Research As Of` and Candidate `Role As Of` are required. The identity,
role and email evidence must have `Last Confirmed At` or `Retrieved At` on or after Research As Of,
and that date must fall inside any `Effective From`/`Effective To` interval.

Only a fully verified row should be changed to the value below and imported with `--approver`:

```text
Review Status = Approved
```

Run validation:

```bash
python scripts/validate_candidates.py
```

The QA report is written to `outputs/candidate_qa.csv`. An Approved candidate with a high-severity
issue is blocked from draft generation and is checked again immediately before delivery.

## Importing Results from the Original Packages

Import a legacy academic result:

```bash
python scripts/import_legacy_package_output.py \
  --type academic \
  --input "/path/to/AF Speaker Dataset DRAFT.xlsx"
```

Import a legacy industry result:

```bash
python scripts/import_legacy_package_output.py \
  --type industry \
  --input "/path/to/AF Speaker Dataset WITH INDUSTRY DRAFT.xlsx"
```

Important: a legacy industry workbook may contain both academic and industry rows. Do not label an entire mixed workbook as industry data. Prefer the industry package's `industry_review.csv`, or first create a workbook containing industry rows only.

The migration tool separates a legacy value such as `Media Relations media@example.com` into a plain email address and a separate contact type.

All migrated records become `Needs Review`. Before approval, add `Topic Fit`, verify all facts, and provide the actual `Email Source URL` for any departmental contact route.

### Awards and Academy Research Workbooks

The separately prepared Nobel, awards/honors and living-academy-member workbooks are research
deliverables, not canonical pipeline review workbooks. In particular, the 18-column awards/honors
workbook prepared on September 7, 2026 is **not directly supported** by
`import_legacy_package_output.py`. That importer expects the original academic/industry package
layout; it is not a generic spreadsheet importer and does not preserve award-year metadata.

No awards collector, academy-directory collector or adapter for that research workbook is included
in this release. Keep research files outside the public repository. If adapting selected records
later, preserve their award/election metadata and evidence in the research dataset, map only
supported fields into the canonical ledgers, and obtain fresh, person-specific review and
approval. A missing email, an unverified life status, or an award/membership entry alone is not
evidence of an eligible, current contact route. Never use a profile URL as email evidence unless
that page actually publishes the exact address.

## Step 4: Configure and Generate Email Drafts

Edit `config/invitation.json` before generating drafts. Give every event a stable `campaign_id`, then replace every example value with real event information, including:

- event name, host, date, location, and description;
- sender name, title, organization, and email;
- subject template;
- body template for direct contact; and
- body template for routed contact through media relations, public affairs, or another department.

The invitation `campaign_id` must identify exactly one row in `config/campaigns.csv`, and
`sender_organization` must exactly match that campaign's `Sender Organization`. Draft generation
binds the candidate's current approval hash, the full campaign-policy hash, `sender_email`,
`sender_name`, and Reply-To into the draft. If `reply_to` is omitted from the invitation JSON,
the approved Reply-To stays blank and replies use the From address.

Available template placeholders include:

```text
{full_name} {salutation} {organization} {title} {expertise}
{topic_fit} {profile_url} {contact_type} {route_greeting}
{event_name} {event_host} {event_date} {event_location}
{event_description} {sender_name} {sender_title}
{sender_organization} {sender_email}
```

Generate drafts:

```bash
python scripts/generate_email_drafts.py
```

This command never sends email. It creates:

- `data/email_drafts.csv`
- `outputs/email_draft_review.xlsx`

Direct contacts and departmental routes use different body templates. A routed contact is eligible
only if `Allow Department Routes` is enabled. If the candidate, campaign policy, sender identity,
recipient, route, subject or body changes, approval becomes stale and the draft must be reviewed
again.

## Step 5: Review and Approve Email Drafts

Review the recipient, salutation, event details, subject, body, and requested action. Only a draft that is ready for delivery should be changed to:

```text
Draft Status = Approved
```

If review was completed in Excel, import the workbook back into the canonical CSV:

```bash
python scripts/import_review_workbook.py \
  --kind drafts \
  --input outputs/email_draft_review.xlsx \
  --approver "reviewer@example.org"
```

Do not attempt live delivery directly from an Excel workbook. Live delivery requires the canonical CSV so status changes can be saved immediately.

## Step 6: Perform a Dry Run

```bash
python scripts/send_approved_emails.py \
  --campaign-id YOUR-EVENT-2026
```

The dry run reports the selection count but hides addresses and subjects by default. It does not
read SMTP credentials, open a network connection, or send email. In a private terminal only, add
`--show-targets` to display those personal details.

Limit the dry run to a small batch if desired:

```bash
python scripts/send_approved_emails.py \
  --campaign-id YOUR-EVENT-2026 \
  --max-messages 2
```

## Step 7: Configure SMTP and Send

First set the selected campaign to `Active`, give it a valid outreach window and a positive
`Max Messages`, then regenerate and re-approve drafts so their policy hash matches. `Max Messages`
counts attempts, including `Sending`, `Sent`, `Failed`, and rows with `Last Attempt At`; it is not a
promise of successful inbox delivery.

Set SMTP values in the current shell. Never save the password in the project directory. The three
sender values must exactly match the identity reviewed in `config/invitation.json` and sealed into
each approved draft:

STARTTLS example:

```bash
export SMTP_HOST="smtp.example.org"
export SMTP_PORT="587"
export SMTP_USERNAME="your-account@example.org"
export SMTP_PASSWORD="your-app-password-or-smtp-token"
export SMTP_FROM_EMAIL="you@example.org"       # invitation sender_email
export SMTP_FROM_NAME="Your Name"              # invitation sender_name
export SMTP_REPLY_TO=""                        # blank because invitation reply_to is omitted
export SMTP_STARTTLS="true"
export SMTP_USE_SSL="false"
```

An SSL configuration commonly uses port 465 with `SMTP_USE_SSL=true` and `SMTP_STARTTLS=false`.

Run the offline doctor after exporting the SMTP variables:

```bash
python scripts/doctor.py \
  --campaign-id YOUR-EVENT-2026 \
  --max-messages 1
```

For a deployment validation, use a test-owned recipient and attempt exactly one message. Live send
requires all five authoritative ledgers explicitly; the command locks them in deterministic order,
re-reads them, and performs the final campaign/candidate/evidence/suppression preflight before SMTP:

```bash
python scripts/send_approved_emails.py \
  --input data/email_drafts.csv \
  --campaigns config/campaigns.csv \
  --candidates data/candidates.csv \
  --evidence data/evidence.csv \
  --suppressions data/suppressions.csv \
  --campaign-id YOUR-EVENT-2026 \
  --max-messages 1 \
  --send \
  --confirm SEND_APPROVED_EMAILS
```

Only after independently confirming the test should an operator consider another small reviewed
batch:

```bash
python scripts/send_approved_emails.py \
  --input data/email_drafts.csv \
  --campaigns config/campaigns.csv \
  --candidates data/candidates.csv \
  --evidence data/evidence.csv \
  --suppressions data/suppressions.csv \
  --campaign-id YOUR-EVENT-2026 \
  --max-messages 2 \
  --send \
  --confirm SEND_APPROVED_EMAILS
```

`Sent` means the SMTP server accepted the message. It does not mean inbox delivery, reading, or a
reply. The project has no provider webhook, bounce processor or inbox monitor. An explicit permanent
SMTP refusal becomes `Failed`; investigate it and any suppression obligation before a human
authorizes another attempt.

Timeouts, disconnects and other ambiguous outcomes stay `Sending`. Never change such a row or retry
it based on guesswork. Obtain provider-side evidence using its Message-ID and attempt timestamp,
then reconcile exactly one row:

```bash
python scripts/reconcile_delivery.py \
  --draft-id DRAFT-ID-HERE \
  --resolution provider-accepted \
  --provider-reference "provider-log-or-audit-id" \
  --reviewer "reviewer@example.org" \
  --confirm RECONCILE_UNCERTAIN_DELIVERY
```

If the provider proves non-acceptance, use `--resolution provider-rejected` instead. Reconciliation
never sends email. Provider-accepted becomes `Sent`; provider-rejected becomes `Failed` and still
requires an explicit human reapproval before retry.

## Global Suppressions

Record an opt-out, hard bounce, legal restriction, domain block or internal do-not-contact decision
immediately. This ledger is enforced across campaigns:

```bash
python scripts/manage_suppressions.py add \
  --scope Email \
  --value "person@example.org" \
  --reason "Recipient requested no further contact" \
  --created-by "reviewer@example.org"
```

Scopes are `Email`, `Domain`, `Target ID`, and `Candidate ID`. Listing hides protected values unless
the operator deliberately uses `--show-values`:

```bash
python scripts/manage_suppressions.py list
```

Revocation requires a specific human decision and confirmation phrase:

```bash
python scripts/manage_suppressions.py revoke \
  --id SUP-ID-HERE \
  --revoked-by "reviewer@example.org" \
  --confirm REVOKE_SUPPRESSION
```

Do not remove suppression rows or rely on candidate notes as the enforcement mechanism.

## Operational Recommendations

- If live validation is authorized, use a test-owned recipient and `--max-messages 1` before any
  external-recipient pilot.
- Keep batches deliberately small and use a delay appropriate for the SMTP provider.
- Keep the invitation relevant and personalized; do not use the tool for indiscriminate bulk outreach.
- Include accurate sender identity and a clear reply path.
- Preserve all five locked live-send ledgers together: drafts, campaigns, candidates, evidence and suppressions.
- Back up the complete canonical workspace before any live pilot.
- Record no-contact requests through `manage_suppressions.py`; optionally reject the candidate too.
- Do not wrap the live command in cron, a scheduler, a queue or an automatic retry loop. The required
  human approvals, confirmation and reconciliation are deliberate controls.

## Testing

Install development dependencies:

```bash
python -m pip install -e ".[dev]" -c constraints.txt
```

Run the complete local suite:

```bash
ruff format --check .
ruff check .
python -m pytest --cov=speaker_pipeline --cov-report=term-missing
python -m compileall -q speaker_pipeline scripts
```

Tests use local simulated webpages and simulated SMTP behavior. They require no credentials, do not
access live websites, and never send real email. Passing tests does not establish that a production
SMTP account, provider policy, authentication setup, or inbox delivery has been validated.

See `TEST_REPORT.md` for the latest verification results and test boundaries.

## Repository and Release Hygiene

Active files containing operational data are intentionally ignored by Git:

- `config/invitation.json`
- `config/industry_sources.csv`
- `config/campaigns.csv`
- `config/industry_targets.csv`
- `config/email_claims.csv`
- `config/email_evidence.csv`
- `data/candidates.csv`
- `data/email_drafts.csv`
- `data/evidence.csv`
- `data/suppressions.csv`
- generated files under `outputs/`

Commit only reviewed, fictional configuration intended for public distribution. A filename
containing `example` is not sufficient: private named-recipient research fixtures and the internal
campaign fixture are deliberately excluded too. Before publishing or tagging a release, complete
`docs/RELEASE_CHECKLIST.md` and inspect every potential secret-scan match.
