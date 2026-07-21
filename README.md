# Safe Speaker Discovery and Invitation Workflow

**Version:** 1.0.0

**Status:** Beta; suitable for reviewed, limited production use

**License:** MIT

This project combines the original academic discovery, industry discovery, and candidate-management packages into one review-first workflow:

1. Collect potential speakers from configured official websites.
2. Verify and approve candidates in one standardized review table.
3. Generate personalized invitation email drafts from approved candidates.
4. Review and approve each email draft separately.
5. Perform a dry run by default; connect to SMTP only after live sending is explicitly enabled and confirmed.
6. Record delivery status, timestamps, and Message-ID values in the draft ledger to reduce the risk of duplicate delivery.

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
- Running collection again does not overwrite a manually approved candidate.
- An `Approved` status from a legacy package is not automatically trusted. Migrated records become `Needs Review` and must be approved again.
- A candidate must have `Review Status = Approved` before an email draft can be generated.
- A draft must separately have `Draft Status = Approved` before it can be selected for sending.
- `send_approved_emails.py` does not open an SMTP connection by default.
- Live delivery requires both `--send` and `--confirm SEND_APPROVED_EMAILS`.
- SMTP passwords are read only from environment variables. They are never stored in configuration files, CSV files, or logs.
- Immediately before a delivery attempt, the draft is saved as `Sending`. If the program stops unexpectedly during the network request, that draft is not retried automatically. A person must investigate and resolve it, reducing accidental duplicate delivery.
- Always comply with applicable anti-spam, privacy, institutional, and email-provider rules. Use the workflow only for relevant, individually reviewed outreach.

## Installation

From the project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/create_workspace.py
```

On Windows PowerShell, activate the virtual environment with:

```powershell
.venv\Scripts\Activate.ps1
```

Initialization creates the following files without overwriting existing review work:

- `data/candidates.csv`
- `data/email_drafts.csv`
- `config/industry_sources.csv`
- `config/invitation.json`

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

## Step 2: Configure and Collect Industry Candidates

Edit `config/industry_sources.csv`. A blank working template is created during initialization, and `config/industry_sources.example.csv` shows the required structure.

Whenever possible, set `Profile Link Selector` to a CSS selector that targets person-profile links on the official leadership page. A specific selector substantially reduces false positives from ordinary site navigation.

```bash
python scripts/collect_industry.py \
  --allow-live-fetch \
  --limit-per-source 5
```

The collector requires the profile name to agree with the leadership-page name and requires a senior title containing terms such as Chief, President, Vice President, Founder, Chair, Managing Director, Executive Director, Global Head, Head of, or Senior Fellow. A failure for one company produces a warning without stopping the remaining companies.

Direct and departmental contact routes are stored separately:

- `Email` always contains one plain email address.
- `Contact Type` records `Direct`, `Media Relations`, `Public Affairs`, or another route type.
- `Email Source URL` records the official page where that email address was published.

If no verified public contact route is found, the candidate is retained as `Needs Review` and cannot be approved until a valid route is added.

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
  --input outputs/candidate_review.xlsx
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

Only a fully verified row should be changed to:

```text
Review Status = Approved
```

Run validation:

```bash
python scripts/validate_candidates.py
```

The QA report is written to `outputs/candidate_qa.csv`. An Approved candidate with a high-severity issue is blocked from email-draft generation.

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

## Step 4: Configure and Generate Email Drafts

Edit `config/invitation.json` before generating drafts. Replace every example value with real event information, including:

- event name, host, date, location, and description;
- sender name, title, organization, and email;
- subject template;
- body template for direct contact; and
- body template for routed contact through media relations, public affairs, or another department.

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

Direct contacts and departmental routes use different body templates. If a recipient address, contact type, subject, or body changes, the system creates a new Draft ID and requires a new approval.

## Step 5: Review and Approve Email Drafts

Review the recipient, salutation, event details, subject, body, and requested action. Only a draft that is ready for delivery should be changed to:

```text
Draft Status = Approved
```

If review was completed in Excel, import the workbook back into the canonical CSV:

```bash
python scripts/import_review_workbook.py \
  --kind drafts \
  --input outputs/email_draft_review.xlsx
```

Do not attempt live delivery directly from an Excel workbook. Live delivery requires the canonical CSV so status changes can be saved immediately.

## Step 6: Perform a Dry Run

```bash
python scripts/send_approved_emails.py
```

The dry run lists the recipients and subjects that would be selected. It does not read SMTP credentials, open a network connection, or send email.

Limit the dry run to a small batch if desired:

```bash
python scripts/send_approved_emails.py --max-messages 2
```

## Step 7: Configure SMTP and Send

Set SMTP values in the current shell. Never save the password in the project directory.

STARTTLS example:

```bash
export SMTP_HOST="smtp.example.org"
export SMTP_PORT="587"
export SMTP_USERNAME="your-account@example.org"
export SMTP_PASSWORD="your-app-password-or-smtp-token"
export SMTP_FROM_EMAIL="your-account@example.org"
export SMTP_FROM_NAME="Your Name"
export SMTP_REPLY_TO="your-account@example.org"
export SMTP_STARTTLS="true"
export SMTP_USE_SSL="false"
```

An SSL configuration commonly uses port 465 with `SMTP_USE_SSL=true` and `SMTP_STARTTLS=false`.

The first live run should send only one message:

```bash
python scripts/send_approved_emails.py \
  --send \
  --confirm SEND_APPROVED_EMAILS \
  --max-messages 1
```

Confirm that the message was received and formatted correctly before delivering the remaining Approved drafts:

```bash
python scripts/send_approved_emails.py \
  --send \
  --confirm SEND_APPROVED_EMAILS
```

Successful rows become `Sent`. Failed rows become `Failed` and record an error. Before retrying a failed item, investigate the cause and then manually return only that row to `Approved`.

Rows left as `Sending` indicate an interrupted or uncertain delivery attempt. Check the sender's mailbox and provider logs before changing the status. Never automatically retry an uncertain item.

## Operational Recommendations

- Start every new campaign with a one-message live test.
- Use a reasonable delay and batch size appropriate for the SMTP provider.
- Keep the invitation relevant and personalized; do not use the tool for indiscriminate bulk outreach.
- Include accurate sender identity and a clear reply path.
- Maintain the candidate and draft CSV files as the audit trail for approvals and delivery results.
- Back up the canonical CSV files before a large campaign.
- If a person requests no further contact, mark the candidate `Rejected` and record the request in `Notes`.

## Testing

Install development dependencies:

```bash
python -m pip install -e ".[dev]"
```

Run the complete local suite:

```bash
ruff format --check .
ruff check .
python -m pytest --cov=speaker_pipeline --cov-report=term-missing
python -m compileall -q speaker_pipeline scripts
```

Tests use local simulated webpages and a simulated SMTP server. They require no credentials, do not access live websites, and never send real email.

See `TEST_REPORT.md` for the latest verification results and test boundaries.

## Repository and Release Hygiene

Active files containing operational data are intentionally ignored by Git:

- `config/invitation.json`
- `config/industry_sources.csv`
- `data/candidates.csv`
- `data/email_drafts.csv`
- generated files under `outputs/`

Commit only the corresponding example configuration. Before publishing or tagging a release, complete `docs/RELEASE_CHECKLIST.md` and inspect every potential secret-scan match.
