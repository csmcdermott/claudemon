# Usage Strip Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a compact strip to the claudemon dashboard showing live Anthropic 5-hour session and 7-day weekly rate-limit utilization bars, sourced from the Anthropic OAuth usage API via Claude Code's existing Keychain credentials.

**Architecture:** A new `keychain.py` module reads the OAuth token from macOS Keychain via the `security` CLI. A new `/api/usage` route in `server.py` calls `api.anthropic.com/api/oauth/usage` on-demand with a 2-minute in-memory cache. Dashboard JS polls `/api/usage` every 2 minutes and renders two side-by-side progress bars with color-coded fill and reset-time labels.

**Tech Stack:** Python stdlib (`subprocess`, `urllib.request`, `threading`), existing `http.server` handler pattern, vanilla JS (`fetch`, `setInterval`), CSS (hardcoded hex colors matching existing style).

---

## File Map

| Action | Path | What changes |
|---|---|---|
| **Create** | `claudemon/keychain.py` | `KeychainError`, `read_access_token()` |
| **Create** | `tests/test_keychain.py` | 4 unit tests for keychain reading |
| **Modify** | `claudemon/server.py` | Add imports, `_usage_cache`, `_USAGE_LOCK`, `_call_usage_api()`, `/api/usage` handler branch |
| **Modify** | `tests/test_server.py` | Add `_reset_usage_cache()` helper + 5 new tests |
| **Modify** | `claudemon/dashboard/index.html` | Insert `#usage-strip` div between `#custom-picker` and `.stats` |
| **Modify** | `claudemon/dashboard/style.css` | Add all `.usage-*` CSS classes |
| **Modify** | `claudemon/dashboard/app.js` | Add `fmtResetsAt`, `colorClass`, `renderUsageStrip`, `fetchUsage`; wire polling in `DOMContentLoaded` |

---

## Task 1: `keychain.py` + unit tests

**Files:**
- Create: `claudemon/keychain.py`
- Create: `tests/test_keychain.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_keychain.py`:

```python
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
just test tests/test_keychain.py
```

Expected: `ModuleNotFoundError: No module named 'claudemon.keychain'`

- [ ] **Step 3: Implement `claudemon/keychain.py`**

```python
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
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
just test tests/test_keychain.py
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add claudemon/keychain.py tests/test_keychain.py
git commit -m "feat(keychain): read Claude Code OAuth token from macOS Keychain"
```

---

## Task 2: `/api/usage` server endpoint + tests

**Files:**
- Modify: `claudemon/server.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Write the failing tests**

Add the following to `tests/test_server.py`. Insert the import additions at the top of the file and the helper + test functions at the bottom:

```python
# At the top of the file, add these imports (alongside existing ones):
import claudemon.server as srv
from unittest.mock import MagicMock, patch
from claudemon.keychain import KeychainError
```

```python
# ── /api/usage tests ─────────────────────────────────────────────────────────

_MOCK_API_RESPONSE = {
    "five_hour": {"utilization": 42.0, "resets_at": "2026-06-09T18:00:00Z"},
    "seven_day":  {"utilization": 67.0, "resets_at": "2026-06-13T00:00:00Z"},
}


def _reset_usage_cache():
    srv._usage_cache["data"] = None
    srv._usage_cache["fetched_at"] = None


def test_usage_returns_data(server):
    _reset_usage_cache()
    with patch("claudemon.keychain.read_access_token", return_value="tok"), \
         patch("claudemon.server._call_usage_api", return_value=_MOCK_API_RESPONSE):
        data = _get(server + "/api/usage")
    assert data["available"] is True
    assert data["five_hour"]["utilization"] == 42.0
    assert data["seven_day"]["utilization"] == 67.0


def test_usage_cache_hit(server):
    _reset_usage_cache()
    with patch("claudemon.keychain.read_access_token", return_value="tok") as mock_kc, \
         patch("claudemon.server._call_usage_api", return_value=_MOCK_API_RESPONSE):
        _get(server + "/api/usage")
        _get(server + "/api/usage")
    assert mock_kc.call_count == 1  # fetched once, second call used cache


