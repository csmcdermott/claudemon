venv := ".venv/bin"

# List available recipes
default:
    @just --list

# ── Setup ─────────────────────────────────────────────────────────────────────

# Create .venv and install all dependencies (run once after cloning)
setup:
    python3 -m venv .venv
    {{venv}}/pip install --upgrade pip
    {{venv}}/pip install -e ".[dev]"

# Install pre-commit and pre-push hooks
install-hooks: _install-pre-commit _install-pre-push

# ── Development ───────────────────────────────────────────────────────────────

# Run linter
lint:
    {{venv}}/ruff check claudemon/ tests/

# Run test suite
test:
    {{venv}}/pytest tests/ -v

# Run tests with coverage report (must stay ≥ 80%)
coverage:
    {{venv}}/pytest tests/ --cov=claudemon --cov-report=term-missing --cov-fail-under=80

# ── Versioning ────────────────────────────────────────────────────────────────

# Bump patch version (0.2.0 → 0.2.1) — also run automatically by pre-commit hook
bump-patch:
    python3 scripts/bump_version.py patch

# Bump minor version (0.2.0 → 0.3.0) — run before committing a new feature
bump-minor:
    python3 scripts/bump_version.py minor

# Bump major version (0.2.0 → 1.0.0) — run before a breaking change
bump-major:
    python3 scripts/bump_version.py major

# ── Distribution ──────────────────────────────────────────────────────────────

# Build claudemon.app bundle (output: dist/claudemon.app)
build:
    rm -rf build dist
    {{venv}}/python setup.py py2app

# Build and install to /Applications/claudemon.app
install-app: build
    rm -rf /Applications/claudemon.app
    cp -r dist/claudemon.app /Applications/claudemon.app
    @echo "Installed to /Applications/claudemon.app"

# ── Internal ──────────────────────────────────────────────────────────────────

[private]
_install-pre-push:
    cp scripts/pre-push.sh .git/hooks/pre-push
    chmod +x .git/hooks/pre-push

[private]
_install-pre-commit:
    cp scripts/pre-commit.sh .git/hooks/pre-commit
    chmod +x .git/hooks/pre-commit
