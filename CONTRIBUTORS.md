# Contributing to claudemon

## Prerequisites

- macOS 13+
- Python 3.11+
- [just](https://github.com/casey/just)

## Setup

```bash
git clone https://github.com/csmcdermott/claudemon.git
cd claudemon
just setup          # creates .venv and installs all dependencies
just install-hooks  # install pre-commit + pre-push hooks
```

## Development loop

```bash
just lint        # run ruff linter
just test        # run test suite
just coverage    # run tests with coverage report (must stay >= 80%)
```

The pre-push hook blocks pushes when lint, coverage, or tests fail.

## Submitting a pull request

1. Fork the repo and create a branch from `main`.
2. Make your changes. Keep each PR focused on a single concern.
3. Ensure `just lint`, `just test`, and `just coverage` all pass.
4. Open a PR with a clear description of what changed and why.

## Versioning

The pre-commit hook bumps the patch version automatically on every commit. No action needed for fixes.

Before committing a new feature, run `just bump-minor` first. Before a breaking change, run `just bump-major`.

Never edit `pyproject.toml` or `claudemon/_version.py` manually; always use the bump scripts.

## Releasing

```bash
just bump-minor   # for a feature release
just release      # builds .app, zips it, and publishes to GitHub releases
```
