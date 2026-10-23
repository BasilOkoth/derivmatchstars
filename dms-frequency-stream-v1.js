
/* DigitMatchStar Frequency + V1 Shadow Study v4
   Public Deriv market-data connection, independent of account or trade controls.
   No trading endpoints or authorization tokens are used.
*/
(() => {
  'use strict';
  if (window.DMSFrequencyStudy) return;

  const appId = String(window.DMS_RESEARCH_APP_ID || '1089');
  const MAX = 1000;
  const ENDPOINTS = [
    'wss://api.derivws.com/trading/v1/options/ws/public',
    `wss://ws.derivws.com/websockets/v3?app_id=${encodeURIComponent(appId)}`
  ];

  const S = {
    symbol: 'R_10', socket: null, subscription: null, prices: [], seen: new Set(),
    last: null, seq: 0, pending: null, block: null, rows: [], forecasts: [], rejected: 0,
    connected: false, ready: false, generation: 0, timer: null, html: null, status: 'connecting',
    snapshotMatched: 0, snapshotUnavailable: 0, gapCount: 0, liveTicks: 0, lastLiveAt: 0,
    reconnects: 0, endpointIndex: 0, lastError: '', gotHistory: false, gotLive: false
  };

  const digit = v => Number.isInteger(+v) && +v >= 0 && +v <= 9 ? +v : null;
  const symbol = () => String(document.querySelector('#symbol')?.value || 'R_10');
  const key = t => `${S.symbol}|${t.epoch}|${t.quote}|${t.digit}`;
  const pct = n => (Number.isFinite(n) ? `${n.toFixed(1)}%` : '—%');

  function installStyles() {
    if (document.getElementById('dms-fs-style')) return;
    const style = document.createElement('style');
    style.id = 'dms-fs-style';
    style.textContent = `
      #dms-frequency-study{font-family:Inter,system-ui,sans-serif;width:100%;margin:14px 0 0;padding:14px;border:1px solid rgba(71,85,105,.9);border-radius:16px;background:linear-gradient(180deg,rgba(15,23,42,.98),rgba(2,6,23,.98));color:#f8fafc;box-sizing:border-box;box-shadow:0 14px 32px rgba(0,0,0,.24), inset 0 1px 0 rgba(255,255,255,.04)}
      #dms-frequency-study .dms-fs-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap;margin-bottom:8px}
      #dms-frequency-study .dms-fs-title{font-size:15px;font-weight:900;letter-spacing:.01em;color:#e2e8f0}
      #dms-frequency-study .dms-fs-sub{margin:4px 0 0;color:#94a3b8;font-size:12px;line-height:1.35}
      #dms-frequency-study .dms-fs-status{display:inline-flex;align-items:center;gap:8px;padding:7px 10px;border-radius:999px;font-size:11px;font-weight:900;letter-spacing:.03em;border:1px solid rgba(148,163,184,.18);text-transform:uppercase;white-space:nowrap}
      #dms-frequency-study .dms-fs-status::before{content:'';width:8px;height:8px;border-radius:999px;background:#94a3b8;box-shadow:0 0 0 4px rgba(148,163,184,.18)}
      #dms-frequency-study .status-streaming{background:rgba(5,150,105,.12);color:#6ee7b7;border-color:rgba(16,185,129,.28)}
      #dms-frequency-study .status-streaming::before{background:#10b981;box-shadow:0 0 0 4px rgba(16,185,129,.18)}
      #dms-frequency-study .status-connecting,#dms-frequency-study .status-reconnecting,#dms-frequency-study .status-stale{background:rgba(245,158,11,.10);color:#fbbf24;border-color:rgba(245,158,11,.25)}
      #dms-frequency-study .status-connecting::before,#dms-frequency-study .status-reconnecting::before,#dms-frequency-study .status-stale::before{background:#f59e0b;box-shadow:0 0 0 4px rgba(245,158,11,.16)}
      #dms-frequency-study .status-error,#dms-frequency-study .status-closed,#dms-frequency-study .status-api{background:rgba(239,68,68,.10);color:#fca5a5;border-color:rgba(239,68,68,.24)}
      #dms-frequency-study .status-error::before,#dms-frequency-study .status-closed::before,#dms-frequency-study .status-api::before{background:#ef4444;box-shadow:0 0 0 4px rgba(239,68,68,.16)}
      #dms-frequency-study .status-idle{background:rgba(56,189,248,.10);color:#93c5fd;border-color:rgba(56,189,248,.22)}
      #dms-frequency-study .status-idle::before{background:#60a5fa;box-shadow:0 0 0 4px rgba(96,165,250,.15)}
      #dms-frequency-study .dms-fs-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;margin-top:12px}
      @media (max-width:900px){#dms-frequency-study .dms-fs-grid{grid-template-columns:repeat(5,minmax(0,1fr));}}
      @media (max-width:640px){#dms-frequency-study .dms-fs-grid{grid-template-columns:repeat(2,minmax(0,1fr));}}
      #dms-frequency-study .dms-fs-card{position:relative;overflow:hidden;padding:10px;border-radius:14px;border:1px solid rgba(71,85,105,.55);background:linear-gradient(180deg,rgba(30,41,59,.75),rgba(15,23,42,.85));transition:transform .12s ease,border-color .15s ease,box-shadow .15s ease}
      #dms-frequency-study .dms-fs-card:hover{transform:translateY(-1px);box-shadow:0 8px 18px rgba(0,0,0,.22)}
      #dms-frequency-study .dms-fs-card-top{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px}
      #dms-frequency-study .dms-fs-digit{display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:999px;font-size:13px;font-weight:900;background:rgba(15,23,42,.9);border:1px solid rgba(148,163,184,.2);color:#f8fafc}
      #dms-frequency-study .dms-fs-pct{font-size:18px;font-weight:900;letter-spacing:-.02em}
      #dms-frequency-study .dms-fs-count{font-size:11px;color:#cbd5e1}
      #dms-frequency-study .dms-fs-track{height:8px;border-radius:999px;background:rgba(51,65,85,.9);overflow:hidden;border:1px solid rgba(148,163,184,.08)}
      #dms-frequency-study .dms-fs-fill{height:100%;border-radius:999px;min-width:2px}
      #dms-frequency-study .dms-fs-rank{margin-top:6px;font-size:10px;font-weight:800;letter-spacing:.03em;text-transform:uppercase;color:#94a3b8}
      #dms-frequency-study .tier-top{border-color:rgba(16,185,129,.38);background:linear-gradient(180deg,rgba(6,78,59,.33),rgba(15,23,42,.92))}
      #dms-frequency-study .tier-top .dms-fs-pct{color:#6ee7b7}
      #dms-frequency-study .tier-top .dms-fs-fill{background:linear-gradient(90deg,#10b981,#34d399)}
      #dms-frequency-study .tier-high{border-color:rgba(34,197,94,.26)}
      #dms-frequency-study .tier-high .dms-fs-pct{color:#a7f3d0}
      #dms-frequency-study .tier-high .dms-fs-fill{background:linear-gradient(90deg,#22c55e,#86efac)}
      #dms-frequency-study .tier-mid{border-color:rgba(59,130,246,.24)}
      #dms-frequency-study .tier-mid .dms-fs-pct{color:#bfdbfe}
      #dms-frequency-study .tier-mid .dms-fs-fill{background:linear-gradient(90deg,#3b82f6,#60a5fa)}
      #dms-frequency-study .tier-low{border-color:rgba(245,158,11,.22)}
      #dms-frequency-study .tier-low .dms-fs-pct{color:#fde68a}
      #dms-frequency-study .tier-low .dms-fs-fill{background:linear-gradient(90deg,#f59e0b,#fbbf24)}
      #dms-frequency-study .tier-weak{border-color:rgba(239,68,68,.22)}
      #dms-frequency-study .tier-weak .dms-fs-pct{color:#fca5a5}
      #dms-frequency-study .tier-weak .dms-fs-fill{background:linear-gradient(90deg,#ef4444,#fb7185)}
      #dms-frequency-study .dms-fs-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-top:12px}
      @media (max-width:640px){#dms-frequency-study .dms-fs-metrics{grid-template-columns:repeat(2,minmax(0,1fr));}}
      #dms-frequency-study .dms-fs-metric{padding:10px 11px;border-radius:12px;background:rgba(15,23,42,.88);border:1px solid rgba(71,85,105,.6)}
      #dms-frequency-study .dms-fs-metric-label{font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.04em;color:#94a3b8}
      #dms-frequency-study .dms-fs-metric-value{margin-top:3px;font-size:16px;font-weight:900;color:#f8fafc}
      #dms-frequency-study .dms-fs-foot{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-top:12px}
      #dms-frequency-study .dms-fs-note{font-size:11px;color:#94a3b8;line-height:1.35;flex:1 1 320px}
      #dms-frequency-study .dms-fs-export{padding:9px 12px;border:0;border-radius:10px;background:linear-gradient(135deg,#2563eb,#1d4ed8);color:white;font-weight:900;font-size:12px;box-shadow:0 8px 16px rgba(37,99,235,.18);cursor:pointer}
      #dms-frequency-study .dms-fs-export:hover{filter:brightness(1.05)}
      #dms-frequency-study .dms-fs-error{margin-top:8px;font-size:11px;color:#fca5a5;min-height:15px}
    `;
    document.head.appendChild(style);
  }

  function statusClass(text) {
    const s = String(text || '').toLowerCase();
    if (s.includes('streaming')) return 'status-streaming';
    if (s.includes('reconnecting')) return 'status-reconnecting';
    if (s.includes('connecting') || s.includes('subscribing') || s.includes('waiting')) return 'status-connecting';
    if (s.includes('stale')) return 'status-stale';
    if (s.includes('websocket error')) return 'status-error';
    if (s.includes('api')) return 'status-api';
    if (s.includes('closed')) return 'status-closed';
    return 'status-idle';
  }

  function ensurePanel() {
    installStyles();
    if (S.html?.isConnected) return;
    const host = document.createElement('section');
    host.id = 'dms-frequency-study';
    host.innerHTML = `
      <div class="dms-fs-head">
        <div>
          <div class="dms-fs-title">Market stream & frequency research</div>
          <p class="dms-fs-sub">Independent research feed · read-only · no purchases. Historical frequencies are descriptive, not a promise about the next tick.</p>
        </div>
        <span id="dms-fs-status" class="dms-fs-status status-connecting">CONNECTING · R_10</span>
      </div>
      <div id="dms-fs-grid" class="dms-fs-grid"></div>
      <div id="dms-fs-metrics" class="dms-fs-metrics"></div>
      <div id="dms-fs-error" class="dms-fs-error"></div>
      <div class="dms-fs-foot">
        <div id="dms-fs-note" class="dms-fs-note">Waiting for historical ticks and live streaming data.</div>
        <button type="button" id="dms-fs-export" class="dms-fs-export">Export shadow CSV</button>
      </div>`;
    const market = document.getElementById('market_status');
    const container = market?.closest('.bg-gray-900.border') || document.querySelector('.lg\\:col-span-1');
    if (container) container.appendChild(host); else document.body.prepend(host);
    host.querySelector('#dms-fs-export').addEventListener('click', exportCsv);
    S.html = host;
    render();
  }

  function classify(value, maxValue) {
    if (!Number.isFinite(value)) return 'tier-mid';
    if (value === maxValue) return 'tier-top';
    if (value >= 11.0) return 'tier-high';
    if (value >= 9.5) return 'tier-mid';
    if (value >= 8.8) return 'tier-low';
    return 'tier-weak';
  }

  function render() {
    ensurePanel();
    const counts = Array(10).fill(0);
    for (const item of S.prices) counts[item.digit]++;
    const n = S.prices.length;
    if (S.connected && S.lastLiveAt && Date.now() - S.lastLiveAt > 10000) S.status = 'stale: no new ticks';
    const values = counts.map(c => n ? (100 * c / n) : NaN);
    const maxValue = values.reduce((m, v) => Number.isFinite(v) && v > m ? v : m, -Infinity);
    const ranked = values.map((v, d) => ({ d, v })).sort((a, b) => (b.v - a.v) || (a.d - b.d));
    const rankMap = new Map(ranked.map((row, idx) => [row.d, idx + 1]));

    const statusEl = S.html.querySelector('#dms-fs-status');
    statusEl.className = `dms-fs-status ${statusClass(S.status)}`;
    statusEl.textContent = `${S.status.toUpperCase()} · ${S.symbol}`;

    const grid = S.html.querySelector('#dms-fs-grid');
    grid.innerHTML = values.map((v, d) => {
      const tier = classify(v, maxValue);
      const count = counts[d];
      const width = Number.isFinite(v) ? Math.max(4, Math.min(100, v * 6.5)) : 4;
      const leader = rankMap.get(d) === 1 ? 'Highest frequency now' : `Rank #${rankMap.get(d)}`;
      return `
        <div class="dms-fs-card ${tier}">
          <div class="dms-fs-card-top">
            <span class="dms-fs-digit">${d}</span>
            <span class="dms-fs-pct">${pct(v)}</span>
          </div>
          <div class="dms-fs-count">${count}/${n || 1000} ticks</div>
          <div class="dms-fs-track"><div class="dms-fs-fill" style="width:${width}%"></div></div>
          <div class="dms-fs-rank">${leader}</div>
        </div>`;
    }).join('');

    const metrics = [
      ['Ticks in window', `${n}/${MAX}`],
      ['New live ticks', String(S.liveTicks)],
      ['Duplicate drops', String(S.rejected)],
      ['Blocks tested', String(S.forecasts.length)],
      ['Aligned V1', String(S.snapshotMatched)],
      ['Unavailable V1', String(S.snapshotUnavailable)],
      ['Observed gaps', String(S.gapCount)],
      ['Reconnects', String(S.reconnects)]
    ];
    S.html.querySelector('#dms-fs-metrics').innerHTML = metrics.map(([label, value]) => `
      <div class="dms-fs-metric">
        <div class="dms-fs-metric-label">${label}</div>
        <div class="dms-fs-metric-value">${value}</div>
      </div>`).join('');

    const top = ranked.slice(0, 3).map((r, idx) => `${idx + 1}) digit ${r.d} ${pct(r.v)}`).join(' · ');
    S.html.querySelector('#dms-fs-note').textContent = n
      ? `Leaders in the current ${n}-tick window: ${top}. Use this as a shadow research signal only.`
      : 'Waiting for historical ticks and live streaming data.';
    S.html.querySelector('#dms-fs-error').textContent = S.lastError || '';
  }

  function parseTick(obj) {
    if (!obj || obj.epoch == null || obj.quote == null) return null;
    const p = obj.pip_size !== undefined && obj.pip_size !== null && Number.isInteger(+obj.pip_size) && +obj.pip_size >= 0 && +obj.pip_size <= 12 ? +obj.pip_size : (S.symbol === 'R_10' ? 3 : null);
    const str = p !== null ? Number(obj.quote).toFixed(p) : String(obj.quote);
    const last = str.match(/\.(\d+)$/);
    if (!last) return null;
    return { epoch: Number(obj.epoch), quote: str, digit: Number(last[1].slice(-1)), pip_size: p };
  }

  function captureV1(t) {
    const ds = window.SERVER_EXECUTION?.state?.digit_score;
    const ct = ds?.canonical_tick;
    const rank = ds?.ranking?.[0], epoch = Number(ds?.rank_epoch || 0);
    if (!ct || epoch !== t.epoch || String(ct.formatted_quote ?? ct.quote ?? '') !== t.quote || !rank) {
      S.snapshotUnavailable++; return null;
    }
    const d = digit(rank.digit);
    if (d === null) { S.snapshotUnavailable++; return null; }
    S.snapshotMatched++; return d;
  }

  function updateShadow(t) {
    S.seq++;
    if (S.pending) {
      const p = S.pending;
      if (S.seq === p.validForSeq) S.rows.push({ ...p, actualDigit: t.digit, hit: p.target === t.digit, observedTickKey: key(t) });
      S.pending = null;
    }
    if (S.block) {
      S.block.elapsed++;
      const hit = S.block.target === t.digit;
      S.forecasts.push({
        sourceSeq: S.block.sourceSeq, sourceTickKey: S.block.sourceTickKey,
        target: S.block.target, elapsed: S.block.elapsed, observedSeq: S.seq,
        actualDigit: t.digit, hit
      });
      if (hit || S.block.elapsed === 3) S.block = null;
    }
    const v1 = captureV1(t);
    S.prices.push(t); if (S.prices.length > MAX) S.prices.shift();
    if (S.prices.length >= 100) {
      const counts = Array(10).fill(0); for (const v of S.prices) counts[v.digit]++;
      const leader = counts.reduce((best, c, d) => c > counts[best] ? d : best, 0);
      const currentKey = key(t);
      S.pending = { sourceSeq: S.seq, validForSeq: S.seq + 1, sourceTickKey: currentKey, target: leader, method: 'FREQ1000', sampleSize: S.prices.length, v1Target: v1 };
      if (!S.block) S.block = { sourceSeq: S.seq, sourceTickKey: currentKey, target: v1 === null ? leader : v1, selection: v1 === null ? 'FREQUENCY_FALLBACK_NO_ALIGNED_V1' : 'V1_ALIGNED', elapsed: 0 };
    }
    render();
  }

  function receiveTick(raw, history = false) {
    const t = parseTick(raw); if (!t) return;
    const k = key(t); if (S.seen.has(k)) { S.rejected++; return; }
    if (!history && S.last && t.epoch < S.last.epoch) return;
    if (!history && S.last && t.epoch - S.last.epoch > 3) S.gapCount++;
    S.seen.add(k); if (S.seen.size > 3000) S.seen = new Set(Array.from(S.seen).slice(-1500));
    if (history) { S.prices.push(t); if (S.prices.length > MAX) S.prices.shift(); }
    else { S.liveTicks++; S.lastLiveAt = Date.now(); updateShadow(t); }
    S.last = t;
  }

  let retryTimer = null, startupTimer = null;

  function connect() {
    const gen = ++S.generation;
    const chosen = symbol();
    const changed = chosen !== S.symbol;
    S.symbol = chosen;
    S.connected = false; S.ready = false; S.gotHistory = false; S.gotLive = false; S.lastError = '';
    clearTimeout(retryTimer); clearTimeout(startupTimer);
    if (S.socket) { try { S.socket.close(1000, 'research reconnect'); } catch (_) {} }
    if (changed) { S.prices = []; S.seen.clear(); S.last = null; S.seq = 0; S.pending = null; S.block = null; S.liveTicks = 0; S.lastLiveAt = 0; S.rows = []; S.forecasts = []; }
    S.status = `connecting ${S.endpointIndex === 0 ? 'public' : 'legacy'}`;
    const ws = new WebSocket(ENDPOINTS[S.endpointIndex]);
    S.socket = ws;
    let gotOpen = false;

    const send = payload => { if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(payload)); };

    function retry(reason) {
      if (gen !== S.generation) return;
      clearTimeout(startupTimer);
      S.connected = false;
      S.status = reason || 'connection failed';
      S.lastError = reason || S.lastError;
      S.reconnects++;
      render();
      S.endpointIndex = (S.endpointIndex + 1) % ENDPOINTS.length;
      try { if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) ws.close(); } catch (_) {}
      clearTimeout(retryTimer);
      retryTimer = setTimeout(() => { if (gen === S.generation) connect(); }, Math.min(30000, 3000 + S.reconnects * 1500));
    }

    ws.addEventListener('open', () => {
      if (gen !== S.generation) return;
      gotOpen = true;
      S.status = `subscribing ${S.endpointIndex === 0 ? 'public' : 'legacy'}`;
      render();
      send({ ticks: S.symbol, subscribe: 1, req_id: 102 });
      send({ ticks_history: S.symbol, count: MAX, end: 'latest', style: 'ticks', req_id: 101 });
      startupTimer = setTimeout(() => { if (gen === S.generation && !S.gotLive) retry('NO LIVE TICKS (15S)'); }, 15000);
    });

    ws.addEventListener('message', ev => {
      if (gen !== S.generation) return;
      let m; try { m = JSON.parse(ev.data); } catch (_) { return; }
      if (m.error) {
        const detail = String(m.error.code || m.error.message || 'unknown');
        const origin = m.req_id === 101 ? 'history' : m.req_id === 102 ? 'subscription' : 'request';
        if (m.req_id === 101) { S.status = `history unavailable: ${detail}`; S.lastError = `History request: ${detail}`; render(); return; }
        retry(`API ${origin} ERROR: ${detail}`); return;
      }
      if (m.msg_type === 'history' && m.history && !S.gotHistory) {
        S.gotHistory = true;
        const h = m.history, prices = h.prices || [], times = h.times || [];
        const pip = Number.isInteger(Number(m.pip_size)) ? Number(m.pip_size) : null;
        for (let i = 0; i < prices.length; i++) if (times[i] != null) receiveTick({ epoch: times[i], quote: prices[i], pip_size: pip }, true);
        render();
      } else if (m.msg_type === 'tick' && m.tick) {
        S.gotLive = true;
        clearTimeout(startupTimer);
        S.ready = true; S.connected = true; S.lastError = '';
        receiveTick(m.tick, false);
        S.status = 'streaming';
        render();
      }
    });

    ws.addEventListener('close', e => {
      if (gen !== S.generation) return;
      if (retryTimer) return;
      retry(`CLOSED ${e.code}${e.reason ? ': ' + String(e.reason).slice(0, 70) : ''}${!gotOpen ? ' (before open)' : ''}`);
    });

    ws.addEventListener('error', () => {
      if (gen !== S.generation) return;
      S.status = `WEBSOCKET ERROR (${S.endpointIndex === 0 ? 'public' : 'legacy'})`;
      S.lastError = `WebSocket error on ${S.endpointIndex === 0 ? 'public' : 'legacy'} endpoint. If live ticks continue rising, this may be a transient browser-side event.`;
      render();
    });

    render();
  }

  function exportCsv() {
    const fields = ['sourceSeq','validForSeq','sourceTickKey','target','method','sampleSize','v1Target','actualDigit','hit','observedTickKey'];
    const lines = [fields.join(','), ...S.rows.map(r => fields.map(k => JSON.stringify(r[k] ?? '')).join(','))];
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `dms-frequency-shadow-${S.symbol}-${Date.now()}.csv`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  window.DMSFrequencyStudy = {
    state: S, connect, exportCsv,
    disconnect() { ++S.generation; clearTimeout(retryTimer); clearTimeout(startupTimer); S.socket?.close(); S.status = 'stopped'; render(); }
  };

  function boot() {
    ensurePanel();
    connect();
    document.getElementById('symbol')?.addEventListener('change', connect);
    setInterval(() => {
      if (!S.socket || S.socket.readyState === WebSocket.CLOSED) return;
      const age = Date.now() - (S.lastLiveAt || 0);
      if (S.socket.readyState === WebSocket.OPEN && S.ready && age > 20000) {
        S.status = 'stale: reconnecting';
        S.lastError = 'No live tick has arrived for 20 seconds on the research feed. Reconnecting.';
        render();
        S.endpointIndex = (S.endpointIndex + 1) % ENDPOINTS.length;
        connect();
      } else {
        render();
      }
    }, 5000);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
})();
