---
name: dashboard-ux-improvements
description: Sort skills/MCP by max tokens, persist collapse state, drag-to-reorder sections
metadata:
  type: project
---

# Dashboard UX Improvements

**Date:** 2026-06-13

## Summary

Three independent UX improvements to the claudemon dashboard:

1. Sort Skills and MCP tool rows by max output tokens (instead of call count)
2. Persist section collapsed/expanded state across app restarts
3. Drag-to-reorder collapsible sections, with order persisted across restarts

---

## Feature 1: Sort Skills & MCP by Max Tokens

### Current behaviour

`db.query_tool_usage` sorts both `skills` and `mcp` lists by `calls` descending. `renderSkills` / `renderMcp` in `app.js` compute bar widths relative to the highest call count.

### New behaviour

Both lists are sorted by `max_output_tokens` descending. Bar widths in the rendered rows are relative to the highest `max_output_tokens` value in the list (i.e. the bar tracks the metric being sorted by).

### Changes

**`claudemon/db.py`**
- `query_tool_usage`: change sort key from `"calls"` to `"max_output_tokens"` for both `skills` and `mcp`.

**`claudemon/dashboard/app.js`**
- `renderSkills`: replace `const maxCalls = skills[0].calls` with `const maxTok = skills[0].max_output_tokens`; replace `s.calls / maxCalls` with `s.max_output_tokens / maxTok`.
- `renderMcp`: same change.

No API shape changes. No new tests required beyond existing coverage (sort order is a trivial key swap).

---

## Feature 2: Persist Section Collapse State

### Storage mechanism

Collapse state is stored in `~/.claudemon/config.json` under the key `section_collapse_state`, a JSON object mapping `data-section-id` → `true` (open) or `false` (closed).

Example:
```json
{
  "section_collapse_state": {
    "recent-sessions": false,
    "tasks-queries": true,
    "queries-volume": false,
    "model-breakdown": true,
    "skills-used": true,
    "mcp-tools": true
  }
}
```

Written via `POST /api/config`. Read via the existing `api.config()` call inside `refresh()`.

### Restoration

A module-level flag `_stateRestored = false` prevents re-applying saved state on every poll refresh. On the first `refresh()` call (flag is false), apply saved state then set flag to true. Subsequent refreshes skip this step, preserving any live toggles the user has made mid-session.

### On toggle

After each collapse/expand click in `initCollapsibles()`, collect the current open/closed state of all `.csec` elements and POST to `/api/config`.

### Section IDs

Each `.csec` in `index.html` gets a `data-section-id` attribute:

| HTML section | `data-section-id` |
|---|---|
| Recent sessions | `recent-sessions` |
| Tasks & queries | `tasks-queries` |
| Queries by token volume | `queries-volume` |
| Model breakdown | `model-breakdown` |
| Skills used | `skills-used` |
| MCP tools | `mcp-tools` |

### Changes

**`claudemon/dashboard/index.html`**
- Add `data-section-id="..."` to each `.csec` div.

**`claudemon/dashboard/app.js`**
- Add `_stateRestored = false` module-level flag.
- Add `saveCollapseState()`: collects open/closed for all `.csec` elements by `data-section-id`, POSTs to `/api/config`.
- Update `initCollapsibles()`: after toggling, call `saveCollapseState()`.
- Update `refresh()`: if `!_stateRestored`, apply `config.section_collapse_state` (add/remove `.open` class per saved value), then set `_stateRestored = true`.

---

## Feature 3: Drag-to-Reorder Sections

### Implementation: native HTML5 Drag & Drop

No new library dependency (per CLAUDE.md "Minimal Dependencies"). Uses `draggable="true"` on each `.csec` element and the native `dragstart` / `dragover` / `drop` / `dragend` events.

### Drag handle

A `⠿` grab handle is added to the left side of each `.csec-hdr`. This makes the drag affordance visible without disrupting the existing collapse-toggle click behaviour. Click and drag are distinguished by the browser naturally: a click-without-drag fires only `click`; a drag fires `dragstart` and suppresses the `click`.

### DOM reordering

On `drop`, insert the dragged `.csec` before or after the target, depending on whether the mouse is in the top or bottom half of the target element.

On `dragend`, call `saveSectionOrder()`.

### Storage mechanism

Section order is stored in `~/.claudemon/config.json` under the key `section_order`, an array of `data-section-id` strings in display order.

Example:
```json
{
  "section_order": ["model-breakdown", "recent-sessions", "tasks-queries", "queries-volume", "skills-used", "mcp-tools"]
}
```

Written via `POST /api/config`. Read via `api.config()`.

### Restoration

`applySectionOrder(order)` re-inserts `.csec` elements before `<footer>` in saved order. Unknown IDs in the saved array are silently skipped. Sections not present in the saved array are appended after the known ones (forward-compatibility).

Called once per session on first `refresh()` (same `_stateRestored` guard is sufficient — both collapse state and section order are applied in the same first-refresh block, before setting the flag).

### Visual feedback during drag

- `.dragging` class on the element being dragged: reduced opacity.
- `.drag-over` class on the current drop target: top or bottom border highlight.

### Changes

**`claudemon/dashboard/index.html`**
- Add `data-section-id` to each `.csec` (shared with Feature 2).
- Add `<span class="drag-handle">⠿</span>` as the first child of each `.csec-hdr`.

**`claudemon/dashboard/app.js`**
- Add `initDragDrop()`: wires `dragstart`, `dragover`, `dragleave`, `drop`, `dragend` on all `.csec` elements.
- Add `saveSectionOrder()`: collects `data-section-id` values in DOM order, POSTs to `/api/config`.
- Add `applySectionOrder(order)`: reinserts `.csec` elements before `<footer>` in saved order.
- Update `refresh()`: inside the first-refresh block, call `applySectionOrder(config.section_order)` before applying collapse state.
- Call `initDragDrop()` in `DOMContentLoaded`.

**`claudemon/dashboard/style.css`**
- `.drag-handle`: muted colour, `cursor: grab`, `user-select: none`, small left margin.
- `.csec.dragging`: `opacity: 0.4`.
- `.csec.drag-over-top`: top border highlight (`border-top: 2px solid #a78bfa`).
- `.csec.drag-over-bottom`: bottom border highlight (`border-bottom: 2px solid #a78bfa`).

---

## Config key allowlist note

`/api/config` POST currently merges any JSON keys into the config file (known security issue per project-analysis.md). The keys `section_order` and `section_collapse_state` are internal — no validation changes are needed for this feature. The security hardening of the config endpoint is a separate deferred item.

---

## Testing

- No new server-side tests required (no API changes).
- Existing `test_server.py` coverage of `/api/config` POST/GET remains valid.
- Manual verification: sort order, collapse persistence, drag reorder, app restart restores state.
