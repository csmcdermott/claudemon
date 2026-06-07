#!/usr/bin/env bash
set -e
echo "Running lint..."
ruff check claudemon/ tests/
echo "Running tests with coverage..."
pytest tests/ --cov=claudemon --cov-report=term-missing --cov-fail-under=80
echo "Pre-push checks passed."
