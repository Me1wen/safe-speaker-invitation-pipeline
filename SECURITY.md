# Security Policy

## Supported Version

Security fixes are currently applied to the latest `1.x` release.

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
- The project cannot guarantee the accuracy or continued safety of third-party website content.
- SMTP delivery is not transactionally idempotent. The `Sending` state intentionally requires human investigation after an interrupted attempt.
- Operators are responsible for access control, backups, legal compliance, provider limits, and appropriate recipient outreach.
