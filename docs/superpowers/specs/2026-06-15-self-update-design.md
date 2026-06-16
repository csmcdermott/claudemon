# Self-Update Feature Design

**Date:** 2026-06-15
**Status:** Approved (updated after architecture, quality, and security review)

## Overview

claudemon checks GitHub releases for a newer version on dashboard open (with a 1-hour server-side cache). If a newer version is found and the app is running as a `.app` bundle, a notification banner appears at the top of the dashboard offering a one-click in-place update: download the release zip, verify the domain, extract it, replace `/Applications/claudemon.app`, relaunch the new version, and quit the current process.

Also in this spec: the selected time range tab is persisted to config and restored on next open.

## Architecture

### New module: `claudemon/updater.py`

Single-responsibility module for all update logic. No timer threads — the HTTP handler calls it on demand.

**Constants:**
- `GITHUB_REPO = "csmcdermott/claudemon"`
- `CACHE_TTL = 3_600` (1 hour — short enough that a yanked/compromised release is not cached long)
- `_TRUSTED_HOSTS = {"github.com", "objects.githubusercontent.com"}`

**`_update_cache: dict`** — `{"data": None, "checked_at": None}`, guarded by `_UPDATE_LOCK`.

**`_update_status: dict`** — `{"state": "idle", "error": None}`, guarded by `_UPDATE_LOCK`. States: `"idle"`, `"running"`, `"failed"`.

---

**`check_for_updates() -> dict`**
- Acquires `_UPDATE_LOCK` to read cache. If `checked_at` is set and `time.time() - checked_at < CACHE_TTL`, returns cached data immediately (no network call).
- Otherwise: calls `GET https://api.github.com/repos/csmcdermott/claudemon/releases/latest` with `Accept: application/vnd.github+json` and `User-Agent: claudemon` headers, 10s timeout.
- Compares `tag_name` against `_APP_VERSION` using tuple comparison. Pre-release suffixes are stripped before parsing: `tag.lstrip("v").split("-")[0].split(".")`. Both parts are converted to `int`; `ValueError` falls to the exception handler.
- Schema guard on `assets`: `assets = release.get("assets") or []`; iterate with `isinstance(a, dict) and str(a.get("name","")).endswith(".zip")` — tolerates null/missing fields.
- If latest > current: returns `{"available": True, "version": "<tag without v>", "asset_url": "<url>"}`. `asset_url` is stored in the cache but **not** returned to callers outside this module — see `get_update_asset_url()`.
- If no `.zip` asset found: returns `{"available": True, "version": "<tag>", "asset_url": None}` — update is signalled but button is suppressed (no URL to download).
- If current >= latest: returns `{"available": False, "version": _APP_VERSION}`.
- On any exception: returns `{"available": False}` — no raise.
- Stores result and timestamp in `_update_cache` under lock.

**`get_update_asset_url() -> str | None`**
- Returns `_update_cache["data"]["asset_url"]` if the cached state is `{"available": True, "asset_url": <non-None>}`, otherwise `None`. Holds lock during read.
- Used by `POST /api/update` — the server never reads raw cache internals. This is the only path from which `asset_url` is used; it is **not** included in any HTTP response.

**`get_update_state_for_response() -> dict`**
- Returns a copy of `_update_cache["data"]` with `asset_url` removed. Safe to return directly in HTTP responses.

**`get_update_status() -> dict`**
- Returns a copy of `_update_status` under lock. Shape: `{"state": "idle"|"running"|"failed", "error": None|"<message>"}`.

---

**`perform_update(asset_url: str) -> None`** — `# pragma: no cover`

Called from a **non-daemon** thread started by `POST /api/update`. Non-daemon ensures the thread is not killed by SIGTERM mid-download.

