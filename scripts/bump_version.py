#!/usr/bin/env python3
"""Bump the project version. Usage: bump_version.py [patch|minor|major]"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
TOML = ROOT / "pyproject.toml"
VERSION_PY = ROOT / "claudemon" / "_version.py"

text = TOML.read_text()
m = re.search(r'^version\s*=\s*"(\d+)\.(\d+)\.(\d+)"', text, re.MULTILINE)
if not m:
    sys.exit("Could not find version in pyproject.toml")

major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
part = sys.argv[1] if len(sys.argv) > 1 else "patch"

if part == "major":
    major, minor, patch = major + 1, 0, 0
elif part == "minor":
    major, minor, patch = major, minor + 1, 0
else:
    patch += 1

new_version = f"{major}.{minor}.{patch}"
TOML.write_text(text[: m.start(1)] + new_version + text[m.end(3) :])
VERSION_PY.write_text(f'__version__ = "{new_version}"\n')
print(new_version)
