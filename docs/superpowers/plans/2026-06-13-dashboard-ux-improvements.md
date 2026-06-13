# Dashboard UX Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sort skills/MCP by max output tokens, persist section collapse state and order to config, and enable drag-to-reorder collapsible sections.

**Architecture:** All three features are independent and touch different layers — `db.py` (sort), `index.html`/`style.css` (markup + styles), and `app.js` (behaviour + persistence). State is persisted via the existing `POST /api/config` endpoint into `~/.claudemon/config.json` and restored from `api.config()` on first `refresh()`.

**Tech Stack:** Python (db.py), HTML5 Drag & Drop API (no new deps), vanilla JS, CSS.

---

## File Map

| File | Change |
|---|---|
| `claudemon/db.py` | Sort skills/mcp by `max_output_tokens` instead of `calls` |
| `claudemon/dashboard/index.html` | Add `data-section-id` to each `.csec`; add `<span class="drag-handle">⠿</span>` inside each `.csec-hdr` |
| `claudemon/dashboard/style.css` | Add `.drag-handle`, `.csec.dragging`, `.drag-over-top`, `.drag-over-bottom`; give `.csec-title` `flex:1` |
| `claudemon/dashboard/app.js` | Update bar-width logic in `renderSkills`/`renderMcp`; add `_stateRestored`, `saveCollapseState`, `saveSectionOrder`, `applySectionOrder`, `initDragDrop`; update `initCollapsibles` and `refresh` |
| `tests/test_db.py` | Add `test_query_tool_usage_sorted_by_max_tokens`; update comment in `test_query_tool_usage_basic` |

---

### Task 1: Sort skills/MCP by max_output_tokens in db.py

**Files:**
- Modify: `claudemon/db.py:480-481`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_db.py` after the existing `test_query_tool_usage_p50_max` test:

```python
def test_query_tool_usage_sorted_by_max_tokens(conn):
    now = int(time.time() * 1000)
    db.upsert_session(conn, "s1", "proj", None, now - 5000, now, "main")
    # "alpha": 2 calls, small tokens (max 200)
    # "beta":  1 call,  large tokens (max 500)
    # sorted by calls: alpha first; sorted by max_output_tokens: beta first
    db.insert_tool_use(conn, "s1", "s1:1:1", now - 4000, "skill", "alpha", 100)
    db.insert_tool_use(conn, "s1", "s1:1:2", now - 3000, "skill", "alpha", 200)
    db.insert_tool_use(conn, "s1", "s1:1:3", now - 2000, "skill", "beta", 500)
    result = db.query_tool_usage(conn, (now - 10_000, now))
    assert result["skills"][0]["name"] == "beta"
    assert result["skills"][1]["name"] == "alpha"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_db.py::test_query_tool_usage_sorted_by_max_tokens -v
```

Expected: `FAILED` — `assert result["skills"][0]["name"] == "beta"` fails (currently "alpha" comes first by call count).

- [ ] **Step 3: Change sort key in db.py**

In `claudemon/db.py`, replace lines 480-481:

```python
    skills.sort(key=lambda x: x["calls"], reverse=True)
    mcp.sort(key=lambda x: x["calls"], reverse=True)
```

with:

```python
    skills.sort(key=lambda x: x["max_output_tokens"], reverse=True)
    mcp.sort(key=lambda x: x["max_output_tokens"], reverse=True)
```

- [ ] **Step 4: Update stale comment in existing test**

In `tests/test_db.py`, find `test_query_tool_usage_basic` and replace:

```python
    # brainstorming has 2 calls, tdd has 1 — sorted descending by calls
```

with:

```python
    # brainstorming max_output_tokens=1000, tdd max=800 — sorted descending by max_output_tokens
