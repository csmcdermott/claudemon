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
    with patch("claudemon.keychain.pwd.getpwuid") as mock_pwd:
        mock_pwd.return_value.pw_name = "testuser"
        with patch("claudemon.keychain.subprocess.run", return_value=_proc(blob)):
            assert read_access_token() == "sk-test-v2"


def test_read_token_shape_access_token():
    blob = json.dumps({"access_token": "sk-test-at"})
    with patch("claudemon.keychain.pwd.getpwuid") as mock_pwd:
        mock_pwd.return_value.pw_name = "testuser"
        with patch("claudemon.keychain.subprocess.run", return_value=_proc(blob)):
            assert read_access_token() == "sk-test-at"


def test_read_token_shape_raw():
    """Test Shape 3: raw string token starting with sk-"""
    with patch("claudemon.keychain.pwd.getpwuid") as mock_pwd:
        mock_pwd.return_value.pw_name = "testuser"
        with patch("claudemon.keychain.subprocess.run", return_value=_proc("sk-ant-abc123def456")):
            assert read_access_token() == "sk-ant-abc123def456"


def test_read_token_not_found():
    with patch("claudemon.keychain.pwd.getpwuid") as mock_pwd:
        mock_pwd.return_value.pw_name = "testuser"
        with patch("claudemon.keychain.subprocess.run", return_value=_proc(returncode=44)):
            with pytest.raises(KeychainError):
                read_access_token()


def test_read_token_unparseable():
    with patch("claudemon.keychain.pwd.getpwuid") as mock_pwd:
        mock_pwd.return_value.pw_name = "testuser"
        with patch("claudemon.keychain.subprocess.run", return_value=_proc("{}")):
            with pytest.raises(KeychainError):
                read_access_token()


def test_read_token_garbage():
    """Test that unparseable non-JSON garbage raises KeychainError"""
    with patch("claudemon.keychain.pwd.getpwuid") as mock_pwd:
        mock_pwd.return_value.pw_name = "testuser"
        with patch("claudemon.keychain.subprocess.run", return_value=_proc("garbage")):
            with pytest.raises(KeychainError):
                read_access_token()


def test_read_token_pwd_error():
    """Test that OSError from pwd.getpwuid raises KeychainError"""
    with patch("claudemon.keychain.pwd.getpwuid") as mock_pwd:
        mock_pwd.side_effect = OSError("no such user")
        with pytest.raises(KeychainError):
            read_access_token()


def test_read_token_timeout():
    """Test that subprocess.TimeoutExpired raises KeychainError"""
    import subprocess
    with patch("claudemon.keychain.pwd.getpwuid") as mock_pwd:
        mock_pwd.return_value.pw_name = "testuser"
        with patch("claudemon.keychain.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("security", 5)
            with pytest.raises(KeychainError):
                read_access_token()
