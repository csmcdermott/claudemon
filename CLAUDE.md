# claudemon — Overview

This document provides a technical overview of the claudemon project, intended to help AI Agents manage this project.


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
just install-hooks     # Install pre-commit + pre-push hooks (run once after cloning)
```

The pre-push hook (`scripts/pre-push.sh`) blocks pushes when lint, coverage, or tests fail.

## Versioning

This project uses **semantic versioning**. Version is defined in two places that must always stay in sync:
- `pyproject.toml` — packaging metadata
- `claudemon/_version.py` — runtime source of truth (imported by the server, displayed in the dashboard footer)

**Never edit these files manually.** Always use the bump scripts:

```bash
just bump-patch   # 0.2.0 → 0.2.1  (auto-run by pre-commit hook — you rarely need this)
just bump-minor   # 0.2.0 → 0.3.0  (run before committing a new feature)
just bump-major   # 0.2.0 → 1.0.0  (run before committing a breaking change)
```

**Rules:**
- The **pre-commit hook** auto-bumps the patch version on every commit — no manual action needed for fixes/tweaks.
- Before committing a **new feature**, run `just bump-minor` first (the hook will then bump patch on top — that's fine, it's just one extra patch).
- Before a **breaking change**, run `just bump-major` first.
- Merge commits are skipped by the hook.

The version is displayed in the dashboard footer and served via `/api/config` as `_version`.


## Architectural Notes

- **macOS-only**: Built on rumps + PyObjC (NSPanel, WKWebView). No Linux or Windows support.
- **In-memory SQLite only**: `db.connect()` always returns `":memory:"`. Full re-index on every
  launch; no persistent DB file. Adding a `DB_PATH` constant would be wrong.
- **Local data only**: Reads `~/.claude/projects/**/*.jsonl` and `~/.claude/sessions/*.json`.
  The only outbound network call is the optional `/api/usage` → Anthropic OAuth API for
  rate-limit state (115 s cache, fails gracefully if unavailable).
- **NSPanel + WKWebView for the dashboard**: Not a native AppKit UI. The panel hosts a WKWebView
  that loads `http://127.0.0.1:<port>/` — a local Chart.js dashboard served by `server.py`.
- **Python 3.11+ required**: Driven by the PyObjC dependency and f-string / match usage.


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
