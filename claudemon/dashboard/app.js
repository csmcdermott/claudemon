const PALETTE = [
  'rgba(167,139,250,0.82)', 'rgba(56,189,248,0.82)',  'rgba(52,211,153,0.82)',
  'rgba(251,146,60,0.82)',  'rgba(251,191,36,0.82)',  'rgba(232,121,249,0.82)',
  'rgba(99,202,183,0.82)',  'rgba(253,164,175,0.82)', 'rgba(129,140,248,0.82)',
  'rgba(74,222,128,0.82)',  'rgba(250,204,21,0.82)',  'rgba(217,119,6,0.82)',
  'rgba(168,85,247,0.82)',  'rgba(14,165,233,0.82)',
];

const COLOR_CLASSES = ['usage-green', 'usage-yellow', 'usage-orange', 'usage-red'];

// Captured from the initial DOM on first load so the success path can rebuild
// the bar elements after the error path replaces them.
let _usageStripHTML = '';

const CHART_DEFAULTS = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: { legend: { display: false }, tooltip: {
    backgroundColor: '#1c1c28',
    borderColor: 'rgba(255,255,255,0.1)', borderWidth: 1,
    titleColor: '#888', bodyColor: '#ddd', padding: 8,
  }},
};

const SCALE_LEFT = {
  position: 'left',
  grid: { color: 'rgba(255,255,255,0.04)' },
  ticks: { color: '#555', font: { size: 9 },
    callback: v => v >= 1e6 ? (v/1e6).toFixed(0)+'M' : v >= 1e3 ? (v/1e3).toFixed(0)+'k' : v },
  border: { display: false },
};
const SCALE_RIGHT = (color, fmt) => ({
  position: 'right',
  grid: { drawOnChartArea: false },
  ticks: { color, font: { size: 9 }, callback: fmt },
  border: { display: false },
});
const SCALE_X = {
  type: 'category',
  grid: { display: false },
  ticks: { color: '#555', font: { size: 9 } },
  border: { display: false },
};

// HTML-escape server-supplied strings before interpolating into innerHTML templates.
// Required for any value that can flow from JSONL into the dashboard — notably
// `s.project` (cwd directory name) and `s.title` (AI-generated title).
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({
  '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;',
}[c]));

function fmt(n) {
  if (n >= 1e9) return (n/1e9).toFixed(1)+'B';
  if (n >= 1e6) return (n/1e6).toFixed(1)+'M';
  if (n >= 1e3) return (n/1e3).toFixed(0)+'k';
  return String(n);
}

function fmtDuration(ms) {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  const h = Math.floor(m / 60);
  if (h > 0) return `${h}h ${m % 60}m`;
  if (m > 0) return `${m}m`;
  return `${s}s`;
}

