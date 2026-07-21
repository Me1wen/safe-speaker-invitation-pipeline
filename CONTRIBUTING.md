# Contributing

Thank you for helping improve the Safe Speaker Discovery and Invitation Workflow.

## Before You Start

- Open an issue before making a large behavioral or schema change.
- Never include real candidate records, recipient lists, SMTP credentials, private contact information, or copied website content in an issue, pull request, test fixture, or commit.
- Use fictional `example.com`, `example.org`, or `example.edu` data in tests and documentation.
- Do not weaken the two approval gates, dry-run default, official-domain allowlist, or duplicate-delivery protections.

## Development Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python scripts/create_workspace.py
```

## Required Checks

Before opening a pull request, run:

```bash
ruff format --check .
ruff check .
python -m pytest --cov=speaker_pipeline --cov-report=term-missing
python -m compileall -q speaker_pipeline scripts
```

Formatting can be applied with:

```bash
ruff format .
ruff check --fix .
```

## Pull Requests

A pull request should:

- explain the user-visible behavior;
- identify any safety, privacy, website-access, or delivery implications;
- include or update tests;
- update `README.md`, `CHANGELOG.md`, or the relevant document when behavior changes;
- avoid unrelated formatting or generated runtime files; and
- pass all GitHub Actions checks.

## Commit Guidance

Use clear, imperative commit messages, for example:

```text
Reject ambiguous leadership profile links
Preserve delivery ledger during draft regeneration
Document SMTP interruption recovery
```

By contributing, you agree that your contribution is licensed under the MIT License included in this repository.
