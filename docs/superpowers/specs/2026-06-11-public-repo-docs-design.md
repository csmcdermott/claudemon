## Public Repo Documentation — Design Spec

| Field | Value |
| --- | --- |
| **Date** | 2026-06-11 |
| **Status** | Approved |

## Goal

Make the claudemon repo fit for public consumption without changing any code.
Deliverables: README.md, CONTRIBUTORS.md, TODO.md, updated CLAUDE.md, reorganized justfile.

## README.md

Clean and minimal. Sections:
- One-line description
- Requirements (macOS 13+, Python 3.11+, just)
- Install from source (`just setup`, `just install-hooks`, `claudemon`)
- Build .app bundle (`just build`, `just install-app`) + Gatekeeper note
- Configuration (`~/.claudemon/config.json`, `task_gap_minutes`)
- Contributing pointer
- License

No badges, no screenshots, no marketing copy.

## CONTRIBUTORS.md

Lightweight guide. Sections:
- Prerequisites
- Setup (clone, `just setup`, `just install-hooks`)
- Development loop (`just lint`, `just test`, `just coverage`)
- Submitting a PR (fork, branch, PR description)
- Versioning note (pre-commit auto-bumps patch; run `just bump-minor` before a feature commit)

No code of conduct, no governance.

## TODO.md

Two sections documenting known open items:
- **Security** — 6 findings: CSRF on POST routes, error message leaking, config POST hardening,
  custom-range input validation, Chart.js CDN lacks SRI, runtime deps unpinned
- **Tech debt** — JS unit test coverage gap, DST regression test missing, startup time grows
  linearly with history, .app bundle is unsigned

## CLAUDE.md changes

- Replace `{PROJECT NAME}` with `claudemon` in the title
- Fill in the empty Architectural Notes section:
  - macOS-only (rumps + PyObjC; no Linux/Windows support)
  - In-memory SQLite only (full re-index on every launch; no persistent DB file)
  - Local data only (reads ~/.claude JSONL files; the only network call is optional /api/usage
    to Anthropic's OAuth API for rate-limit state)
  - NSPanel + WKWebView for dashboard popup (not native AppKit UI)

## justfile changes

- Add `default` recipe at top that runs `@just --list`
- Add `# Description` comments on all recipes (shown by `just --list`)
- Group with section header comments: Setup, Development, Quality, Versioning, Distribution
- Make `install-pre-commit` and `install-pre-push` private-style (kept but called only via `install-hooks`)
