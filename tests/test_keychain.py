import json
from unittest.mock import MagicMock, patch

import pytest

from claudemon.keychain import KeychainError, read_access_token


def _proc(stdout="", returncode=0):
    m = MagicMock()
    m.stdout = stdout
    m.returncode = returncode
    return m


def test_read_token_shape_v2():
    blob = json.dumps({"claudeAiOauth": {"accessToken": "sk-test-v2"}})
    with patch("subprocess.run", return_value=_proc(blob)):
        assert read_access_token() == "sk-test-v2"


def test_read_token_shape_access_token():
    blob = json.dumps({"access_token": "sk-test-at"})
    with patch("subprocess.run", return_value=_proc(blob)):
        assert read_access_token() == "sk-test-at"


def test_read_token_not_found():
    with patch("subprocess.run", return_value=_proc(returncode=44)):
        with pytest.raises(KeychainError):
            read_access_token()


def test_read_token_unparseable():
    with patch("subprocess.run", return_value=_proc("{}")):
        with pytest.raises(KeychainError):
            read_access_token()
