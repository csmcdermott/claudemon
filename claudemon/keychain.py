import json
import os
import subprocess


class KeychainError(Exception):
    pass


def read_access_token() -> str:
    """Return the Claude Code OAuth access token from Keychain.

    Raises KeychainError if the Keychain item is missing or unparseable.
    Never logs or exposes the token value.
    """
    result = subprocess.run(
        [
            "security", "find-generic-password",
            "-s", "Claude Code-credentials",
            "-a", os.getlogin(),
            "-w",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise KeychainError("not found")

    raw = result.stdout.strip()

    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            # Shape 1: { "claudeAiOauth": { "accessToken": "..." } }  (Claude Code 2.x)
            oauth = obj.get("claudeAiOauth")
            if isinstance(oauth, dict):
                token = oauth.get("accessToken")
                if token:
                    return token
            # Shape 2: { "access_token": "..." }
            token = obj.get("access_token")
            if token:
                return token
    except json.JSONDecodeError:
        pass

    # Shape 3: raw string token (legacy — starts with "sk-" or contains ".")
    if raw.startswith("sk-") or ("." in raw and len(raw) > 20):
        return raw

    raise KeychainError("unparseable")