```
1. Set _update_status["state"] = "running" (under lock)
2. Validate asset_url:
   parsed = urlparse(asset_url)
   assert parsed.scheme == "https" and parsed.netloc in _TRUSTED_HOSTS
   (raises ValueError on failure → caught below)
3. with tempfile.TemporaryDirectory() as tmp:
   a. Download: open urlopen(Request(asset_url), timeout=60) → read → write to tmp/claudemon.zip
      (urlopen follows redirects; GitHub assets redirect to objects.githubusercontent.com — in _TRUSTED_HOSTS)
   b. Extract: subprocess.run(["ditto", "-x", "-k", zip_path, tmp], check=True)
   c. Verify: app_tmp = Path(tmp) / "claudemon.app"
              assert app_tmp.is_dir() and not app_tmp.is_symlink()
   d. Install: subprocess.run(["ditto", str(app_tmp), "/Applications/claudemon.app"], check=True)
   e. Cleanup: shutil.rmtree(tmp, ignore_errors=True)  ← explicit before SIGTERM
   f. Launch:  subprocess.Popen(["open", "/Applications/claudemon.app"])
   g. Quit:    os.kill(os.getpid(), signal.SIGTERM)
      (non-daemon thread; SIGTERM handled by rumps; HTTP 200 was already sent before this thread started)
4. On any exception:
   print(f"[claudemon] update failed: {exc}", file=sys.stderr)
   Set _update_status = {"state": "failed", "error": str(exc)} (under lock)
   (process does not quit; dashboard detects failure via GET /api/update-status)
```

---

### server.py changes

**CSRF token**
- At module load: `_CSRF_TOKEN = secrets.token_hex(32)` (stdlib `secrets`, no new dep).
- `GET /` (index.html): served with `<meta name="csrf-token" content="<token>">` injected into the HTML before serving (string replace on the static file bytes, or a template placeholder).
- All state-mutating POSTs (`/api/update`, `/api/quit`, `/api/config`): check `self.headers.get("X-CSRF-Token") == _CSRF_TOKEN`. Return 403 on mismatch. WKWebView loads `index.html` from localhost — the meta tag is always present.
- This fixes the deferred CSRF issue on all three POST endpoints simultaneously.

**`GET /api/update-check`**
- Calls `updater.check_for_updates()`, then `updater.get_update_state_for_response()`.
- Injects `"bundle": bool(getattr(sys, "frozen", False))`.
- **Does not include `asset_url`** — the download URL is a server-internal detail.
- Always returns 200.

**`GET /api/update-status`**
- Calls `updater.get_update_status()`.
- Returns `{"state": "idle"|"running"|"failed", "error": null|"<message>"}`.
- Always returns 200.

**`POST /api/update`**
- CSRF check (see above) → 403 on failure.
- Returns 400 if `not sys.frozen`.
- Calls `updater.get_update_asset_url()`. Returns 400 (`"No update available"`) if result is `None` — covers: cache empty, `available: False`, `asset_url: None` (no zip asset).
- Starts `threading.Thread(target=updater.perform_update, args=(asset_url,), daemon=False)`.
- Returns `{"status": "started"}`.
- Path comparison uses `urlparse(self.path).path`.

---

## API

### `GET /api/update-check`

```json
// Update available, bundle — button shown
{"available": true, "version": "0.6.0", "bundle": true}

// Update available, no zip asset — informational only
{"available": true, "version": "0.6.0", "bundle": true}

// Up to date
{"available": false, "version": "0.5.17", "bundle": true}

// Dev (not frozen)
{"available": true, "version": "0.6.0", "bundle": false}

// Error (silent)
{"available": false, "bundle": true}
```

Note: `asset_url` is **not** in any response shape. The client does not need it and should not receive it.

### `GET /api/update-status`

```json
{"state": "idle",     "error": null}
{"state": "running",  "error": null}
{"state": "failed",   "error": "ditto: exit code 1"}
```

### `POST /api/update`

No body. Requires `X-CSRF-Token: <token>` header. Returns `{"status": "started"}` (200), `{"error": "..."}` (400), or 403 on CSRF failure.

---

## Dashboard

### `index.html`

Inject CSRF meta tag in `<head>`:
```html
<meta name="csrf-token" content="{{CSRF_TOKEN}}">
```
(Server replaces `{{CSRF_TOKEN}}` with `_CSRF_TOKEN` when serving `/`.)

New `#update-banner` immediately after `#banner`:
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

**CSRF token**: Read once at module init: `const CSRF_TOKEN = document.querySelector('meta[name="csrf-token"]')?.content ?? ''`. Pass as `'X-CSRF-Token': CSRF_TOKEN` header on all fetch POST calls.

**`fetchUpdateCheck()`**
- Fetches `/api/update-check`.
- On success, calls `renderUpdateBanner(data)`. Errors silently swallowed.
- Called once at end of first `refresh()` call (guarded by `_stateRestored`).