def test_usage_cache_miss_after_ttl(server):
    _reset_usage_cache()
    with patch("claudemon.keychain.read_access_token", return_value="tok"), \
         patch("claudemon.server._call_usage_api", return_value=_MOCK_API_RESPONSE):
        _get(server + "/api/usage")
    # Expire the cache manually
    srv._usage_cache["fetched_at"] = time.time() - 121
    with patch("claudemon.keychain.read_access_token", return_value="tok") as mock_kc2, \
         patch("claudemon.server._call_usage_api", return_value=_MOCK_API_RESPONSE):
        _get(server + "/api/usage")
    assert mock_kc2.call_count == 1  # re-fetched after TTL


def test_usage_keychain_error(server):
    _reset_usage_cache()
    with patch("claudemon.keychain.read_access_token", side_effect=KeychainError("not found")):
        data = _get(server + "/api/usage")
    assert data["available"] is False
    assert "Token not found" in data["error"]


def test_usage_401(server):
    _reset_usage_cache()
    import urllib.error
    from io import BytesIO
    http_err = urllib.error.HTTPError(
        url="https://api.anthropic.com/api/oauth/usage",
        code=401,
        msg="Unauthorized",
        hdrs={},
        fp=BytesIO(b""),
    )
    with patch("claudemon.keychain.read_access_token", return_value="tok"), \
         patch("claudemon.server._call_usage_api", side_effect=http_err):
        data = _get(server + "/api/usage")
    assert data["available"] is False
    assert "expired" in data["error"]
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
just test tests/test_server.py::test_usage_returns_data
```

Expected: `AttributeError: module 'claudemon.server' has no attribute '_usage_cache'`

- [ ] **Step 3: Implement the `/api/usage` endpoint in `server.py`**

**3a.** Add two new imports at the top of `claudemon/server.py` (after the existing imports):

```python
import urllib.error
import urllib.request

from claudemon import keychain
```

**3b.** Add the cache, lock, and helper function after the existing imports, before `_tz_offset_ms`:

```python
_usage_cache: dict = {"data": None, "fetched_at": None}
_USAGE_LOCK = threading.Lock()


def _call_usage_api(token: str) -> dict:
    """Call Anthropic OAuth usage API. Returns parsed JSON dict."""
    req = urllib.request.Request(
        "https://api.anthropic.com/api/oauth/usage",
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())
```

**3c.** Inside `_make_handler`, in the `do_GET` method, add this branch **between** the `/api/config` branch and the `else: self._json_error(404, "not found")` line:

```python
                elif parsed.path == "/api/usage":
                    with _USAGE_LOCK:
                        now = time.time()
                        cached_ok = (
                            _usage_cache["fetched_at"] is not None
                            and now - _usage_cache["fetched_at"] < 120
                        )
                        if cached_ok:
                            self._json(_usage_cache["data"])
                            return
                    try:
                        token = keychain.read_access_token()
                        raw = _call_usage_api(token)
                        result = {
                            "available": True,
                            "five_hour": raw.get("five_hour"),
                            "seven_day": raw.get("seven_day"),
                        }
                        with _USAGE_LOCK:
                            _usage_cache["data"] = result
                            _usage_cache["fetched_at"] = time.time()
                        self._json(result)
                    except keychain.KeychainError:
                        self._json({
                            "available": False,
                            "error": "Token not found — run any claude command to refresh credentials",
                        })
                    except urllib.error.HTTPError as e:
                        msg = (
                            "Token expired — run any claude command to refresh"
                            if e.code == 401
                            else f"Usage API error (HTTP {e.code})"
                        )
                        self._json({"available": False, "error": msg})
                    except (urllib.error.URLError, OSError):
                        self._json({"available": False, "error": "Network error — check your connection"})
                    return
