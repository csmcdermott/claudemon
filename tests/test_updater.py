# tests/test_updater.py
import json
import subprocess
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import claudemon.updater as updater


@pytest.fixture(autouse=True)
def reset_updater():
    updater._update_cache["data"] = None
    updater._update_cache["checked_at"] = None
    updater._update_status["state"] = "idle"
    updater._update_status["error"] = None
    yield


def _make_release_body(tag: str, has_zip: bool = True) -> bytes:
    url = (
        f"https://objects.githubusercontent.com/releases/{tag}/claudemon-{tag}.zip"
    )
    assets = (
        [{"name": f"claudemon-{tag}.zip", "browser_download_url": url}]
        if has_zip
        else []
    )
    return json.dumps({"tag_name": tag, "assets": assets}).encode()


def _mock_resp(body: bytes):
    m = MagicMock()
    m.read.return_value = body
    m.__enter__ = MagicMock(return_value=m)
    m.__exit__ = MagicMock(return_value=False)
    return m


def test_parse_version_with_v_prefix():
    assert updater._parse_version("v0.5.13") == (0, 5, 13)


def test_parse_version_without_prefix():
    assert updater._parse_version("0.5.13") == (0, 5, 13)


def test_parse_version_prerelease_suffix():
    assert updater._parse_version("v0.6.0-rc1") == (0, 6, 0)


def test_check_for_updates_newer_version():
    body = _make_release_body("v99.0.0")
    with patch("claudemon.updater.urllib.request.urlopen", return_value=_mock_resp(body)):
        result = updater.check_for_updates()
    assert result["available"] is True
    assert result["version"] == "99.0.0"
    assert result["asset_url"] is not None
    assert updater._update_cache["checked_at"] is not None


def test_check_for_updates_same_version():
    tag = f"v{updater._APP_VERSION}"
    body = _make_release_body(tag)
    with patch("claudemon.updater.urllib.request.urlopen", return_value=_mock_resp(body)):
        result = updater.check_for_updates()
    assert result["available"] is False


def test_check_for_updates_older_version():
    body = _make_release_body("v0.0.1")
    with patch("claudemon.updater.urllib.request.urlopen", return_value=_mock_resp(body)):
        result = updater.check_for_updates()
    assert result["available"] is False


def test_check_for_updates_cache_ttl():
    body = _make_release_body("v99.0.0")
    with patch(
        "claudemon.updater.urllib.request.urlopen", return_value=_mock_resp(body)
    ) as mock_open:
        updater.check_for_updates()
        updater.check_for_updates()  # second call should hit cache
    assert mock_open.call_count == 1


def test_check_for_updates_network_error():
    with patch(
        "claudemon.updater.urllib.request.urlopen",
        side_effect=urllib.error.URLError("no network"),
    ):
        result = updater.check_for_updates()
    assert result["available"] is False


def test_check_for_updates_no_zip_asset():
    body = _make_release_body("v99.0.0", has_zip=False)
    with patch("claudemon.updater.urllib.request.urlopen", return_value=_mock_resp(body)):
        result = updater.check_for_updates()
    assert result["available"] is True
    assert result["asset_url"] is None


def test_check_for_updates_null_assets():
    body = json.dumps({"tag_name": "v99.0.0", "assets": None}).encode()
    with patch("claudemon.updater.urllib.request.urlopen", return_value=_mock_resp(body)):
        result = updater.check_for_updates()
    assert result["available"] is True
    assert result["asset_url"] is None


# --- get_update_asset_url ---

def test_get_update_asset_url_empty_cache():
    assert updater.get_update_asset_url() is None


def test_get_update_asset_url_no_update():
    updater._update_cache["data"] = {"available": False, "version": "0.5.0"}
    assert updater.get_update_asset_url() is None


def test_get_update_asset_url_asset_none():
    updater._update_cache["data"] = {
        "available": True, "version": "99.0.0", "asset_url": None
    }
    assert updater.get_update_asset_url() is None