```

- [ ] **Step 5: Run all tool-usage tests**

```bash
.venv/bin/pytest tests/test_db.py -k "tool_usage" -v
```

Expected: all 5 tool-usage tests pass.

- [ ] **Step 6: Run full test suite and lint**

```bash
just test && just lint
```

Expected: all tests pass, lint clean.

- [ ] **Step 7: Commit**

```bash
git add claudemon/db.py tests/test_db.py
git commit -m "feat: sort skills and MCP tools by max output tokens"
```

---

### Task 2: Add data-section-id attributes and drag handles to index.html

**Files:**
- Modify: `claudemon/dashboard/index.html`

Each `.csec` gets a `data-section-id` attribute, and each `.csec-hdr` gets a `⠿` drag handle span as its first child.

- [ ] **Step 1: Update the six .csec elements**

Replace the six `.csec` blocks in `claudemon/dashboard/index.html` with:

```html
<div class="csec" data-section-id="recent-sessions">
  <div class="csec-hdr">
    <span class="drag-handle">⠿</span>
    <span class="csec-title">Recent sessions</span>
    <span class="csec-chevron">▶</span>
  </div>
  <div class="csec-body">
    <div id="sessions-list"></div>
  </div>
</div>

<div class="csec" data-section-id="tasks-queries">
  <div class="csec-hdr">
    <span class="drag-handle">⠿</span>
    <span class="csec-title">Tasks &amp; queries</span>
    <span class="csec-chevron">▶</span>
  </div>
  <div class="csec-body">
    <div class="legend" style="margin-bottom:4px">
      <div class="leg">
        <div style="display:flex;gap:2px">
          <div class="leg-dot" style="background:rgba(167,139,250,0.8)"></div>
          <div class="leg-dot" style="background:rgba(56,189,248,0.8)"></div>
          <div class="leg-dot" style="background:rgba(52,211,153,0.8)"></div>
        </div>
        tasks
      </div>
      <div class="leg"><div class="leg-line leg-dashed" style="border-color:#fcd34d"></div>p50 tok</div>
      <div class="leg"><div class="leg-line" style="background:#f87171"></div>top tok</div>
    </div>
    <div class="axis-labels"><div class="axis-lbl">← queries</div><div class="axis-lbl">tok/task →</div></div>
    <div class="chart-wrap tall"><canvas id="task-chart"></canvas></div>
  </div>
</div>

<div class="csec" data-section-id="queries-volume">
  <div class="csec-hdr">
    <span class="drag-handle">⠿</span>
    <span class="csec-title">Queries by token volume</span>
    <span class="csec-chevron">▶</span>
  </div>
  <div class="csec-body">
    <div class="legend" style="margin-bottom:4px">
      <div class="leg">
        <div style="display:flex;gap:2px">
          <div class="leg-dot" style="background:rgba(167,139,250,0.8)"></div>
          <div class="leg-dot" style="background:rgba(56,189,248,0.8)"></div>
          <div class="leg-dot" style="background:rgba(52,211,153,0.8)"></div>
        </div>
        queries
      </div>
      <div class="leg"><div class="leg-line leg-dashed" style="border-color:#fcd34d"></div>p50 tok</div>
      <div class="leg"><div class="leg-line" style="background:#f87171"></div>top tok</div>
    </div>
    <div class="axis-labels"><div class="axis-lbl">← tokens</div><div class="axis-lbl">tok/query →</div></div>
    <div class="chart-wrap tall"><canvas id="query-chart"></canvas></div>
  </div>
</div>

<div class="csec" data-section-id="model-breakdown">
  <div class="csec-hdr">
    <span class="drag-handle">⠿</span>
    <span class="csec-title">Model breakdown</span>
    <span class="csec-chevron">▶</span>
  </div>
  <div class="csec-body">
    <div id="models-list"></div>
  </div>
</div>

<div class="csec" data-section-id="skills-used">
  <div class="csec-hdr">
    <span class="drag-handle">⠿</span>
    <span class="csec-title">Skills used</span>
    <span class="csec-chevron">▶</span>
  </div>
  <div class="csec-body">
    <div id="skills-list"></div>
  </div>
</div>

