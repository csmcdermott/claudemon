#!/usr/bin/env bash
set -e

# Skip auto-bump during merges (version already set)
if git rev-parse -q --verify MERGE_HEAD > /dev/null 2>&1; then
    exit 0
fi

NEW_VER=$(python3 "$(git rev-parse --show-toplevel)/scripts/bump_version.py" patch)
git add pyproject.toml claudemon/_version.py
echo "Version bumped to $NEW_VER"