def test_get_update_asset_url_returns_url():
    updater._update_cache["data"] = {
        "available": True,
        "version": "99.0.0",
        "asset_url": "https://objects.githubusercontent.com/foo/bar.zip",
    }
    assert updater.get_update_asset_url() == (
        "https://objects.githubusercontent.com/foo/bar.zip"
    )


# --- get_update_state_for_response ---

def test_get_update_state_for_response_excludes_asset_url():
    updater._update_cache["data"] = {
        "available": True,
        "version": "99.0.0",
        "asset_url": "https://objects.githubusercontent.com/foo/bar.zip",
    }
    result = updater.get_update_state_for_response()
    assert "asset_url" not in result
    assert result["available"] is True
    assert result["version"] == "99.0.0"


def test_get_update_state_for_response_empty_cache():
    result = updater.get_update_state_for_response()
    assert result == {"available": False}


# --- get_update_status ---

def test_get_update_status_initial():
    assert updater.get_update_status() == {"state": "idle", "error": None}


# --- _install_app ---

def _make_bundle(path: Path, marker: str):
    path.mkdir(parents=True, exist_ok=True)
    (path / "marker.txt").write_text(marker)


def _fake_ditto(returncode: int = 0, stderr: str = "", make_dest: bool = True,
                on_call=None):
    def run(cmd, capture_output=False, text=False, **kw):
        dest = Path(cmd[2])
        if on_call is not None:
            on_call(dest)
        if returncode == 0 and make_dest:
            _make_bundle(dest, "new")
        return subprocess.CompletedProcess(cmd, returncode, stdout="", stderr=stderr)
    return run


def test_install_app_fresh_no_existing(tmp_path):
    src = tmp_path / "src.app"
    _make_bundle(src, "new")
    dest = tmp_path / "dest.app"
    with patch("claudemon.updater.subprocess.run", _fake_ditto()):
        updater._install_app(src, dest)
    assert (dest / "marker.txt").read_text() == "new"
    assert not list(tmp_path.glob("dest.app.old-*"))


def test_install_app_replaces_existing(tmp_path):
    src = tmp_path / "src.app"
    _make_bundle(src, "new")
    dest = tmp_path / "dest.app"
    _make_bundle(dest, "old")
    with patch("claudemon.updater.subprocess.run", _fake_ditto()):
        updater._install_app(src, dest)
    assert (dest / "marker.txt").read_text() == "new"
    assert not list(tmp_path.glob("dest.app.old-*"))


def test_install_app_moves_old_aside_before_ditto(tmp_path):
    # Prove the running bundle is renamed aside, not overwritten in place.
    src = tmp_path / "src.app"
    _make_bundle(src, "new")
    dest = tmp_path / "dest.app"
    _make_bundle(dest, "old")
    seen = {}

    def on_call(d):
        seen["dest_exists"] = d.exists()
        seen["backup_exists"] = bool(list(tmp_path.glob("dest.app.old-*")))

    with patch("claudemon.updater.subprocess.run", _fake_ditto(on_call=on_call)):
        updater._install_app(src, dest)
    assert seen["dest_exists"] is False
    assert seen["backup_exists"] is True


def test_install_app_restores_on_ditto_failure(tmp_path):
    src = tmp_path / "src.app"
    _make_bundle(src, "new")
    dest = tmp_path / "dest.app"
    _make_bundle(dest, "old")
    fake = _fake_ditto(returncode=1, stderr="Operation not permitted", make_dest=False)
    with patch("claudemon.updater.subprocess.run", fake):
        with pytest.raises(RuntimeError, match="Operation not permitted"):
            updater._install_app(src, dest)
    # original bundle restored, no partial dest, no leftover backup
    assert (dest / "marker.txt").read_text() == "old"
    assert not list(tmp_path.glob("dest.app.old-*"))
