#!/usr/bin/env bash
set -e
echo "Running lint..."
.venv/bin/ruff check claudemon/ tests/
echo "Running tests with coverage..."
.venv/bin/pytest tests/ --cov=claudemon --cov-report=term-missing --cov-fail-under=80
echo "Pre-push checks passed."
