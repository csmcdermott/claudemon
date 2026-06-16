# Self-Update Feature Design

**Date:** 2026-06-15
**Status:** Approved

## Overview

claudemon checks GitHub releases for a newer version on dashboard open (with a 24h server-side cache). If a newer version is found and the app is running as a `.app` bundle, a notification banner appears at the top of the dashboard offering a one-click in-place update: download the release zip, extract it, replace `/Applications/claudemon.app`, relaunch the new version, and quit the current process.

## Architecture

### New module: `claudemon/updater.py`

Single-responsibility module for all update logic. No timer threads — the HTTP handler calls it on demand.

**`GITHUB_REPO = "csmcdermott/claudemon"`**
**`CACHE_TTL = 86_400`** (24 hours)

**`check_for_updates() -> dict`**
- Acquires `_UPDATE_LOCK` to read `_update_cache`. If `checked_at` is set and `time.time() - checked_at < CACHE_TTL`, returns cached data immediately (no network call).
- Otherwise: calls `GET https://api.github.com/repos/csmcdermott/claudemon/releases/latest` with `Accept: application/vnd.github+json` and `User-Agent: claudemon` headers, 10s timeout.
- Compares `tag_name` (e.g. `"v0.6.0"`) against `_APP_VERSION` using tuple comparison after stripping the `v` prefix and splitting on `.`.
- If latest > current: finds the `.zip` asset in `release["assets"]`, returns `{"available": True, "version": "0.6.0", "asset_url": "https://..."}`.
- If current >= latest: returns `{"available": False, "version": _APP_VERSION}`.
- On any exception (network, JSON parse, version parse): returns `{"available": False}` — no raise, no banner.
- Updates `_update_cache` with the result and current timestamp under lock.

**`get_cached_state() -> dict | None`**
- Returns `_update_cache["data"]` under lock. Used by `POST /api/update` to avoid a redundant network call.

**`perform_update(asset_url: str) -> None`**
- Creates a tempdir via `tempfile.mkdtemp()`.
- Downloads zip to `{tmp}/claudemon.zip` via `urllib.request.urlretrieve`.
- Extracts with `subprocess.run(["ditto", "-x", "-k", zip_path, tmp], check=True)` — produces `{tmp}/claudemon.app`.
- Copies over installed app with `subprocess.run(["ditto", app_tmp, "/Applications/claudemon.app"], check=True)`.
- Launches new version: `subprocess.Popen(["open", "/Applications/claudemon.app"])`.
- Quits current process: `os.kill(os.getpid(), signal.SIGTERM)`.
- Any exception is logged; the process does not quit on failure (user sees the dashboard is still up).

### server.py changes

**`GET /api/update-check`**
- Calls `updater.check_for_updates()`.
- Injects `"bundle": bool(getattr(sys, "frozen", False))` into the response before returning.
- Response is always 200; errors are represented as `{"available": false}`.

**`POST /api/update`**
- Returns 400 if `not sys.frozen` ("Update only available in .app bundle").
- Returns 400 if `get_cached_state()` shows `available` is not `True` or `asset_url` is absent ("No update available").
- Otherwise: starts `threading.Thread(target=updater.perform_update, args=(asset_url,), daemon=True)` and responds `{"status": "started"}`.
- Path comparison uses `urlparse(self.path).path` (consistent with existing `do_POST` pattern).

## API

### `GET /api/update-check`

```json
// Update available, running as bundle
{"available": true, "version": "0.6.0", "asset_url": "https://github.com/...", "bundle": true}

// Up to date
{"available": false, "version": "0.5.13", "bundle": true}

// Running in dev (not frozen)
{"available": true, "version": "0.6.0", "asset_url": "https://...", "bundle": false}

// Error (silent)
{"available": false, "bundle": true}
```

### `POST /api/update`

No request body. Returns `{"status": "started"}` (200) or `{"error": "..."}` (400).

## Dashboard

### `index.html`

A new `<div id="update-banner" class="update-banner hidden">` is placed immediately after the existing `#banner` (active session banner).

Structure:
```html
<div id="update-banner" class="update-banner hidden">
  <span id="update-msg"></span>
  <div id="update-actions">
    <button id="update-confirm-btn" class="update-btn">Update now</button>
    <button id="update-dismiss-btn" class="update-dismiss">✕</button>
  </div>
  <span id="update-progress" class="hidden"></span>
</div>
```

