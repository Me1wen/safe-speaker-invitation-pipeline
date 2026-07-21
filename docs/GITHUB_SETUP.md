# Publishing on GitHub

This repository is prepared for a public GitHub release, but publication is a deliberate human action. Before publishing, complete the repository-hygiene section of the [release checklist](RELEASE_CHECKLIST.md), especially the checks for customer data, recipient data, and credentials.

## Create the Repository

Create an empty GitHub repository without adding a README, license, or `.gitignore`; those files are already included here. Then run the following commands from the extracted project directory, replacing the example URL with the repository URL:

```bash
git init
git add .
git status
git commit -m "Initial public release"
git branch -M main
git remote add origin https://github.com/OWNER/REPOSITORY.git
git push -u origin main
```

Inspect `git status` before committing. Active configuration, generated candidate data, email drafts, logs, credentials, and local virtual environments must not appear in the staged file list.

## Recommended Repository Settings

In GitHub repository settings:

1. Enable Dependabot alerts and security updates.
2. Enable secret scanning, push protection, and private vulnerability reporting when they are available for the repository.
3. Protect the `main` branch and require the `CI` checks before merging.
4. Require pull requests for changes to the default branch.
5. Keep GitHub Actions permissions read-only unless a workflow specifically needs more access.
6. Add a short description, the project website if applicable, and relevant topics such as `python`, `email-automation`, `human-in-the-loop`, and `speaker-discovery`.

The included Dependabot, CI, CodeQL, issue-template, and pull-request-template files activate after the first push. Review their initial results before announcing the repository.

## First Release

After CI and CodeQL pass on `main`, create an annotated tag and push it:

```bash
git tag -a v1.0.0 -m "Safe Speaker Invitation Pipeline v1.0.0"
git push origin v1.0.0
```

Create a GitHub release from that tag, use `CHANGELOG.md` as the release-note source, and attach the tested source archive and its SHA-256 checksum. Do not attach active configuration, candidate tables, email drafts, or SMTP credentials.

## Deployment Validation

GitHub Actions intentionally does not perform live website collection or SMTP delivery. In the actual deployment environment:

1. Configure one approved test recipient that you control.
2. Generate and review the draft.
3. Run the default dry-run command.
4. Send one test message using the explicit live-send confirmation.
5. Verify the delivery ledger before enabling any larger batch.

Never store SMTP secrets in the repository. Use environment variables or the deployment platform's secret manager.
