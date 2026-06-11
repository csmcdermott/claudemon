# TODO

Known open issues. Pull requests welcome.

## Security

These issues are low-risk for a local personal tool (the HTTP server binds to 127.0.0.1 only and
is not exposed to the network), but should be addressed before wider distribution.

- **CSRF on POST routes** — `/api/quit` and `/api/config` have no `Origin` header check. Any
  localhost-accessible browser tab can kill the app or rewrite config. Fix: validate `Origin`
  against `http://127.0.0.1:<port>` (empty string is acceptable for WKWebView).

- **Exception messages leak in error responses** — `_json_error(500, str(exc))` echoes internal
  exception text (file paths, type names) into HTTP responses. Fix: log via `log.exception`,
  return a fixed `"internal error"` body.

- **Config POST not hardened** — `int(Content-Length)` accepts negative values (`rfile.read(-1)`
  reads to EOF); no key allowlist on the JSON body. Fix: clamp length to ≤ 64 KiB; validate keys
  against `{task_gap_minutes}`.

- **Custom range input not validated** — `_range_to_timestamps("custom:...")` raises
  `ValueError`/`IndexError` on malformed input, caught only by the generic 500 handler. Fix:
  validate format and return 400.

- **Chart.js CDN loaded without SRI** — `dashboard/index.html` loads Chart.js from jsDelivr
  without a `integrity="sha384-..."` attribute. A compromised CDN could execute arbitrary JS in
  the WKWebView. Fix: add `integrity` + `crossorigin="anonymous"`, or vendor `chart.js` locally.

- **Runtime dependencies unpinned** — `rumps`, `watchdog`, and `pyobjc-framework-WebKit` use
  `>=` bounds. A bad upstream release would be picked up silently. Fix: pin with `~=` or commit a
  lock file (`uv lock` / `pip-compile`).

## Tech Debt

- **No JS unit tests** — `colorClass`, `fmtResetsAt`, `padBuckets`, `bucketLabel`, `viewBuckets`
  have no automated tests. Needs a runner decision (Node + jsdom, Bun, or pytest + Playwright)
  before adding tooling.

- **No DST regression test** — `_range_to_timestamps("day:...")` had a real DST bug; fix is in
  place but no regression test exists. Portable TZ manipulation in pytest requires
  `TZ=America/Los_Angeles` env override (macOS/Linux only).

- **Startup time grows linearly** — full re-index on every launch. Currently ~100–200 ms for
  ~370 sessions; will grow as history accumulates.

- **Unsigned .app bundle** — first launch requires right-click → Open (Gatekeeper). Code signing
  and notarization are required for broader distribution outside this repo.
