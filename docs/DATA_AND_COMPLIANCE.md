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

## Outreach

- Send only relevant, individually reviewed invitations.
- Identify the sender and organization accurately.
- Use an accurate subject and a functional reply address.
- Explain why the recipient is relevant to the event.
- Honor requests for no further contact and record them in candidate notes.
- Follow applicable law, including requirements that may apply under CAN-SPAM or other privacy and communications rules.
- Follow the sender's institution policy and SMTP provider terms and limits.

## Retention and Access

Store candidate and delivery files only as long as needed. Limit access to authorized team members, use encrypted and access-controlled storage where appropriate, and maintain backups for active campaigns. Remove or anonymize information when it is no longer needed or when policy requires it.

## Public Repository Hygiene

Never commit:

- `config/invitation.json` with real event or sender data;
- `config/industry_sources.csv` if it contains sensitive business targeting;
- files under `data/` or generated output workbooks;
- `.env` files, credentials, tokens, cookies, or browser profiles;
- real recipient addresses in fixtures, screenshots, issues, or pull requests; or
- provider logs containing message or account identifiers.
