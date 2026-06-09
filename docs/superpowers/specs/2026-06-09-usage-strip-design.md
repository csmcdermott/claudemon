# Usage Strip — Design Spec

**Date:** 2026-06-09  
**Status:** Approved

## Overview

Add a compact rate-limit strip to the claudemon dashboard that shows live Anthropic 5-hour session and 7-day weekly utilization bars. Data comes from the Anthropic OAuth usage API, read via Claude Code's existing Keychain credentials.

Inspired by [agencyenterprise/claude-meter](https://github.com/agencyenterprise/claude-meter), which uses the same API.

---

## Goals

- Show current rate-limit capacity at a glance whenever the dashboard is open
- No new sign-in required — reuses Claude Code's existing OAuth token from macOS Keychain
- Minimal footprint: no background threads, no network calls when the dashboard is closed

---

## Architecture

Three new or modified components:

```
Dashboard JS  →  /api/usage (server.py)  →  keychain.py  →  security CLI  →  macOS Keychain
                      ↓ (on cache miss)
               api.anthropic.com/api/oauth/usage
```

### 1. `claudemon/keychain.py` (new file)

Reads the OAuth access token from macOS Keychain.

**Public interface:**
```python
class KeychainError(Exception): ...

def read_access_token() -> str:
    """Return the Claude Code OAuth access token from Keychain.
    Raises KeychainError if the item is missing or unparseable."""
```

**Implementation:**
- Calls `security find-generic-password -s "Claude Code-credentials" -a <username> -w` via `subprocess.run`
- The raw output is a JSON string. Parse it and extract `claudeAiOauth.accessToken`.
- Support three credential shapes (matching claude-meter's Keychain.swift):
  1. `{ "claudeAiOauth": { "accessToken": "..." } }` — Claude Code 2.x (primary)
  2. `{ "access_token": "..." }` — fallback shape
  3. Raw string token (legacy)
- Raise `KeychainError("not found")` if the `security` command exits non-zero.
- Raise `KeychainError("unparseable")` if none of the three shapes match.
- Never log or expose the token value.

### 2. `/api/usage` endpoint (added to `server.py`)

On-demand fetch with a 2-minute in-memory cache.

**Route:** `GET /api/usage`

**Cache:** Module-level dict `_usage_cache = {"data": None, "fetched_at": None}`. If `fetched_at` is not None and `time.time() - fetched_at < 120`, return `data` immediately.

**On cache miss:**
1. Call `keychain.read_access_token()`.
2. Make a GET request to `https://api.anthropic.com/api/oauth/usage` with:
   - `Authorization: Bearer <token>`
   - `anthropic-beta: oauth-2025-04-20`
   - `Accept: application/json`
   - Timeout: 10 seconds
3. Parse the JSON response and cache it with the current timestamp.
4. Return the parsed data.

**Success response shape:**
```json
{
  "available": true,
  "five_hour": { "utilization": 42.0, "resets_at": "2026-06-09T18:00:00Z" },
  "seven_day": { "utilization": 67.0, "resets_at": "2026-06-13T00:00:00Z" }
}
```
(`resets_at` is the raw ISO8601 string from the API; JS parses it.)

**Error response shape:**
```json
{ "available": false, "error": "Token not found — run any claude command to refresh credentials" }
```

**Error cases and messages:**
| Condition | Message shown |
|---|---|
| `KeychainError` | `"Token not found — run any claude command to refresh credentials"` |
| HTTP 401 | `"Token expired — run any claude command to refresh"` |
| Network / timeout | `"Network error — check your connection"` |
| Any other HTTP error | `"Usage API error (HTTP <code>)"` |

On error: do **not** cache the result (allow retry on next poll).

**HTTP status:** Always returns HTTP 200, even on error — the `available` field signals the error state to the dashboard.

### 3. Dashboard strip (HTML / CSS / JS)

#### HTML (`index.html`)

Insert `#usage-strip` between `#custom-picker` and `.stats`:

```html
<div id="usage-strip" class="usage-strip">
  <div class="usage-bar-group" id="usage-5h">
    <div class="usage-row">
      <span class="usage-lbl">5-hour session</span>
      <span class="usage-pct" id="usage-5h-pct">—</span>
    </div>
    <div class="usage-track"><div class="usage-fill" id="usage-5h-fill"></div></div>
    <div class="usage-reset" id="usage-5h-reset"></div>
  </div>
  <div class="usage-divider"></div>
  <div class="usage-bar-group" id="usage-7d">
    <div class="usage-row">
      <span class="usage-lbl">7-day weekly</span>
      <span class="usage-pct" id="usage-7d-pct">—</span>
    </div>
    <div class="usage-track"><div class="usage-fill" id="usage-7d-fill"></div></div>
    <div class="usage-reset" id="usage-7d-reset"></div>
  </div>
</div>
```

#### CSS (`style.css`)

```css
.usage-strip       — flex row, gap 16px, padding 10px 14px, background var(--bg-card), border-radius 8px
.usage-bar-group   — flex:1
.usage-row         — flex, justify-content: space-between, align-items: baseline, margin-bottom: 4px
.usage-lbl         — font-size 11px, color var(--text-secondary)
.usage-pct         — font-size 11px, font-weight 600, monospace; color driven by JS class
.usage-track       — height 5px, background var(--track-bg), border-radius 3px
.usage-fill        — height 100%, border-radius 3px, transition width 0.4s; width + color driven by JS
.usage-reset       — font-size 10px, color var(--text-dim), margin-top 3px
.usage-divider     — width 1px, background var(--border), align-self stretch
.usage-error       — font-size 11px, color var(--text-secondary), padding 4px 0 (shown instead of bars on error)
```

Color classes applied to `.usage-fill` and `.usage-pct` by JS:
- `usage-green` (`< 50`) — `#34d399`
- `usage-yellow` (`50–79`) — `#f59e0b`
- `usage-orange` (`80–94`) — `#f97316`
- `usage-red` (`≥ 95`) — `#ef4444`

#### JS (`app.js`)

**New functions:**

```js
async function fetchUsage()          // calls /api/usage, updates the strip
function renderUsageStrip(data)      // updates DOM from response
function colorClass(pct)             // returns 'usage-green'|'yellow'|'orange'|'red'
function fmtResetsAt(isoStr)         // formats reset time: "resets in 2h 15m" or "resets Mon 00:00"
```

**Polling:**
- Call `fetchUsage()` on page load (after stats fetch).
- Set an interval to call `fetchUsage()` every 120 000 ms (2 min).

**Loading state:** On first load, `usage-pct` shows `—` and `usage-fill` is 0-width. No skeleton animation needed (data arrives quickly).

**Error state:** Replace the two `usage-bar-group` contents with a single `.usage-error` div showing the error message from `data.error`. Show `⚠` prefix.

**`fmtResetsAt` logic:**
- Parse `resets_at` as a Date. Compute `secs = (resets_at - now) / 1000`.
- `secs < 3600` → `"resets in Xm"` (minutes only).
- `secs < 86400` → `"resets in Xh Ym"` (hours + minutes).
- `secs ≥ 86400` → `"resets Mon 00:00"` (short weekday + `HH:MM`, no seconds).

---

## Error Handling Summary

| Layer | Error | Behaviour |
|---|---|---|
| `keychain.py` | Item not found | Raises `KeychainError` |
| `keychain.py` | JSON unparseable | Raises `KeychainError` |
| `server.py` | `KeychainError` | Returns `{"available": false, "error": "Token not found…"}` |
| `server.py` | HTTP 401 | Returns `{"available": false, "error": "Token expired…"}` |
| `server.py` | Timeout / network | Returns `{"available": false, "error": "Network error…"}` |
| `server.py` | Other HTTP error | Returns `{"available": false, "error": "Usage API error (HTTP N)"}` |
| `app.js` | `available: false` | Shows `⚠ <error message>` in strip |
| `app.js` | fetch() throws | Shows `⚠ Could not reach local server` |

---

## Testing

### `tests/test_keychain.py` (new)

| Test | What it covers |
|---|---|
| `test_read_token_shape_v2` | Primary JSON shape `{ claudeAiOauth: { accessToken } }` |
| `test_read_token_shape_access_token` | Fallback `{ access_token }` shape |
| `test_read_token_not_found` | `security` exits 44 → `KeychainError` |
| `test_read_token_unparseable` | Valid JSON but no known token field → `KeychainError` |

### `tests/test_server.py` additions

| Test | What it covers |
|---|---|
| `test_usage_returns_data` | Mock keychain + mock Anthropic HTTP → returns utilization fields |
| `test_usage_cache_hit` | Second call within 2 min does not re-fetch (keychain called once) |
| `test_usage_cache_miss_after_ttl` | Second call after TTL re-fetches |
| `test_usage_keychain_error` | `KeychainError` → `{"available": false}` HTTP 200 |
| `test_usage_401` | Anthropic returns 401 → `{"available": false, "error": "Token expired…"}` |

---

## Out of Scope

- Showing Opus / Sonnet per-model buckets (not in this feature)
- Menu bar icon changes (not requested)
- Persisting the cache across app restarts (in-memory only)
- Refreshing the token automatically (user must run `claude` to refresh)
