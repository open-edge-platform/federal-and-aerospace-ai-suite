// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0
(() => {
  const COLORS = ['#4da3ff', '#3ecf8e', '#f5a623', '#c58bff', '#ef5b5b'];
  const $ = (id) => document.getElementById(id);
  const state = { includeProcessing: false, cfg: null, series: {}, colorIdx: 0, lastNow: 0, offset: 0, qbvTouched: 0 };

  const chart = new Chart($('chart'), {
    type: 'line',
    data: { datasets: [] },
    options: {
      animation: false, parsing: false, normalized: true, maintainAspectRatio: false,
      interaction: { mode: 'nearest', intersect: false },
      elements: { point: { radius: 0 }, line: { borderWidth: 1.8, tension: 0 } },
      scales: {
        x: { type: 'linear', ticks: { color: '#8b98a7', maxTicksLimit: 8,
               callback: (v) => `${Math.round(v - state.lastNow)} s` },
             grid: { color: '#212b36' } },
        y: { type: 'linear', beginAtZero: true, suggestedMax: 50, title: { display: true, text: 'ms', color: '#8b98a7' },
             ticks: { color: '#8b98a7' }, grid: { color: '#212b36' } },
      },
      plugins: { legend: { labels: { color: '#e6edf3' } },
        tooltip: { callbacks: { label: (c) => { const p = c.raw; const proc = p.proc === null ? '' : `, processing ${p.proc.toFixed(1)}`; return `${c.dataset.label}: network ${p.net.toFixed(1)}${proc} ms`; } } } },
    },
  });

  function series(name) {
    if (!state.series[name]) {
      const color = COLORS[state.colorIdx++ % COLORS.length];
      const ds = { label: name, data: [], borderColor: color, backgroundColor: color };
      chart.data.datasets.push(ds);
      state.series[name] = { ds, color, kpi: makeKpi(name, color) };
    }
    return state.series[name];
  }

  function makeKpi(name, color) {
    const el = document.createElement('div');
    el.className = 'kpi';
    el.style.setProperty('--c', color);
    el.innerHTML = `<div class="kpi-name"><span></span><span class="tag"></span></div>
      <div class="kpi-value">–<small> ms</small></div>
      <div class="kpi-row"><span class="mean"></span><span class="p95"></span><span class="max"></span></div>
      <div class="kpi-row"><span class="proc"></span><span class="rate"></span><span class="gaps"></span></div>`;
    el.querySelector('.kpi-name span').textContent = name;
    $('kpis').appendChild(el);
    return el;
  }

  const fmt = (v) => (v === null || v === undefined ? '–' : v >= 100 ? v.toFixed(0) : v.toFixed(1));

  function renderKpis(sources) {
    for (const [name, s] of Object.entries(sources)) {
      const el = series(name).kpi;
      el.classList.toggle('stalled', s.stalled);
      el.querySelector('.tag').textContent = s.stalled ? 'no data' : '';
      el.querySelector('.tag').className = 'tag' + (s.stalled ? ' tag-stalled' : '');
      el.querySelector('.kpi-value').innerHTML = `${fmt(s.last_ms)}<small> ms</small>`;
      el.querySelector('.mean').textContent = `mean ${fmt(s.mean_ms)}`;
      el.querySelector('.p95').textContent = `p95 ${fmt(s.p95_ms)}`;
      el.querySelector('.max').textContent = `max ${fmt(s.max_ms)}`;
      el.querySelector('.proc').textContent = s.proc_ms === null ? '' : `processing ${fmt(s.proc_ms)} ms`;
      el.querySelector('.rate').textContent = `${s.rate_hz} msg/s`;
      el.querySelector('.gaps').textContent = `missed ${s.gaps}` + (s.rejected ? ` · bad clock ${s.rejected}` : '');
    }
    $('empty').classList.toggle('hidden', Object.keys(sources).length > 0);
  }

  const yOf = (net, proc) => net + (state.includeProcessing && proc !== null ? proc : 0);

  // Server timestamps are used for the x axis; 'offset' hides browser/server clock differences.
  function addPoints(points, historySpan) {
    for (const [name, pts] of Object.entries(points)) {
      const ds = series(name).ds;
      for (const [t, net, proc] of pts) ds.data.push({ x: t, net, proc, y: yOf(net, proc) });
      const cutoff = state.lastNow - historySpan;
      while (ds.data.length && ds.data[0].x < cutoff) ds.data.shift();
    }
  }

  function render(now) {
    state.lastNow = now;
    chart.options.scales.x.min = now - state.cfg.history_s / 2;
    chart.options.scales.x.max = now;
    chart.update('none');
  }

  function renderControls(msg) {
    const mq = $('chip-mqtt');
    mq.textContent = msg.mqtt_connected ? 'MQTT: connected' : 'MQTT: disconnected';
    mq.className = 'chip ' + (msg.mqtt_connected ? 'chip-ok' : 'chip-bad');

    const t = msg.traffic;
    if (!state.draggingTraffic) {
      $('traffic').value = t.rate_mbps;
      $('traffic-value').textContent = `${t.rate_mbps} Mbit/s`;
    }
    const ms = t.measured;
    $('traffic-measured').textContent = ms
      ? `Arriving at machine-1: ${ms.mbps.toFixed(0)} Mbit/s, loss ${ms.loss_pct.toFixed(1)} %`
      : (t.running && t.mode === 'iperf' ? 'Waiting for the iperf3 receiver…' : '');
    const tm = $('traffic-msg');
    tm.textContent = t.error || (t.rate_mbps > 0 && !t.running ? 'Load stopped unexpectedly' : '');
    tm.classList.toggle('hidden', !tm.textContent);

    const q = msg.qbv;
    $('qbv-port').textContent = `port ${q.port}`;
    if (Date.now() - state.qbvTouched > 1500) $('qbv').checked = q.enabled;
    $('qbv').disabled = q.busy || q.read_only;
    $('qbv-label').textContent = q.busy ? 'Applying…' : q.enabled ? 'On' : 'Off';
    const qm = $('qbv-msg');
    qm.textContent = q.error || (q.read_only ? 'Read-only: switch changes are disabled' : '');
    qm.classList.toggle('hidden', !qm.textContent);
    const sched = (q.slots || []).map((sl) => `${sl.interval_us / 1000} ms: Q${sl.queues.join(',')}`).join('  |  ');
    $('qbv-schedule').textContent = q.enabled && sched ? `Schedule: ${sched}` : '';

    const mode = $('chip-mode');
    const simulated = [t.mode === 'sim' && 'load', q.mode === 'sim' && 'switch'].filter(Boolean);
    mode.textContent = simulated.length ? `simulated: ${simulated.join(' + ')}` : '';
    mode.classList.toggle('hidden', !simulated.length);
  }

  let trafficTimer;
  $('traffic').addEventListener('input', (e) => {
    state.draggingTraffic = true;
    $('traffic-value').textContent = `${e.target.value} Mbit/s`;
    clearTimeout(trafficTimer);
    trafficTimer = setTimeout(async () => {
      await post('/api/traffic', { rate_mbps: Number(e.target.value) });
      state.draggingTraffic = false;
    }, 300);
  });

  $('qbv').addEventListener('change', async (e) => {
    state.qbvTouched = Date.now();
    const r = await post('/api/qbv', { enabled: e.target.checked });
    if (!r.ok) {
      const m = $('qbv-msg');
      m.textContent = (await r.json()).detail || 'Request failed';
      m.classList.remove('hidden');
      e.target.checked = !e.target.checked;
    }
  });

  $('log-scale').addEventListener('change', (e) => {
    const y = chart.options.scales.y;
    y.type = e.target.checked ? 'logarithmic' : 'linear';
    y.beginAtZero = !e.target.checked;
    y.min = e.target.checked ? 1 : undefined;
    chart.update('none');
  });

  $('include-proc').addEventListener('change', (e) => {
    state.includeProcessing = e.target.checked;
    for (const sr of Object.values(state.series)) for (const p of sr.ds.data) p.y = yOf(p.net, p.proc);
    chart.update('none');
  });

  $('clear').addEventListener('click', async () => {
    await post('/api/reset', {});
    for (const s of Object.values(state.series)) s.ds.data.length = 0;
    chart.update('none');
  });

  function post(url, body) {
    return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  }

  async function start() {
    state.cfg = await (await fetch('/api/config')).json();
    $('traffic').max = state.cfg.traffic_max_mbps;
    const hist = await (await fetch('/api/history')).json();
    state.lastNow = hist.now;
    addPoints(hist.points, state.cfg.history_s);
    const es = new EventSource('/api/stream');
    es.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      state.lastNow = msg.now;
      addPoints(msg.points, state.cfg.history_s);
      renderKpis(msg.sources);
      renderControls(msg);
      render(msg.now);
    };
    es.onerror = () => {
      $('chip-mqtt').textContent = 'Backend: reconnecting';
      $('chip-mqtt').className = 'chip chip-bad';
    };
  }
  start();
})();
