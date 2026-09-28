# Security Policy

## Supported Version

Security fixes are currently applied to the latest `1.2.x` release.

## Reporting a Vulnerability

Do not disclose a vulnerability, exposed credential, recipient list, or other sensitive information in a public issue.

Use GitHub's private vulnerability reporting or security-advisory feature for the repository. If private reporting has not yet been enabled, contact the repository owner privately and request a secure reporting channel.

Include:

- the affected version or commit;
- a concise description of the impact;
- reproduction steps using fictional data only;
- whether SMTP credentials, recipient privacy, duplicate delivery, or domain restrictions are involved; and
- a suggested mitigation, if available.

You should receive an acknowledgment within seven calendar days. A remediation timeline will depend on severity and reproducibility.

## Credential Exposure

If a real SMTP password, app password, API token, service-account file, or private recipient list is committed or shared:

1. Revoke or rotate the credential immediately.
2. Stop any active campaign using that credential.
3. Remove the sensitive file from the working tree.
4. Follow the hosting provider's process for removing sensitive data from repository history.
5. Review delivery and access logs for misuse.

Deleting a secret in a later commit does not remove it from Git history and is not sufficient by itself.

## Security Boundaries

- This project does not store SMTP credentials; it reads them from environment variables.
- Live SMTP requires SSL or STARTTLS, except for a deliberate localhost-only test mode.
- Candidate and draft v2 approvals bind reviewer, time, revision and reviewed content. A draft also
  binds the exact candidate approval, full campaign policy and Sender Email/Name/Reply-To. Legacy
  v1 approvals may be inspected but cannot authorize live delivery.
- Approval SHA-256 values detect stale or accidental edits. They are not digital signatures and do
  not defend against an operator who can modify both code and canonical ledgers.
- Live policy requires one matching `Active` campaign, a current outreach window, a positive
  `Max Messages` cap, current accepted supporting evidence and no active global suppression.
  Evidence confirmation/retrieval and effective dates must be valid relative to Campaign
  `Research As Of`, and Candidate `Role As Of` is required.
- The explicit draft, campaign, candidate, evidence and suppression ledgers are locked in
  deterministic order from authoritative read through every delivery-state write. Policy is run
  again in a final preflight before SMTP is opened.
- Global suppressions cover email, domain, target ID and candidate ID. Opt-outs and hard bounces
  must be recorded there; free-text notes are not an enforcement control.
- Claimed addresses, naming patterns, historical addresses, domain mail routing, and current mailbox outcomes are represented separately.
- Official-page fetching rejects off-allowlist redirects and private, loopback, link-local, multicast, reserved, or unspecified destination addresses.
- Fetch checks are defense in depth, not a hostile-network sandbox: DNS validation is performed
  before the request and is not pinned to the connection, and the response-size check occurs
  after downloading the response. Use trusted, reviewed official-source allowlists and external
  network/resource controls; do not expose the collector as an arbitrary-URL fetching service.
- The project cannot guarantee the accuracy or continued safety of third-party website content.
- SMTP delivery is not transactionally idempotent. A timeout or disconnect may occur after provider
  acceptance, so ambiguous exceptions remain `Sending` and are never automatically retried.
- `scripts/reconcile_delivery.py` requires provider-side evidence, a provider reference, a named
  reviewer and an explicit confirmation before changing uncertain state.
- `Sent` means only that SMTP accepted the message; it does not prove inbox placement, reading or
  reply. There is no provider webhook, bounce processor or inbox monitor.
- The project intentionally has no unattended scheduler, background sending worker or mass-outreach
  mode. Wrapping the live command in automation bypasses the intended human control boundary.
- Operators are responsible for access control, backups, legal compliance, provider limits, and appropriate recipient outreach.