```

The exact location: the `do_GET` handler has an `if/elif` chain for each `/api/*` path. Find this block:

```python
                elif parsed.path == "/api/config":
                    config = json.loads(config_path.read_text()) if config_path.exists() else {}
                    self._json({**config, "_version": _APP_VERSION})

                else:
                    self._json_error(404, "not found")
```

Insert the new `elif parsed.path == "/api/usage":` block between `/api/config` and `else`.

- [ ] **Step 4: Run tests to confirm they pass**

```bash
just test tests/test_server.py
```

Expected: all existing tests + 5 new tests pass. No failures.

- [ ] **Step 5: Commit**

```bash
git add claudemon/server.py tests/test_server.py
git commit -m "feat(server): add /api/usage endpoint with 2-min in-memory cache"
```

---

## Task 3: Dashboard HTML + CSS

**Files:**
- Modify: `claudemon/dashboard/index.html`
- Modify: `claudemon/dashboard/style.css`

- [ ] **Step 1: Add the usage strip HTML**

In `claudemon/dashboard/index.html`, insert the `#usage-strip` div **between** the `#custom-picker` div and the `.stats` div. Find this existing block:

```html
</div>
<div id="custom-error" class="picker-error"></div>
</div>

<div class="stats">
```

Replace it with:

```html
</div>
<div id="custom-error" class="picker-error"></div>
</div>

<div id="usage-strip">
  <div class="usage-bar-group">
    <div class="usage-row">
      <span class="usage-lbl">5-hour session</span>
      <span class="usage-pct" id="usage-5h-pct">—</span>
    </div>
    <div class="usage-track"><div class="usage-fill" id="usage-5h-fill"></div></div>
    <div class="usage-reset" id="usage-5h-reset"></div>
  </div>
  <div class="usage-divider"></div>
  <div class="usage-bar-group">
    <div class="usage-row">
      <span class="usage-lbl">7-day weekly</span>
      <span class="usage-pct" id="usage-7d-pct">—</span>
    </div>
    <div class="usage-track"><div class="usage-fill" id="usage-7d-fill"></div></div>
    <div class="usage-reset" id="usage-7d-reset"></div>
  </div>
</div>

<div class="stats">
```

- [ ] **Step 2: Add the usage strip CSS**

Append the following to the end of `claudemon/dashboard/style.css`:

```css
/* ── Usage strip ─────────────────────────────────────────────────────────── */
#usage-strip {
  display: flex;
  gap: 16px;
  align-items: stretch;
  padding: 10px 16px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}

.usage-bar-group { flex: 1; }

.usage-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 4px;
}

