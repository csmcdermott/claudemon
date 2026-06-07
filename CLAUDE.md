# {PROJECT NAME} - Overview

This document provides a technical overview of the {PROJECT NAME} project, intended to help AI Agents manage this project. 


## Project Structure

- **docs/**: A place to keep documentation and reference material for this project (eg, an OpenAPI spec of all API endpoints)
- **docs/agent/**: Persistent agent memory — `project-analysis.md` (architecture snapshot) and `lessons.md` (hard-won lessons)
- **scripts/**: A place to put utility scripts, such as pre-push scripts, custom linters, etc.

## Session Start

At the start of every session:
1. Read `docs/agent/project-analysis.md` to orient yourself on the current architecture and state of the project.
2. Read `docs/agent/lessons.md` for hard-won lessons from prior work on this project.

## Dev Workflow

Use `just` to run development tasks:

```bash
just lint        # Run linters
just test        # Run test suite
just coverage    # Run tests with coverage reporting
just install-pre-push  # Install the pre-push hook
```

The pre-push hook (`scripts/pre-push.sh`) blocks pushes when lint, coverage, or tests fail.


## Architectural Notes

- Put any high-level relevant constraints here, such as language choices or components


## Documentation
- Developer documentation for APIs should use the OpenAPI standard


## Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.
- **Secure by Default**: Security as a first-class concern. Keep attack surface area as small as possible.
- **Careful with Secrets**: Secrets (passwords, API keys, etc) MUST NOT be committed to version control in plain text.
- **No Laziness**: Find the root cause. No temporary fixes. Senior Engineer standards.
- **Minimal Impact**: Changes should only touch what's necessary. Avoid introducing bugs.
- **Minimal Dependencies**: Avoid introducing new external dependencies unless absolutely necessary. If a new dependency is required, state the reason.
- **Minimal Types**: Avoid introducing new types unless absolutely necessary. Continuously run typecheck to make sure you’re not introducing new issues.


## Quality Gates

- **Spec Completeness**: A plan is not complete until **ALL** requirements from the spec have been **proven** working.
- **Tests Passing**: A plan is not complete until **ALL** tests are passing and test coverage is >80%.


## Coding Style

- Use 4 spaces for indentation.
- Use YYYY-MM-DD-HH:mm format for timestamps.
- Use semantic versioning.