<div class="csec" data-section-id="mcp-tools">
  <div class="csec-hdr">
    <span class="drag-handle">⠿</span>
    <span class="csec-title">MCP tools</span>
    <span class="csec-chevron">▶</span>
  </div>
  <div class="csec-body">
    <div id="mcp-list"></div>
  </div>
</div>
```

- [ ] **Step 2: Commit**

```bash
git add claudemon/dashboard/index.html
git commit -m "feat: add data-section-id and drag handles to collapsible sections"
```

---

### Task 3: Add drag styles to style.css

**Files:**
- Modify: `claudemon/dashboard/style.css`

- [ ] **Step 1: Give .csec-title flex:1 so the drag handle and chevron stay at their edges**

In `claudemon/dashboard/style.css`, replace:

```css
.csec-title {
  font-size: 12px;
  font-weight: 600;
  color: #888;
  text-transform: uppercase;
  letter-spacing: .08em;
}
```

with:

```css
.csec-title {
  flex: 1;
  font-size: 12px;
  font-weight: 600;
  color: #888;
  text-transform: uppercase;
  letter-spacing: .08em;
}
```

- [ ] **Step 2: Add drag handle and drag-state rules**

Append the following block after the `.mcp-fill` rule at the bottom of `claudemon/dashboard/style.css`:

```css
/* ── Drag-to-reorder ───────────────────────────────── */
.drag-handle {
  color: #333;
  cursor: grab;
  user-select: none;
  margin-right: 6px;
  font-size: 14px;
  line-height: 1;
}
.drag-handle:active { cursor: grabbing; }
.csec.dragging { opacity: 0.4; }
.csec.drag-over-top    { border-top:    2px solid #a78bfa; }
.csec.drag-over-bottom { border-bottom: 2px solid #a78bfa; }
```

- [ ] **Step 3: Commit**

```bash
git add claudemon/dashboard/style.css
git commit -m "feat: add drag handle and drag-state CSS"
```

---

### Task 4: Update renderSkills/renderMcp to use max_output_tokens for bar width

**Files:**
- Modify: `claudemon/dashboard/app.js:593-625`

The bar width should be relative to `max_output_tokens` (the metric we now sort by), not `calls`.

- [ ] **Step 1: Update renderSkills**

In `claudemon/dashboard/app.js`, replace the `renderSkills` function:

```javascript
function renderSkills(skills) {
  const el = document.getElementById('skills-list');
  if (!skills.length) {
    el.innerHTML = '<div style="color:#444;font-size:11px;padding:4px 0">No skill usage in this range</div>';
    return;
  }
  const maxTok = skills[0].max_output_tokens;
  el.innerHTML = skills.map(s => {
    const pct = Math.round(s.max_output_tokens / maxTok * 100);
    return `<div class="tool-row">
      <div class="tool-name" title="${esc(s.name)}">${esc(s.name)}</div>
      <div class="tool-bar-wrap"><div class="tool-fill skill-fill" style="width:${pct}%"></div></div>
      <div class="tool-meta">×${s.calls} · ${fmt(s.p50_output_tokens)} 50% / ${fmt(s.max_output_tokens)} max</div>
    </div>`;
  }).join('');
}
```

- [ ] **Step 2: Update renderMcp**

In `claudemon/dashboard/app.js`, replace the `renderMcp` function:

```javascript
function renderMcp(mcp) {
  const el = document.getElementById('mcp-list');
  if (!mcp.length) {
    el.innerHTML = '<div style="color:#444;font-size:11px;padding:4px 0">No MCP usage in this range</div>';
    return;
  }
  const maxTok = mcp[0].max_output_tokens;
  el.innerHTML = mcp.map(m => {
    const pct = Math.round(m.max_output_tokens / maxTok * 100);
    return `<div class="tool-row">
      <div class="tool-name" title="${esc(m.name)}">${esc(m.name)}</div>
      <div class="tool-bar-wrap"><div class="tool-fill mcp-fill" style="width:${pct}%"></div></div>
      <div class="tool-meta">×${m.calls} · ${fmt(m.p50_output_tokens)} 50% / ${fmt(m.max_output_tokens)} max</div>
    </div>`;
  }).join('');
}
```

- [ ] **Step 3: Commit**

```bash
git add claudemon/dashboard/app.js
git commit -m "feat: sort skill/MCP bars by max output tokens"
```

---

### Task 5: Add collapse state persistence to app.js

**Files:**
- Modify: `claudemon/dashboard/app.js`

- [ ] **Step 1: Add _stateRestored flag and saveCollapseState function**

In `claudemon/dashboard/app.js`, find:

```javascript
let currentRange = '7d';
```

Replace with:

```javascript
let currentRange = '7d';
let _stateRestored = false;

function saveCollapseState() {
  const state = {};
  document.querySelectorAll('.csec[data-section-id]').forEach(el => {
    state[el.dataset.sectionId] = el.classList.contains('open');
  });
  fetch('/api/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ section_collapse_state: state }),
  });
}
```

- [ ] **Step 2: Update initCollapsibles to save state on toggle**

Replace the `initCollapsibles` function:

```javascript
function initCollapsibles() {
  document.querySelectorAll('.csec-hdr').forEach(hdr => {
    hdr.addEventListener('click', () => {
      hdr.closest('.csec').classList.toggle('open');
      saveCollapseState();
    });
  });
}
```

- [ ] **Step 3: Commit**

```bash
git add claudemon/dashboard/app.js
git commit -m "feat: persist section collapse state to config on toggle"
```

---

### Task 6: Add section order persistence functions to app.js

**Files:**
- Modify: `claudemon/dashboard/app.js`

- [ ] **Step 1: Add saveSectionOrder and applySectionOrder after saveCollapseState**

In `claudemon/dashboard/app.js`, find the end of `saveCollapseState` (closing `}`) and add the following two functions immediately after:

```javascript
function saveSectionOrder() {
  const order = [...document.querySelectorAll('.csec[data-section-id]')]
    .map(el => el.dataset.sectionId);
  fetch('/api/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ section_order: order }),
  });
}