**`renderUpdateBanner(data)`**
- If `!data.available`: hides `#update-banner` and returns.
- Checks `sessionStorage.getItem("update-dismissed")` — if equal to `data.version`, hides banner and returns.
- Sets `#update-msg` textContent to `"claudemon " + esc(data.version) + " is available"`.
- If `data.bundle`: shows Update now and dismiss buttons.
- If `!data.bundle`: hides buttons, shows dev-mode note as textContent (no innerHTML).
- Removes `hidden` from `#update-banner`.

**Update now button (two-step confirm)**

State 1 — initial:
- `#update-confirm-btn` text: "Update now"
- `#update-dismiss-btn` text: "✕"
- Click confirm → State 2

State 2 — confirm:
- `#update-confirm-btn` text: "Confirm update"
- `#update-dismiss-btn` text: "Cancel"; click resets both to State 1 text, does NOT write sessionStorage
- Click confirm → State 3

State 3 — in progress:
- Hides `#update-actions`, shows `#update-progress`: "Updating… app will restart shortly"
- POSTs `/api/update` with `X-CSRF-Token` header
- Starts polling `GET /api/update-status` every 2s
- If status is `"failed"`: shows error text in `#update-progress`, re-shows `#update-actions` (back to State 1) so user can retry

**Dismiss button (State 1 only)**
- Sets `sessionStorage.setItem("update-dismissed", data.version)`
- Hides `#update-banner`

### `style.css`

`.update-banner` — blue/teal accent (e.g. `#3b82f6` tint) to distinguish from orange `.banner`. Flexbox row, space-between. Includes `.update-btn` (small blue button) and `.update-dismiss` (ghost, no border).

---

## Active Range Persistence

### Overview

When the user selects a named time range tab (12H, 7d, 30d, All), that selection is saved to `~/.claudemon/config.json` and restored the next time the dashboard opens. The Custom range is not persisted (its start/end dates are ephemeral and would be stale on next session).

### Config key

New key: **`active_range`** — one of `"today"`, `"7d"`, `"30d"`, `"all"`. Stored in `~/.claudemon/config.json` via the existing `POST /api/config` endpoint. Absent or invalid values default to `"7d"` on restore.

Must be added to the `POST /api/config` allowlist when that security fix is implemented (currently deferred — see Known Issues in project-analysis.md).

### server.py changes

None beyond the allowlist addition. `GET /api/config` already returns the full config dict; `active_range` appears in its response automatically once stored.

### app.js changes

**On tab click**: after activating a named range, call `api.post('/api/config', { active_range: currentRange })` with CSRF token. Do not call for `"custom"` range clicks.

**On first `refresh()` (inside `_stateRestored` block)**: read `cfg.active_range` from the `GET /api/config` response. If it's one of `["today", "7d", "30d", "all"]`, programmatically activate that tab (update `currentRange`, set `active` CSS class, trigger data refresh). If absent, invalid, or `"custom"`, leave default `"7d"` active.

### Testing

No new server-side tests needed. The allowlist test (when written) must include `active_range`. JS behaviour covered by manual QA.

---

## Error Handling

| Scenario | Behavior |
|---|---|
| GitHub API unreachable / timeout | Silent: `available: false`, no banner |
| Release has no `.zip` asset | `available: true`, no `asset_url` → Update button hidden, informational text only |
| `asset_url` fails domain validation | Exception caught → `_update_status.state = "failed"`, error shown in banner |
| `ditto` / subprocess failure | Thread catches exception → `state = "failed"`, banner shows error, user can retry |
| Symlink in temp dir | `assert` fails → same failure path as above |
| Not running as bundle | 400 from POST; dev-mode note shown instead of button |
| CSRF mismatch | 403 — no action taken |
| `get_update_asset_url()` returns None (cache empty or no update) | 400 from POST |
| Pre-release version tag (e.g. `v0.6.0-rc1`) | Suffix stripped before parse; comparison proceeds correctly |

---

## Known Risks

**No zip integrity verification**: The downloaded `.zip` is not checksummed or signature-verified. HTTPS (TLS) provides transport integrity — a network MitM cannot substitute bytes without breaking the TLS handshake. The residual risk is a compromised GitHub account or CI pipeline delivering a malicious `.app` through a legitimate HTTPS URL. The running app holds an OAuth token; a compromised update would inherit it.

