# Lessons

_Hard-won lessons from working on this project. Add entries as surprises are discovered._

## Data

- Claude Code JSONL files use a `type` field to distinguish record kinds: `assistant`, `user`, `system`, `ai-title`, `attachment`, `last-prompt`, `mode`, `permission-mode`, `file-history-snapshot`. Only `assistant` records contain token usage data.
- Token usage is nested at `message.usage` inside assistant records, not at the top level.
- Cache data has two sub-fields in `cache_creation`: `ephemeral_1h_input_tokens` and `ephemeral_5m_input_tokens`. Cache reads are not broken down by tier — only `cache_read_input_tokens` total is available.
- The `gitBranch` field is present on `assistant`, `user`, and `attachment` records — reliable for task boundary detection.
- Session state is in `~/.claude/sessions/{pid}.json` with a `status` field. Value is `"busy"` when Claude is actively processing. File is updated frequently during active sessions.
- The Anthropic Admin API (usage/cost endpoints) requires `sk-ant-admin...` keys and is unavailable for claude.ai subscription users — local JSONL files are the only data source for Claude Code session usage on subscription plans.

## macOS / PyObjC

- `rumps` is built on PyObjC and handles the NSStatusItem. Drop to raw PyObjC only for the NSPopover — don't fight rumps for things it handles well.
- `pyobjc-framework-WebKit` is the package that provides `WKWebView`; it may not be installed by default even if other PyObjC frameworks are present.