.usage-lbl { font-size: 11px; color: #888; }

.usage-pct {
  font-size: 11px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.usage-track {
  height: 5px;
  background: rgba(255,255,255,0.06);
  border-radius: 3px;
  overflow: hidden;
}

.usage-fill {
  height: 100%;
  width: 0;
  border-radius: 3px;
  transition: width 0.4s ease;
}

.usage-reset {
  font-size: 10px;
  color: #555;
  margin-top: 3px;
  min-height: 14px;
}

.usage-divider {
  width: 1px;
  background: rgba(255,255,255,0.06);
  align-self: stretch;
  flex-shrink: 0;
}

.usage-error {
  font-size: 11px;
  color: #666;
  padding: 2px 0;
  align-self: center;
}

/* Color states for .usage-fill and .usage-pct */
.usage-green  { color: #34d399; background: #34d399; }
.usage-yellow { color: #f59e0b; background: #f59e0b; }
.usage-orange { color: #f97316; background: #f97316; }
.usage-red    { color: #ef4444; background: #ef4444; }
```

Note: `.usage-green` etc. set both `color` (for `.usage-pct`) and `background` (for `.usage-fill`). JS adds the class to both elements.

- [ ] **Step 3: Commit**

```bash
git add claudemon/dashboard/index.html claudemon/dashboard/style.css
git commit -m "feat(dashboard): add usage strip HTML and CSS"
```

---

## Task 4: Dashboard JS

**Files:**
- Modify: `claudemon/dashboard/app.js`

- [ ] **Step 1: Add helper functions**

In `claudemon/dashboard/app.js`, add the following four functions after the `fmtDuration` function (around line 53) and before `toDatetimeLocal`:

```js
function fmtResetsAt(isoStr) {
  const d = new Date(isoStr);
  const secs = (d - Date.now()) / 1000;
  if (secs <= 0) return 'resetting now';
  if (secs < 3600) {
    return `resets in ${Math.max(1, Math.floor(secs / 60))}m`;
  }
  if (secs < 86400) {
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    return m > 0 ? `resets in ${h}h ${m}m` : `resets in ${h}h`;
  }
  const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const pad = n => String(n).padStart(2, '0');
  return `resets ${DAYS[d.getDay()]} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function colorClass(pct) {
  if (pct < 50) return 'usage-green';
  if (pct < 80) return 'usage-yellow';
  if (pct < 95) return 'usage-orange';
  return 'usage-red';
}

function renderUsageStrip(data) {
  const strip = document.getElementById('usage-strip');
  if (!data.available) {
    strip.innerHTML = `<div class="usage-error">⚠ ${data.error ?? 'Rate limits unavailable'}</div>`;
    return;
  }
  const COLOR_CLASSES = ['usage-green', 'usage-yellow', 'usage-orange', 'usage-red'];

  function updateBar(pctElId, fillElId, resetElId, bucket) {
    const pctEl  = document.getElementById(pctElId);
    const fillEl = document.getElementById(fillElId);
    const resetEl = document.getElementById(resetElId);
    if (!bucket || bucket.utilization == null) {
      pctEl.textContent = '—';
      fillEl.style.width = '0';
      fillEl.className = 'usage-fill';
      pctEl.className = 'usage-pct';
      resetEl.textContent = '';
      return;
    }
    const pct = Math.round(bucket.utilization);
    const cls = colorClass(pct);
    pctEl.textContent = pct + '%';
    COLOR_CLASSES.forEach(c => { pctEl.classList.remove(c); fillEl.classList.remove(c); });
    pctEl.classList.add(cls);
    fillEl.classList.add(cls);
    fillEl.style.width = Math.min(100, pct) + '%';
    resetEl.textContent = bucket.resets_at ? fmtResetsAt(bucket.resets_at) : '';
  }

  updateBar('usage-5h-pct', 'usage-5h-fill', 'usage-5h-reset', data.five_hour);
  updateBar('usage-7d-pct', 'usage-7d-fill', 'usage-7d-reset', data.seven_day);
}

async function fetchUsage() {
  try {
    const data = await fetch('/api/usage').then(r => r.json());
    renderUsageStrip(data);
  } catch (_) {
    const strip = document.getElementById('usage-strip');
    strip.innerHTML = '<div class="usage-error">⚠ Could not reach local server</div>';
  }
}
```

- [ ] **Step 2: Wire up polling in `DOMContentLoaded`**

In `claudemon/dashboard/app.js`, find the `document.addEventListener('DOMContentLoaded', ...)` block. It currently calls `refresh()` and `refreshBanner()` and sets up two `setInterval` calls. Add `fetchUsage()` and its interval:

Find this block:

```js
document.addEventListener('DOMContentLoaded', () => {
  initCharts();
  refresh();
  refreshBanner();

  setInterval(refresh, 30_000);
  setInterval(refreshBanner, 5_000);
```

Replace with:

```js
document.addEventListener('DOMContentLoaded', () => {
  initCharts();
  refresh();
  refreshBanner();
  fetchUsage();

  setInterval(refresh, 30_000);
  setInterval(refreshBanner, 5_000);
  setInterval(fetchUsage, 120_000);
```

- [ ] **Step 3: Commit**

```bash
git add claudemon/dashboard/app.js
git commit -m "feat(dashboard): wire usage strip JS — fetchUsage, renderUsageStrip, polling"
```

---

## Task 5: Verify quality gates

- [ ] **Step 1: Run full test suite**

```bash
just test
```

Expected: all tests pass. If any fail, read the failure message and fix the specific issue before continuing.

- [ ] **Step 2: Run linter**

```bash
just lint
```

Expected: no errors. Common fix: `just lint` uses ruff; if it flags unused imports or style issues, fix them.

- [ ] **Step 3: Run coverage**

```bash
just coverage
```

Expected: coverage ≥ 80% on covered modules. `keychain.py` is not macOS-only so it will be covered. If coverage drops, check which new lines are untested and add tests for them.

- [ ] **Step 4: Confirm the new endpoint is in `pyproject.toml` omit list if needed**

Open `pyproject.toml` and check the `[tool.coverage.run]` `omit` list. `keychain.py` should **not** be in the omit list — it's testable on any platform. No change needed unless coverage tools flag it incorrectly.

- [ ] **Step 5: Final commit (if any fixes were needed)**

```bash
git add -p   # stage only the specific fix files
git commit -m "fix: address lint/coverage issues from usage strip"
```
