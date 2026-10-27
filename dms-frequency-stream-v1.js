
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
      #dms-frequency-study{font-family:Inter,system-ui,sans-serif;margin:10px 0 0;padding:9px 10px;border:1px solid #334155;border-radius:12px;background:#0f172a;color:#e2e8f0;box-sizing:border-box;width:100%}
      #dms-frequency-study .fs-head{display:flex;align-items:center;justify-content:space-between;gap:6px}
      #dms-frequency-study .fs-title{font-size:12px;font-weight:850;letter-spacing:.01em}
      #dms-frequency-study .fs-actions{display:flex;align-items:center;gap:7px}
      #dms-frequency-study .fs-status{font-size:10px;font-weight:750;color:#34d399;white-space:nowrap;max-width:100px}
      #dms-frequency-study .fs-status.fs-warning{color:#fbbf24}
      #dms-frequency-study .fs-toggle{width:25px;height:23px;border:1px solid #475569;border-radius:7px;background:#1e293b;color:#e2e8f0;font-size:16px;font-weight:bold;cursor:pointer}
      #dms-frequency-study .fs-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:5px;margin-top:9px}
      #dms-frequency-study .fs-tile{display:flex;align-items:center;justify-content:center;gap:5px;min-height:31px;border:1px solid #334155;border-radius:8px;background:#1e293b;padding:3px 4px;white-space:nowrap}
      #dms-frequency-study .fs-digit{font-size:12px;font-weight:900;color:#e2e8f0}
      #dms-frequency-study .fs-percent{font-size:12px;font-weight:900;color:#cbd5e1}
      #dms-frequency-study .fs-tile.first{background:rgba(5,150,105,.15);border-color:#059669}
      #dms-frequency-study .fs-tile.first .fs-percent{color:#4ade80}
      #dms-frequency-study .fs-tile.high{border-color:rgba(34,197,94,.4)}
      #dms-frequency-study .fs-tile.high .fs-percent{color:#86efac}
      #dms-frequency-study .fs-tile.medium .fs-percent{color:#93c5fd}
      #dms-frequency-study .fs-tile.low .fs-percent{color:#fcd34d}
      #dms-frequency-study .fs-tile.bottom .fs-percent{color:#fca5a5}
      #dms-frequency-study .fs-foot{display:flex;align-items:center;justify-content:space-between;gap:7px;margin-top:7px}
      #dms-frequency-study .fs-window{font-size:10px;color:#94a3b8}
      #dms-frequency-study .fs-export{border:1px solid #475569;background:#1e293b;color:#cbd5e1;border-radius:7px;padding:4px 7px;font-size:10px;cursor:pointer}
      #dms-frequency-study .fs-body[hidden]{display:none!important}
      @media(max-width:375px){#dms-frequency-study .fs-grid{grid-template-columns:repeat(2,minmax(0,1fr))}#dms-frequency-study .fs-title{font-size:11px}}
    `;
    document.head.appendChild(style);
  }

  function ensurePanel() {
    installStyles();
    if (S.html?.isConnected) return;
    const host = document.createElement('section');
    host.id = 'dms-frequency-study';
    host.innerHTML = `
      <div class="fs-head">
        <strong class="fs-title">Digit frequency · ${S.symbol}</strong>
        <div class="fs-actions">
          <span id="dms-fs-status" class="fs-status">CONNECTING</span>
          <button id="dms-fs-toggle" class="fs-toggle" type="button" aria-controls="dms-fs-body" aria-expanded="true" title="Minimize frequency panel">−</button>
        </div>
      </div>
      <div id="dms-fs-body" class="fs-body">
        <div id="dms-fs-grid" class="fs-grid"></div>
        <div class="fs-foot">
          <span id="dms-fs-window" class="fs-window">0/1000 ticks · read-only</span>
          <button id="dms-fs-export" class="fs-export" type="button">Export CSV</button>
        </div>
      </div>`;
    const market = document.getElementById('market_status');
    const container = market?.closest('.bg-gray-900.border') || document.querySelector('.lg\\:col-span-1');
    if (container) container.appendChild(host); else document.body.prepend(host);
    host.querySelector('#dms-fs-export').addEventListener('click', exportCsv);
    const toggle = host.querySelector('#dms-fs-toggle');
    const body = host.querySelector('#dms-fs-body');
    const apply = hidden => {
      body.hidden = hidden;
      toggle.textContent = hidden ? '+' : '−';
      toggle.setAttribute('aria-expanded', String(!hidden));
      toggle.title = hidden ? 'Expand frequency panel' : 'Minimize frequency panel';
      try { localStorage.setItem('dms_fs_minimized', hidden ? '1' : '0'); } catch (_) {}
    };
    toggle.addEventListener('click', () => apply(!body.hidden));
    let minimized = false;
    try { minimized = localStorage.getItem('dms_fs_minimized') === '1'; } catch (_) {}
    apply(minimized);
    S.html = host;
    render();
  }

  function render() {
    ensurePanel();
    const counts = Array(10).fill(0);
    for (const item of S.prices) counts[item.digit]++;
    const n = S.prices.length;
    if (S.connected && S.lastLiveAt && Date.now() - S.lastLiveAt > 10000) S.status = 'stale: no new ticks';
    const sorted = counts.map((count, digit) => ({digit, percentage: n ? 100 * count / n : NaN})).sort((a,b) => (b.percentage - a.percentage) || (a.digit - b.digit));
    const el = S.html.querySelector('#dms-fs-status');
    const stateText = String(S.status).toLowerCase();
    const isLive = stateText === 'streaming' && S.socket?.readyState === WebSocket.OPEN;
    const stateLabel = isLive ? '● LIVE' : stateText.includes('connecting') || stateText.includes('subscribing') ? '● CONNECTING' : stateText.includes('stale') ? '● STALE' : stateText.includes('stopped') ? '● STOPPED' : '● OFFLINE';
    el.textContent = stateLabel;
    el.title = S.lastError || S.status;
    el.classList.toggle('fs-warning', !isLive);
    S.html.querySelector('#dms-fs-grid').innerHTML = sorted.map((item,i) => {
      const tier = i===0?'first':i<=2?'high':i<=6?'medium':i<=8?'low':'bottom';
      return `<div class="fs-tile ${tier}" title="Digit ${item.digit} · rank ${i+1} by historical frequency"><span class="fs-digit">${item.digit}</span><span class="fs-percent">${Number.isFinite(item.percentage)?item.percentage.toFixed(1):'—'}%</span></div>`;
    }).join('');
    S.html.querySelector('#dms-fs-window').textContent = `${n}/1000 ticks · ${S.liveTicks} live · ${S.reconnects} reconnects`;
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
  let retryPending = false;

  function connect() {
    const gen = ++S.generation;
    const chosen = symbol();
    const changed = chosen !== S.symbol;
    S.symbol = chosen;
    S.connected = false; S.ready = false; S.gotHistory = false; S.gotLive = false; S.lastError = '';
    clearTimeout(retryTimer); clearTimeout(startupTimer); retryTimer = null; retryPending = false;
    if (S.socket) { try { S.socket.close(1000, 'research reconnect'); } catch (_) {} }
    if (changed) { S.prices = []; S.seen.clear(); S.last = null; S.seq = 0; S.pending = null; S.block = null; S.liveTicks = 0; S.lastLiveAt = 0; S.rows = []; S.forecasts = []; }
    S.status = `connecting ${S.endpointIndex === 0 ? 'public' : 'legacy'}`;
    const ws = new WebSocket(ENDPOINTS[S.endpointIndex]);
    S.socket = ws;
    let gotOpen = false;

    const send = payload => { if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(payload)); };

    function retry(reason) {
      if (gen !== S.generation || retryPending) return;
      retryPending = true;
      clearTimeout(startupTimer);
      S.connected = false;
      S.status = reason || 'connection failed';
      S.lastError = reason || S.lastError;
      S.reconnects++;
      render();
      S.endpointIndex = (S.endpointIndex + 1) % ENDPOINTS.length;
      try { if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) ws.close(); } catch (_) {}
      clearTimeout(retryTimer);
      retryTimer = setTimeout(() => { retryTimer = null; retryPending = false; if (gen === S.generation) connect(); }, Math.min(30000, 3000 + S.reconnects * 1500));
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
      if (retryPending) return;
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
    disconnect() { ++S.generation; clearTimeout(retryTimer); clearTimeout(startupTimer); retryPending=false; S.socket?.close(); S.status = 'stopped'; render(); }
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