function fmtResetsAt(isoStr) {
  const d = new Date(isoStr);
  if (isNaN(d)) return '';
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
  if (!strip) return;
  if (!data.available) {
    const err = document.createElement('div');
    err.className = 'usage-error';
    err.textContent = `⚠ ${data.error ?? 'Rate limits unavailable'}`;
    strip.replaceChildren(err);
    return;
  }
  // Restore bar structure if a prior error replaced it
  if (!document.getElementById('usage-5h-pct')) {
    strip.innerHTML = _usageStripHTML;
  }

  function updateBar(pctElId, fillElId, resetElId, trackElId, label, bucket) {
    const pctEl   = document.getElementById(pctElId);
    const fillEl  = document.getElementById(fillElId);
    const resetEl = document.getElementById(resetElId);
    const trackEl = document.getElementById(trackElId);
    if (!pctEl || !fillEl || !resetEl || !trackEl) return;
    if (!bucket || bucket.utilization == null) {
      pctEl.textContent = '—';
      fillEl.style.width = '0%';
      fillEl.className = 'usage-fill';
      pctEl.className = 'usage-pct';
      resetEl.textContent = '';
      trackEl.removeAttribute('title');
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
    trackEl.title = `${pct}% of ${label} used`;
  }

  updateBar('usage-5h-pct', 'usage-5h-fill', 'usage-5h-reset', 'usage-5h-track', '5-hour session', data.five_hour);
  updateBar('usage-7d-pct', 'usage-7d-fill', 'usage-7d-reset', 'usage-7d-track', '7-day weekly', data.seven_day);
}

async function fetchUsage() {
  try {
    const data = await fetch('/api/usage').then(r => r.json());
    renderUsageStrip(data);
  } catch (_) {
    const strip = document.getElementById('usage-strip');
    if (!strip) return;
    const div = document.createElement('div');
    div.className = 'usage-error';
    div.textContent = '⚠ Could not reach local server';
    strip.replaceChildren(div);
  }
}

function toDatetimeLocal(d) {
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:00`;
}

function updateCustomTabLabel() {
  const btn = document.getElementById('custom-tab');
  if (!currentRange.startsWith('custom:')) {
    btn.textContent = 'Custom';
    return;
  }
  const parts = currentRange.split(':');
  const startMs = parseInt(parts[1]);
  const endMs = parseInt(parts[2]);
  const start = new Date(startMs);
  const end = new Date(endMs);
  if (endMs - startMs <= 24 * 3_600_000) {
    const date = start.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    const s = fmtHour(startMs);
    const e = fmtHour(endMs);
    btn.textContent = `${date} ${s}–${e}`;
  } else {
    const s = start.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    const e = end.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    btn.textContent = `${s}–${e}`;
  }
}

const api = {
  async get(path) {
    const r = await fetch(path);
    return r.json();
  },
  stats(range)    { return api.get(`/api/stats?range=${range}`); },
  timeline(range) { return api.get(`/api/timeline?range=${range}&bucket=${isHourBucket(range) ? '1h' : '1d'}`); },
  tasks(range)    { return api.get(`/api/tasks?range=${range}&bucket=${isHourBucket(range) ? '1h' : '1d'}`); },
  queries(range) {
    return api.get(`/api/queries?range=${range}&bucket=${isHourBucket(range) ? '1h' : '1d'}`);
  },
  sessions(range) { return api.get(`/api/sessions?range=${range}&limit=10`); },
  active()        { return api.get(`/api/sessions?range=all&limit=1&active=true`); },
  config()        { return api.get(`/api/config`); },
};

let tokenChart, queryChart, taskChart;

// Last padded data — used by chart click handlers to resolve a clicked index → timestamp.
let _paddedTimeline = [];
let _paddedTasks = [];
let _paddedQueries = [];

// Drill into a specific day when clicking a bar in a multi-day chart.
function onChartClick(_event, elements) {
  if (!elements.length) return;
  // Only drill when already in a multi-day range, not when already in a day view.
  if (isHourBucket(currentRange)) return;
  const idx = elements[0].index;
  const ts = _paddedTimeline[idx]?.date ?? _paddedTasks[idx]?.date ?? _paddedQueries[idx]?.date;
  if (ts == null) return;
  currentRange = `day:${ts}`;
  refresh();
}

function initCharts() {
  const clickOpts = { onClick: onChartClick };

  tokenChart = new Chart(document.getElementById('token-chart'), {
    data: { labels: [], datasets: [] },
    options: { ...CHART_DEFAULTS, ...clickOpts, scales: { x: SCALE_X, yLeft: { ...SCALE_LEFT, yAxisID: 'yLeft' }, yRight: { ...SCALE_RIGHT('#34d399', v => v + '%'), yAxisID: 'yRight' } } },
  });

  queryChart = new Chart(document.getElementById('query-chart'), {
    data: { labels: [], datasets: [] },
    options: {
      ...CHART_DEFAULTS, ...clickOpts,
      plugins: { ...CHART_DEFAULTS.plugins, tooltip: {
        ...CHART_DEFAULTS.plugins.tooltip,
        filter: item => item.raw !== null && item.raw !== 0,
        callbacks: {
          title: items => items[0].label,
          label: item => ` ${item.dataset.label}`,
        },
      }},
      scales: {
        x: SCALE_X,
        yLeft: { ...SCALE_LEFT, stacked: true, yAxisID: 'yLeft' },
        yRight: { ...SCALE_RIGHT('#888', v => v >= 1e6 ? (v/1e6).toFixed(1)+'M' : v >= 1e3 ? (v/1e3).toFixed(0)+'k' : v), yAxisID: 'yRight' },
      },
    },
  });

  taskChart = new Chart(document.getElementById('task-chart'), {
    data: { labels: [], datasets: [] },
    options: {
      ...CHART_DEFAULTS, ...clickOpts,
      plugins: { ...CHART_DEFAULTS.plugins, tooltip: {
        ...CHART_DEFAULTS.plugins.tooltip,
        filter: item => item.raw !== null && item.raw !== 0,
      }},
      scales: {
        x: SCALE_X,
        yLeft: { ...SCALE_LEFT, stacked: true, yAxisID: 'yLeft' },
        yRight: { ...SCALE_RIGHT('#888', v => v >= 1e6 ? (v/1e6).toFixed(1)+'M' : v >= 1e3 ? (v/1e3).toFixed(0)+'k' : v), yAxisID: 'yRight' },
      },
    },
  });
}

// ── Label helpers ────────────────────────────────────────────────────────────

function fmtHour(ts) {
  const h = new Date(ts).getHours();
  const h12 = h % 12 || 12;
  return `${h12}${h < 12 ? 'am' : 'pm'}`;
}

function bucketLabel(ts, range, prevTs = null) {
  if (isHourBucket(range)) {
    const timeStr = fmtHour(ts);
    // Show date prefix when crossing midnight into a new calendar day.
    if (prevTs !== null && new Date(prevTs).getDate() !== new Date(ts).getDate()) {
      const d = new Date(ts);
      return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' ' + timeStr;
    }
    return timeStr;
  }
  return String(new Date(ts).getDate());
}

// ── Gap filling ──────────────────────────────────────────────────────────────

function viewBuckets(range) {
  if (range === 'today') {
    const d = new Date(Date.now() - 12 * 3_600_000);
    d.setMinutes(0, 0, 0);
    const first = d.getTime();
    const n = new Date(); n.setMinutes(0, 0, 0);
    const last = n.getTime();
    const out = [];
    for (let ts = first; ts <= last; ts += 3_600_000) out.push(ts);
    return out;
  }
  if (range.startsWith('day:')) {
    const dayStart = parseInt(range.split(':')[1]);
    return Array.from({ length: 24 }, (_, h) => dayStart + h * 3_600_000);
  }
  if (range.startsWith('custom:')) {
    const parts = range.split(':');
    const startMs = parseInt(parts[1]);
    const endMs = parseInt(parts[2]);
    if (endMs - startMs <= 24 * 3_600_000) {
      const d = new Date(startMs); d.setMinutes(0, 0, 0);
      const first = d.getTime();
      const n = new Date(endMs); n.setMinutes(0, 0, 0);
      const last = n.getTime();
      const out = [];
      for (let ts = first; ts <= last; ts += 3_600_000) out.push(ts);
      return out;
    } else {
      const d = new Date(startMs); d.setHours(0, 0, 0, 0);
      const n = new Date(endMs); n.setHours(0, 0, 0, 0);
      const out = [];
      for (let ts = d.getTime(); ts <= n.getTime(); ts += 86_400_000) out.push(ts);
      return out;
    }
  }
  return [];
}

// Empty-bucket factories — return a fresh stub each call so callers can
// freely mutate nested arrays without leaking state across buckets.
const TIMELINE_EMPTY = () => ({
  input_tokens: 0, output_tokens: 0, cache_hit_rate: 0, queries: 0, tokens_per_query: 0,
});
const TASKS_EMPTY = () => ({
  tasks: [], avg_tokens_per_task: 0, p50_tokens_per_task: 0, max_tokens_per_task: 0,
});
const QUERIES_EMPTY = () => ({
  queries: [], other_count: 0, other_tokens: 0, p50_tpq: 0, max_tpq: 0,
});

function padBuckets(data, range, makeEmpty) {
  const map = new Map(data.map(b => [b.date, b]));
  const mk = ts => map.get(ts) ?? { date: ts, ...makeEmpty() };
  if (isHourBucket(range) || range.startsWith('custom:')) {
    return viewBuckets(range).map(mk);
  }
  const days = range === '30d' ? 30 : range === '7d' ? 7 : null;
  if (!days) return data;
  const now = new Date();
  return Array.from({ length: days }, (_, i) => {
    const d = new Date(now);
    d.setDate(d.getDate() - (days - 1 - i));
    d.setHours(0, 0, 0, 0);
    return mk(d.getTime());
  });
}

// ── View mode ────────────────────────────────────────────────────────────────

function isHourBucket(range) {
  if (range === 'today' || range.startsWith('day:')) return true;
  if (range.startsWith('custom:')) {
    const parts = range.split(':');
    return (parseInt(parts[2]) - parseInt(parts[1])) <= 24 * 3_600_000;
  }
  return false;
}

function setViewMode(range) {
  document.getElementById('today-summary').classList.toggle('hidden', !isHourBucket(range));
}

// ── Renderers ────────────────────────────────────────────────────────────────

function renderStats(stats) {
  document.getElementById('stat-sessions').textContent = stats.sessions;
  document.getElementById('stat-input').textContent    = fmt(stats.input_tokens);
  document.getElementById('stat-output').textContent   = fmt(stats.output_tokens);
  document.getElementById('stat-cache').textContent    = stats.cache_hit_rate + '%';
}

function renderTodaySummary(stats, range) {
  document.getElementById('today-tasks').textContent   = stats.tasks;
  document.getElementById('today-queries').textContent = stats.queries;
  document.getElementById('today-tpq').textContent     = fmt(stats.tokens_per_query);
  document.getElementById('today-tpt').textContent     = fmt(stats.tokens_per_task);

  const lbl = document.getElementById('today-date-label');
  if (range.startsWith('day:')) {
    const ts = parseInt(range.split(':')[1]);
    lbl.textContent = new Date(ts).toLocaleDateString(undefined,
      { weekday: 'long', month: 'long', day: 'numeric' });
    lbl.classList.remove('hidden');
  } else {
    lbl.classList.add('hidden');
  }
}

function renderTokenChart(timeline, range) {
  const padded = padBuckets(timeline, range, TIMELINE_EMPTY);
  _paddedTimeline = padded;
  tokenChart.data.labels = padded.map((b, i) => bucketLabel(b.date, range, i > 0 ? padded[i - 1].date : null));
  tokenChart.data.datasets = [
    { type: 'bar', label: 'Output', data: padded.map(b => b.output_tokens),
      backgroundColor: 'rgba(167,139,250,0.65)', borderRadius: 3, borderSkipped: false, yAxisID: 'yLeft', order: 2 },
    { type: 'bar', label: 'Input',  data: padded.map(b => b.input_tokens),
      backgroundColor: 'rgba(56,189,248,0.65)',  borderRadius: 3, borderSkipped: false, yAxisID: 'yLeft', order: 2 },
    { type: 'line', label: 'Cache %', data: padded.map(b => b.cache_hit_rate),
      borderColor: '#34d399', borderWidth: 1.5, pointRadius: 2.5, pointBackgroundColor: '#34d399',
      spanGaps: true, tension: 0.4, yAxisID: 'yRight', order: 1 },
  ];
  tokenChart.update();
}

function renderQueryChart(queriesData, range) {
  const padded = padBuckets(queriesData, range, QUERIES_EMPTY);
  _paddedQueries = padded;
  if (!padded.length) return;

  const labels = padded.map((b, i) => bucketLabel(b.date, range, i > 0 ? padded[i - 1].date : null));
  const maxQ = Math.max(...padded.map(b => b.queries?.length ?? 0), 0);

  const stackDatasets = Array.from({ length: maxQ }, (_, i) => ({
    type: 'bar',
    label: `Query ${i + 1}`,
    queryIndex: i,
    data: padded.map(b => b.queries?.[i]?.total_tokens ?? null),
    backgroundColor: PALETTE[i % PALETTE.length],
    borderColor: 'rgba(0,0,0,0.12)', borderWidth: 0.5,
    borderRadius: i === 0 ? { bottomLeft: 3, bottomRight: 3 } : 0,
    borderSkipped: false, stack: 'queries', yAxisID: 'yLeft', order: 2,
  }));

  const otherDataset = {
    type: 'bar',
    label: 'other',
    data: padded.map(b => b.other_tokens > 0 ? b.other_tokens : null),
    backgroundColor: 'rgba(100,100,120,0.5)',
    borderColor: 'rgba(0,0,0,0.12)', borderWidth: 0.5,
    borderSkipped: false, stack: 'queries', yAxisID: 'yLeft', order: 2,
  };

  queryChart.options.plugins.tooltip.callbacks = {
    title: items => items[0].label,
    label: item => {
      if (item.dataset.label === 'p50 tok') return ` p50: ${fmt(item.raw)}`;
      if (item.dataset.label === 'top tok') return ` max: ${fmt(item.raw)}`;
      if (item.dataset.label === 'other') {
        const b = padded[item.dataIndex];
        return ` +${b.other_count} other: ${fmt(item.raw)} tokens`;
      }
      const b = padded[item.dataIndex];
      const q = b.queries?.[item.dataset.queryIndex];
      return ` ${q?.query_id ?? item.dataset.label}: ${fmt(item.raw)} tokens`;
    },
  };

  const activeBuckets = padded.filter(b => (b.queries?.length ?? 0) > 0).length;
  const hasOther = padded.some(b => b.other_tokens > 0);
  queryChart.data.labels = labels;
  queryChart.data.datasets = [
    ...stackDatasets,
    ...(hasOther ? [otherDataset] : []),
    ...(activeBuckets >= 2 ? [
      {
        type: 'line', label: 'p50 tok',
        data: padded.map(b => b.p50_tpq || null),
        borderColor: '#fcd34d', borderWidth: 1.5, borderDash: [4, 2],
        pointRadius: 2, pointBackgroundColor: '#fcd34d',
        spanGaps: false, tension: 0.4, yAxisID: 'yRight', order: 1,
      },
      {
        type: 'line', label: 'top tok',
        data: padded.map(b => b.max_tpq || null),
        borderColor: '#f87171', borderWidth: 1.5,
        pointRadius: 2, pointBackgroundColor: '#f87171',
        spanGaps: false, tension: 0.4, yAxisID: 'yRight', order: 1,
      },
    ] : []),
  ];
  queryChart.update();
}

function renderTaskChart(tasksData, range) {
  const padded = padBuckets(tasksData, range, TASKS_EMPTY);
  _paddedTasks = padded;
  if (!padded.length) return;
  const labels = padded.map((d, i) => bucketLabel(d.date, range, i > 0 ? padded[i - 1].date : null));
  const maxTasks = Math.max(...padded.map(d => d.tasks.length), 0);

  const stackDatasets = Array.from({ length: maxTasks }, (_, i) => ({
    type: 'bar',
    label: `Task ${i + 1}`,
    data: padded.map(d => d.tasks[i]?.queries ?? null),
    backgroundColor: PALETTE[i % PALETTE.length],
    borderColor: 'rgba(0,0,0,0.12)', borderWidth: 0.5,
    borderRadius: i === 0 ? { bottomLeft: 3, bottomRight: 3 } : 0,
    borderSkipped: false, stack: 'tasks', yAxisID: 'yLeft', order: 2,
  }));

  taskChart.options.plugins.tooltip.callbacks = {
    title: items => items[0].label,
    label: item => {
      if (item.dataset.label === 'p50 tok') return ` p50: ${fmt(item.raw)}`;
      if (item.dataset.label === 'top tok') return ` max: ${fmt(item.raw)}`;
      const task = padded[item.dataIndex]?.tasks[item.datasetIndex];
      const name = task?.label || item.dataset.label;
      const q = item.raw;
      return ` ${name}: ${q} quer${q === 1 ? 'y' : 'ies'}`;
    },
  };

  const activeBuckets = padded.filter(d => d.tasks.length > 0).length;
  taskChart.data.labels = labels;
  taskChart.data.datasets = [
    ...stackDatasets,
    ...(activeBuckets >= 2 ? [
      {
        type: 'line', label: 'p50 tok',
        data: padded.map(d => d.tasks.length ? d.p50_tokens_per_task : null),
        borderColor: '#fcd34d', borderWidth: 1.5, borderDash: [4, 2],
        pointRadius: 2, pointBackgroundColor: '#fcd34d',
        spanGaps: false, tension: 0.4, yAxisID: 'yRight', order: 1,
      },
      {
        type: 'line', label: 'top tok',
        data: padded.map(d => d.tasks.length ? d.max_tokens_per_task : null),
        borderColor: '#f87171', borderWidth: 1.5,
        pointRadius: 2, pointBackgroundColor: '#f87171',
        spanGaps: false, tension: 0.4, yAxisID: 'yRight', order: 1,
      },
    ] : []),
  ];
  taskChart.update();
}

function renderModels(stats) {
  const el = document.getElementById('models-list');
  const total = stats.model_breakdown.reduce((s, m) => s + m.messages, 0) || 1;
  el.innerHTML = stats.model_breakdown.map((m, i) => {
    const pct = Math.round((m.messages / total) * 100);
    const color = PALETTE[i % PALETTE.length];
    const name = m.model.replace('claude-', '').replace(/-\d{8}$/, '');
    return `<div class="model-row">
      <div class="model-name">${esc(name)}</div>
      <div class="model-track"><div class="model-fill" style="width:${pct}%;background:${color}"></div></div>
      <div class="model-toks">${fmt(m.input_tokens)} in / ${fmt(m.output_tokens)} out</div>
    </div>`;
  }).join('');
}

function renderSessions(sessions) {
  const el = document.getElementById('sessions-list');
  if (!sessions.length) {
    el.innerHTML = '<div style="color:#444;font-size:11px;padding:4px 0">No sessions</div>';
    return;
  }
  el.innerHTML = sessions.map(s => {
    const dur = s.ended_at && s.started_at ? fmtDuration(s.ended_at - s.started_at) : 'active';
    return `<div class="s-row">
      <div class="s-dot" style="background:#3a3a4a"></div>
      <div class="s-info">
        <div class="s-title">${esc(s.title || 'Untitled session')}</div>
        <div class="s-proj">${esc(s.project)} · ${dur}</div>
      </div>
      <div class="s-right">
        <div class="s-tokens">${fmt(s.input_tokens)} in / ${fmt(s.output_tokens)} out</div>
        <div class="s-tasks">${s.task_count} task${s.task_count !== 1 ? 's' : ''} · ${s.query_count} queries</div>
      </div>
    </div>`;
  }).join('');
}

function renderBanner(activeSessions) {
  const banner = document.getElementById('banner');
  if (!activeSessions.length) { banner.classList.add('hidden'); return; }
  const s = activeSessions[0];
  banner.classList.remove('hidden');
  document.getElementById('banner-project').textContent = s.project;
  const elapsed = s.started_at ? fmtDuration(Date.now() - s.started_at) : '';
  document.getElementById('banner-meta').textContent =
    `${elapsed} · ${fmt(s.input_tokens)} in / ${fmt(s.output_tokens)} out · ${s.task_count} tasks`;
}

function renderFooter(stats, config) {
  document.getElementById('footer-stat').textContent =
    `${stats.sessions} sessions · ${stats.queries} queries`;
  if (config?._version) {
    document.getElementById('footer-version').textContent = `v${config._version}`;
  }
}

let currentRange = '7d';

async function refresh() {
  const [stats, timeline, tasks, queriesData, sessions, config] = await Promise.all([
    api.stats(currentRange),
    api.timeline(currentRange),
    api.tasks(currentRange),
    api.queries(currentRange),
    api.sessions(currentRange),
    api.config(),
  ]);

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
}

async function refreshBanner() {
  const active = await api.active();
  renderBanner(active);
}

document.addEventListener('DOMContentLoaded', () => {
  _usageStripHTML = document.getElementById('usage-strip').innerHTML;
  initCharts();
  refresh();
  refreshBanner();
  fetchUsage();

  setInterval(refresh, 30_000);
  setInterval(refreshBanner, 5_000);
  setInterval(fetchUsage, 120_000);

  const customTab = document.getElementById('custom-tab');
  const customPicker = document.getElementById('custom-picker');
  customPicker.style.display = 'none';
  const customStart = document.getElementById('custom-start');
  const customEnd = document.getElementById('custom-end');

  customTab.addEventListener('click', () => {
    if (customPicker.style.display !== 'none') {
      customPicker.style.display = 'none';
      return;
    }
    const now = new Date();
    now.setMinutes(0, 0, 0);
    const sevenAgo = new Date(now.getTime() - 7 * 86_400_000);
    sevenAgo.setHours(0, 0, 0, 0);
    customStart.value = toDatetimeLocal(sevenAgo);
    customEnd.value = toDatetimeLocal(now);
    document.getElementById('custom-error').textContent = '';
    customPicker.style.display = 'block';
  });

  document.getElementById('custom-apply').addEventListener('click', () => {
    const start = new Date(customStart.value).getTime();
    const end = new Date(customEnd.value).getTime();
    if (isNaN(start) || isNaN(end) || end <= start) {
      document.getElementById('custom-error').textContent = 'End must be after start';
      return;
    }
    document.getElementById('custom-error').textContent = '';
    currentRange = `custom:${start}:${end}`;
    customPicker.style.display = 'none';
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    customTab.classList.add('active');
    updateCustomTabLabel();
    refresh();
  });

  document.addEventListener('click', e => {
    if (customPicker.style.display === 'none') return;
    if (!customPicker.contains(e.target) && e.target !== customTab) {
      customPicker.style.display = 'none';
    }
  });

  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      if (!tab.dataset.range) return;
      currentRange = tab.dataset.range;
      customPicker.style.display = 'none';
      document.getElementById('custom-tab').textContent = 'Custom';
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      refresh();
    });
  });

  document.getElementById('quit-btn').addEventListener('click', () => {
    fetch('/api/quit', { method: 'POST' }).catch(() => {});
  });
});