function applySectionOrder(order) {
  if (!order || !order.length) return;
  const footer = document.querySelector('footer');
  const map = {};
  document.querySelectorAll('.csec[data-section-id]').forEach(el => {
    map[el.dataset.sectionId] = el;
  });
  const seen = new Set();
  order.forEach(id => {
    if (map[id]) { footer.before(map[id]); seen.add(id); }
  });
  // Append sections not present in the saved order (forward-compatibility).
  Object.entries(map).forEach(([id, el]) => {
    if (!seen.has(id)) footer.before(el);
  });
}
```

- [ ] **Step 2: Commit**

```bash
git add claudemon/dashboard/app.js
git commit -m "feat: add saveSectionOrder and applySectionOrder"
```

---

### Task 7: Restore section order and collapse state on first refresh()

**Files:**
- Modify: `claudemon/dashboard/app.js:629-655`

- [ ] **Step 1: Add state restoration block to refresh()**

In `claudemon/dashboard/app.js`, find the `refresh` function and replace it:

```javascript
async function refresh() {
  const [stats, timeline, tasks, queriesData, sessions, config, tools] = await Promise.all([
    api.stats(currentRange),
    api.timeline(currentRange),
    api.tasks(currentRange),
    api.queries(currentRange),
    api.sessions(currentRange),
    api.config(),
    api.tools(currentRange),
  ]);

  if (!_stateRestored) {
    applySectionOrder(config.section_order);
    if (config.section_collapse_state) {
      document.querySelectorAll('.csec[data-section-id]').forEach(el => {
        const id = el.dataset.sectionId;
        if (id in config.section_collapse_state) {
          el.classList.toggle('open', config.section_collapse_state[id]);
        }
      });
    }
    _stateRestored = true;
  }

  setViewMode(currentRange);
  renderStats(stats);

  if (isHourBucket(currentRange)) {
    renderTodaySummary(stats, currentRange);
  }
  renderTokenChart(timeline, currentRange);
  renderTaskChart(tasks, currentRange);
  renderQueryChart(queriesData, currentRange);

  renderModels(stats);
  renderSessions(sessions);
  renderFooter(stats, config);
  renderSkills(tools.skills);
  renderMcp(tools.mcp);
}
```

- [ ] **Step 2: Run lint**

```bash
just lint
```

Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add claudemon/dashboard/app.js
git commit -m "feat: restore section order and collapse state on first refresh"
```

