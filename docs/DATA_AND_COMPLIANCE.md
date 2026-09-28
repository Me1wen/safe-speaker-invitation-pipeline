# Data, Website Access, and Outreach Guidance

This document is operational guidance, not legal advice. Operators should consult qualified counsel when necessary.

## Data Minimization

Collect only information needed to evaluate and contact a potential speaker. Prefer public professional information from official institutional or company pages. Do not add private addresses, personal phone numbers, authentication-protected content, or third-party broker data.

## Website Access

- Configure only official domains and pages relevant to the intended research.
- Respect `robots.txt`, access controls, rate limits, terms, and applicable law.
- Do not bypass login requirements, CAPTCHAs, blocks, or technical restrictions.
- Keep request limits low during configuration and review warnings manually.
- Website structure and content can change without notice; revalidate selectors and results.

## Human Review

Before approval, verify identity, current title, organization, topic relevance, profile source, email, and the appropriateness of the contact route. A departmental address is not a direct address and should receive the routed-contact template.

For targeted candidates, every referenced identity, role and email record must identify the same
campaign, target and candidate; contain the exact claim; have `Review Status = Accepted`; and use
`Claim Polarity = Supports`. Current outreach requires current temporal evidence. Direct addresses
must meet the campaign's E3/E4 exact-current threshold. Historical targets require an explicit
campaign opt-in, and deceased people are ineligible.

Freshness is relative to the campaign, not merely a nonempty timestamp. Live policy requires
Campaign `Research As Of` and Candidate `Role As Of`. Each bound identity, role and email evidence
record must have `Last Confirmed At` or `Retrieved At` on or after Research As Of and within any
declared `Effective From`/`Effective To` interval.

Keep the following assertions separate:

- the exact address was supplied as a claim;
- the local-part resembles a company pattern;
- the exact address appears in a historical record;
- a current authoritative or official source publishes the exact address;
- the address is bound to the intended person rather than a department; and
- the mailbox has delivered, bounced, replied, or been suppressed.

Do not use DNS/MX or SMTP probing to claim that an individual mailbox exists. A mailbox remains
`Unknown` until legitimate operational evidence supplies an allowed status. A draft becoming
`Sent` is not enough to mark the mailbox `Delivered`: `Sent` records SMTP acceptance, not final
inbox delivery.

## Outreach

- Send only relevant, individually reviewed invitations.
- Use a low-volume, manually confirmed pilot; do not use the project for prospecting, bulk mail or
  an unattended scheduled campaign.
- Identify the sender and organization accurately.
- Use an accurate subject and a functional reply address.
- Explain why the recipient is relevant to the event.
- Honor requests for no further contact immediately. Add an active global suppression by email,
  domain, target ID or candidate ID with `scripts/manage_suppressions.py`; notes alone do not block
  delivery.
- Treat hard bounces and legal/internal do-not-contact decisions as suppression events.
- Never automatically retry `Sending`. Use provider logs and Message-ID to reconcile it with
  `scripts/reconcile_delivery.py`; absence of evidence is not proof of rejection.
- Follow applicable law, including requirements that may apply under CAN-SPAM or other privacy and communications rules.
- Follow the sender's institution policy and SMTP provider terms and limits.

## Retention and Access

Store candidate and delivery files only as long as needed. Limit access to authorized team members,
use encrypted and access-controlled storage where appropriate, and maintain coordinated backups of
the campaign, candidate, evidence, suppression and delivery ledgers. Preserve suppression and
attempt audit history for the period required to enforce no-contact and duplicate-prevention policy;
then remove or anonymize data under an approved retention procedure.

The five live ledgers are locked together during a send, but CSV files are not a substitute for
organization-wide identity/access management, encrypted backups, legal hold or a durable provider
event store.

## Public Repository Hygiene

Never commit:

- `config/invitation.json` with real event or sender data;
- `config/industry_sources.csv` if it contains sensitive business targeting;
- files under `data/` or generated output workbooks;
- `.env` files, credentials, tokens, cookies, or browser profiles;
- real operational or named-person recipient lists in release fixtures, screenshots, issues, or
  pull requests; development-private research fixtures must remain excluded from package/release
  artifacts; or
- provider logs containing message or account identifiers.