### `app.js`

**`fetchUpdateCheck()`**
- Fetches `/api/update-check`.
- On success, calls `renderUpdateBanner(data)`. Errors are silently swallowed.
- Called once at the end of the first `refresh()` call (guarded by `_stateRestored` — same pattern as `applySectionOrder` and `initCollapsibles`).

**`renderUpdateBanner(data)`**
- If `!data.available`: hides `#update-banner` and returns.
- Checks `sessionStorage.getItem("update-dismissed")` — if it equals `data.version`, hides banner and returns (user dismissed this version in this session).
- Sets `#update-msg` text to `"claudemon ${esc(data.version)} is available"`.
- If `data.bundle`: shows Update now button and dismiss button.
- If `!data.bundle`: replaces Update now button with a non-interactive note: `"Run just build && just install-app to update."` — no button shown.
- Removes `hidden` class from `#update-banner`.

**Update now button (two-step confirm)**

State 1 — initial:
- Button text: "Update now"
- Click → State 2

State 2 — confirm:
- `#update-confirm-btn` text changes to "Confirm update"
- `#update-dismiss-btn` text changes to "Cancel" (replaces "✕"); clicking it resets both buttons back to State 1 text and does NOT store in sessionStorage
- Cancel → back to State 1

State 3 — in progress (after confirm click):
- Hides `#update-actions`, shows `#update-progress` with text: "Updating… app will restart shortly"
- POSTs `/api/update`
- No further UI changes needed — the app will restart, closing the panel

**Dismiss button**
- Sets `sessionStorage.setItem("update-dismissed", data.version)`
- Hides `#update-banner`

### `style.css`

`.update-banner` — styled similarly to `.banner` but with a distinct color (blue/teal accent, e.g. `#3b82f6` background tint) to differentiate from the orange active-session banner. Flexbox row with space-between alignment. Includes `.update-btn` (small button, blue) and `.update-dismiss` (ghost, no border).

## Error Handling

| Scenario | Behavior |
|---|---|
| GitHub API unreachable or timeout | Silent: `available: false`, no banner shown |
| Release has no `.zip` asset | `asset_url` absent; `data.bundle && !data.asset_url` → show informational text only, no Update button |
| `ditto` / subprocess failure during update | Thread catches exception, logs it; process does not quit; user sees dashboard still alive |
| Version string malformed | Caught as exception in `check_for_updates`; returns `available: false` |
| Not running as bundle | 400 from POST /api/update; dev-mode note shown in banner instead of button |

## Testing

### `tests/test_updater.py` (new file)

- `test_parse_version_with_v_prefix` — `"v0.5.13"` → `(0, 5, 13)`
- `test_parse_version_without_prefix` — `"0.5.13"` → `(0, 5, 13)`
- `test_check_for_updates_newer_version` — mock `urlopen` returning a release with newer tag; asserts `available: True`, correct `version`, correct `asset_url`
- `test_check_for_updates_same_version` — mock returns same version; asserts `available: False`
- `test_check_for_updates_older_version` — mock returns older version; asserts `available: False`
- `test_check_for_updates_cache_ttl` — second call within 24h does not call `urlopen` again
- `test_check_for_updates_network_error` — `urlopen` raises `URLError`; returns `{"available": False}` without raising
- `test_check_for_updates_no_zip_asset` — release assets contain no `.zip`; `asset_url` is `None`

### `tests/test_server.py` (additions)

- `test_update_check_endpoint` — `GET /api/update-check` returns JSON with `available` and `bundle` keys
- `test_update_post_not_frozen` — `POST /api/update` with `sys.frozen` patched to False → 400
- `test_update_post_no_update_available` — `POST /api/update` with empty update cache → 400

`perform_update` is not unit-tested (requires live subprocess and filesystem).

## Constraints

- macOS only: `ditto` is macOS-native. `open -a` is macOS-only. This feature is already macOS-only (py2app bundle).
- The update replaces `/Applications/claudemon.app` specifically. If the user installed elsewhere, the copy step will create `/Applications/claudemon.app` as a new location. Acceptable for personal use.
- No SRI / signature verification on the downloaded zip. Acceptable for personal use on a public repo.
- `perform_update` is not covered by unit tests. Manual QA required before each release.