---

### Task 8: Add drag-to-reorder (initDragDrop) to app.js

**Files:**
- Modify: `claudemon/dashboard/app.js`

- [ ] **Step 1: Add initDragDrop function**

In `claudemon/dashboard/app.js`, find `function initCollapsibles()` and add the following function **before** it:

```javascript
function initDragDrop() {
  let dragSrc = null;
  let fromHandle = false;

  document.addEventListener('mouseup', () => { fromHandle = false; }, { passive: true });

  document.querySelectorAll('.csec').forEach(el => {
    const handle = el.querySelector('.drag-handle');
    if (!handle) return;

    handle.addEventListener('mousedown', () => { fromHandle = true; });
    el.setAttribute('draggable', 'true');

    el.addEventListener('dragstart', e => {
      if (!fromHandle) { e.preventDefault(); return; }
      dragSrc = el;
      el.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
    });

    el.addEventListener('dragend', () => {
      fromHandle = false;
      el.classList.remove('dragging');
      document.querySelectorAll('.csec').forEach(s => {
        s.classList.remove('drag-over-top', 'drag-over-bottom');
      });
      dragSrc = null;
      saveSectionOrder();
    });

    el.addEventListener('dragover', e => {
      if (!dragSrc || dragSrc === el) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      const rect = el.getBoundingClientRect();
      const isTop = e.clientY < rect.top + rect.height / 2;
      el.classList.toggle('drag-over-top', isTop);
      el.classList.toggle('drag-over-bottom', !isTop);
    });

    el.addEventListener('dragleave', e => {
      if (!el.contains(e.relatedTarget)) {
        el.classList.remove('drag-over-top', 'drag-over-bottom');
      }
    });

    el.addEventListener('drop', e => {
      e.preventDefault();
      if (!dragSrc || dragSrc === el) return;
      const rect = el.getBoundingClientRect();
      if (e.clientY < rect.top + rect.height / 2) {
        el.before(dragSrc);
      } else {
        el.after(dragSrc);
      }
      el.classList.remove('drag-over-top', 'drag-over-bottom');
    });
  });
}
```

- [ ] **Step 2: Wire initDragDrop in DOMContentLoaded**

In `claudemon/dashboard/app.js`, find:

```javascript
  initCharts();
  initCollapsibles();
  refresh();
```

Replace with:

```javascript
  initCharts();
  initCollapsibles();
  initDragDrop();
  refresh();
```

- [ ] **Step 3: Run full test suite and lint**

```bash
just test && just lint
```

Expected: all tests pass, lint clean.

- [ ] **Step 4: Commit**

```bash
git add claudemon/dashboard/app.js
git commit -m "feat: drag-to-reorder collapsible sections with order persistence"
```

---

## Manual Verification Checklist

After all tasks are complete, launch the app and verify:

1. **Sort order** — Open Skills Used or MCP Tools panel; item with highest `max` token count appears first.
2. **Collapse persistence** — Collapse some sections, quit the app, relaunch; same sections are collapsed.
3. **Order persistence** — Drag "Model breakdown" above "Recent sessions", quit, relaunch; order persists.
4. **Drag feedback** — Dragging a section shows reduced opacity on the dragged element and a purple border on the drop target.
5. **Collapse still works** — Clicking the section title (not the drag handle) still toggles open/closed.
6. **Drag only from handle** — Clicking text inside the section body doesn't accidentally start a drag.