Mitigation roadmap (not in this release):
1. Publish a `SHA256SUMS` file alongside each release zip; verify in `perform_update` before extraction.
2. Longer term: minisign detached signatures with a hard-coded public key in the app.

Accepted for this personal-use release. Revisit before any public distribution.

---

## Testing

### `tests/test_updater.py` (new file)

**Fixture**: `@pytest.fixture(autouse=True)` that resets `updater._update_cache` and `updater._update_status` to their initial state before each test — prevents module-level state bleed.

Tests:
- `test_parse_version_with_v_prefix` — `"v0.5.13"` → `(0, 5, 13)`
- `test_parse_version_without_prefix` — `"0.5.13"` → `(0, 5, 13)`
- `test_parse_version_prerelease_suffix` — `"v0.6.0-rc1"` → `(0, 6, 0)` (suffix stripped)
- `test_check_for_updates_newer_version` — mock `urlopen` returning release with newer tag; asserts `available: True`, correct `version`, `asset_url` in internal cache; `get_update_state_for_response()` has no `asset_url` key
- `test_check_for_updates_same_version` — asserts `available: False`
- `test_check_for_updates_older_version` — asserts `available: False`
- `test_check_for_updates_cache_ttl` — second call within 1h does not call `urlopen` again
- `test_check_for_updates_network_error` — `urlopen` raises `URLError`; returns `{"available": False}` without raising
- `test_check_for_updates_no_zip_asset` — release assets contain no `.zip`; returns `{"available": True, "version": "...", "asset_url": None}`; `get_update_asset_url()` returns `None`
- `test_check_for_updates_null_assets` — release has `"assets": null`; handled safely (schema guard)
- `test_get_update_asset_url_empty_cache` — returns `None` when cache is uninitialized
- `test_get_update_asset_url_no_update` — returns `None` when `available: False`
- `test_get_update_asset_url_returns_url` — returns URL string when `available: True` with asset
- `test_update_status_initial` — `get_update_status()` returns `{"state": "idle", "error": None}`

### `tests/test_server.py` (additions)

**Fixture**: reset `updater._update_cache` and `updater._update_status` before each test (shared with above).

Tests:
- `test_update_check_endpoint_shape` — `GET /api/update-check` returns JSON with `available`, `bundle` keys; no `asset_url` key in response
- `test_update_check_bundle_flag_false` — `sys.frozen` patched to `False`; `bundle` is `False`
- `test_update_check_bundle_flag_true` — `sys.frozen` patched to `True`; `bundle` is `True`
- `test_update_status_endpoint` — `GET /api/update-status` returns `{"state": "idle", "error": null}`
- `test_update_post_csrf_missing` — `POST /api/update` with no `X-CSRF-Token` → 403
- `test_update_post_csrf_wrong` — wrong token → 403
- `test_update_post_not_frozen` — correct CSRF, `sys.frozen = False` → 400
- `test_update_post_no_update_available` — correct CSRF, frozen, cache empty → 400
- `test_update_post_asset_url_none` — correct CSRF, frozen, cache has `available: True` but `asset_url: None` → 400
- `test_update_post_starts_thread` — correct CSRF, frozen, cache has valid state; `perform_update` patched to no-op; asserts 200 + `{"status": "started"}`; asserts thread was started

### Manual QA checklist

- Dismiss banner → sessionStorage stores version → banner stays hidden on re-open within same session
- Cancel in State 2 → banner resets to State 1, no sessionStorage write
- Dev mode (not frozen) → banner shows, no Update button, note visible
- No zip asset → banner shows, no Update button, informational text
- Failed update → error shown in banner, user can retry
- Active range persists: select 30d, close panel, reopen → 30d active
- Custom range not persisted: select custom, close panel, reopen → previous named range active

---

## Constraints

- macOS only: `ditto` and `open -a` are macOS-native. This feature is macOS-only.
- Replaces `/Applications/claudemon.app` specifically. If running from another path (e.g. `dist/`), a new copy is created at `/Applications/claudemon.app`. A code comment in `perform_update` notes this.
- `perform_update` is not covered by unit tests (marked `# pragma: no cover`). Mock-based tests for URL validation, happy path, and failure path should be added in a follow-up when time allows.
