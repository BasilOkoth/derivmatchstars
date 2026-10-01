/*
 * DigitMatchStars Tick DNA -> Tail Risk Lab v1.0
 * FORWARD-ONLY · 20-CYCLE COHORT · DEMO-ONLY · SHADOW-ONLY
 *
 * Purpose:
 *   Capture the complete numerical structure ("DNA") of every live tick and
 *   test whether the state at cycle entry / early trades contains information
 *   about deep Match tails.
 *
 * It NEVER places, blocks, sizes, stops, extends, or changes a trade.
 */
(() => {
  'use strict';

  const VERSION = 'TICK-DNA-TAIL-LAB-V1.0';
  const STORE_KEY = 'digitmatchstar_tick_dna_tail_lab_v1';
  const MIN_KEY = 'matchstar_panel_min_tick_dna_lab';
  const TARGET_CYCLES = 20;
  const MAX_CONTEXT_TICKS = 100;
  const MAX_LIVE_BUFFER = 500;
  const POLL_MS = 300;
  const CHECKPOINTS = [0, 3, 5, 7, 10, 12, 15];

  let panel, body, statusEl, detailEl, armBtn, exportBtn, resetBtn;
  let liveTicks = [];
  let activeCycleId = null;
  let lastHistorySize = -1;

  function clone(v) {
    try { return JSON.parse(JSON.stringify(v)); } catch (_) { return null; }
  }

  function globalBinding(name) {
    try {
      return (0, eval)(`typeof ${name} !== 'undefined' ? ${name} : null`);
    } catch (_) {
      return null;
    }
  }

  function getCyclePerformance() {
    return globalBinding('cyclePerformance') || window.cyclePerformance || null;
  }

  function currentSymbol() {
    return document.getElementById('symbol')?.value || window.tickFormat?.symbol || 'UNKNOWN';
  }

  function accountId() {
    return String(
      localStorage.getItem('active_account') ||
      localStorage.getItem('derivDemoAccount') ||
      localStorage.getItem('derivAccount') ||
      ''
    ).trim();
  }

  function isDemoAccount() {
    const id = accountId().toUpperCase();
    if (id.startsWith('VRTC')) return true;

    const hints = [
      localStorage.getItem('account_type'),
      localStorage.getItem('trading_account_type'),
      document.body?.innerText?.match(/\b(Demo|Virtual)\b/i)?.[0]
    ].filter(Boolean).join(' ').toLowerCase();

    return hints.includes('demo') || hints.includes('virtual');
  }

  function emptyStore() {
    return {
      schema: 'DIGITMATCHSTAR_TICK_DNA_TAIL_LAB_V1',
      version: VERSION,
      createdAt: new Date().toISOString(),
      armed: false,
      armedAt: null,
      completedAt: null,
      targetCycles: TARGET_CYCLES,
      symbolAtArm: null,
      accountAtArm: null,
      frozenConfig: {
        targetCycles: TARGET_CYCLES,
        contextTicks: MAX_CONTEXT_TICKS,
        checkpoints: CHECKPOINTS.slice(),
        labels: ['beyond5', 'beyond10', 'beyond12', 'reached15']
      },
      cycles: []
    };
  }

  function loadStore() {
    try {
      const parsed = JSON.parse(localStorage.getItem(STORE_KEY) || 'null');
      if (!parsed || typeof parsed !== 'object') return emptyStore();
      return Object.assign(emptyStore(), parsed, {
        cycles: Array.isArray(parsed.cycles) ? parsed.cycles : []
      });
    } catch (_) {
      return emptyStore();
    }
  }

  function saveStore(store) {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(store)); } catch (_) {}
  }

  function formatQuote(t) {
    const q = Number(t?.quote);
    if (!Number.isFinite(q)) return null;
    const pip = Number(t?.pip_size);
    if (Number.isInteger(pip) && pip >= 0 && pip <= 10) return q.toFixed(pip);
    return String(q);
  }

  function digitArray(formatted) {
    if (!formatted) return [];
    return formatted.replace(/[^0-9]/g, '').split('').map(Number);
  }

  function decimalDigits(formatted) {
    if (!formatted || !formatted.includes('.')) return [];
    return formatted.split('.')[1].split('').map(Number);
  }

  function integerDigits(formatted) {
    if (!formatted) return [];
    return formatted.split('.')[0].replace(/[^0-9]/g, '').split('').map(Number);
  }

  function entropy10(ds) {
    if (!ds.length) return null;
    const c = Array(10).fill(0);
    ds.forEach(d => { if (Number.isInteger(d) && d >= 0 && d <= 9) c[d]++; });
    let h = 0;
    c.forEach(n => {
      if (!n) return;
      const p = n / ds.length;
      h -= p * Math.log2(p);
    });
    return h;
  }

  function tickDNA(t, previous = null) {
    const formatted = formatQuote(t);
    const all = digitArray(formatted);
    const dec = decimalDigits(formatted);
    const ints = integerDigits(formatted);
    const last = all.length ? all[all.length - 1] : null;
    const prevFmt = formatQuote(previous);
    const prevAll = digitArray(prevFmt);
    const prevLast = prevAll.length ? prevAll[prevAll.length - 1] : null;
    const quote = Number(t?.quote);
    const prevQuote = Number(previous?.quote);

    const freq = Array(10).fill(0);
    all.forEach(d => freq[d]++);

    let adjacentRepeats = 0;
    let adjacentStepSum = 0;
    for (let i = 1; i < all.length; i++) {
      if (all[i] === all[i - 1]) adjacentRepeats++;
      adjacentStepSum += Math.abs(all[i] - all[i - 1]);
    }

    return {
      epoch: Number(t?.epoch) || null,
      quote,
      formatted,
      pipSize: Number.isFinite(Number(t?.pip_size)) ? Number(t.pip_size) : null,
      digits: all,
      integerDigits: ints,
      decimalDigits: dec,
      lastDigit: last,
      secondLastDigit: all.length > 1 ? all[all.length - 2] : null,
      thirdLastDigit: all.length > 2 ? all[all.length - 3] : null,
      digitSum: all.reduce((a, b) => a + b, 0),
      integerDigitSum: ints.reduce((a, b) => a + b, 0),
      decimalDigitSum: dec.reduce((a, b) => a + b, 0),
      uniqueDigits: new Set(all).size,
      adjacentRepeats,
      adjacentStepMean: all.length > 1 ? adjacentStepSum / (all.length - 1) : 0,
      evenCount: all.filter(d => d % 2 === 0).length,
      oddCount: all.filter(d => d % 2 === 1).length,
      highCount: all.filter(d => d >= 5).length,
      lowCount: all.filter(d => d <= 4).length,
      digitFrequency: freq,
      quoteDelta: Number.isFinite(quote) && Number.isFinite(prevQuote) ? quote - prevQuote : null,
      absQuoteDelta: Number.isFinite(quote) && Number.isFinite(prevQuote) ? Math.abs(quote - prevQuote) : null,
      direction: Number.isFinite(quote) && Number.isFinite(prevQuote)
        ? (quote > prevQuote ? 1 : quote < prevQuote ? -1 : 0) : null,
      lastDigitDelta: Number.isInteger(last) && Number.isInteger(prevLast) ? last - prevLast : null,
      lastDigitAbsDelta: Number.isInteger(last) && Number.isInteger(prevLast) ? Math.abs(last - prevLast) : null,
      sameLastDigitAsPrevious: Number.isInteger(last) && Number.isInteger(prevLast) ? +(last === prevLast) : null
    };
  }

  function windowFeatures(rows, n) {
    const x = rows.slice(-n);
    if (!x.length) return null;
    const ds = x.map(r => r.dna?.lastDigit).filter(Number.isInteger);
    const quotes = x.map(r => Number(r.quote)).filter(Number.isFinite);
    const deltas = [];
    for (let i = 1; i < quotes.length; i++) deltas.push(quotes[i] - quotes[i - 1]);

    const freq = Array(10).fill(0);
    ds.forEach(d => freq[d]++);

    const mean = arr => arr.length ? arr.reduce((a,b) => a+b, 0) / arr.length : null;
    const m = mean(deltas);
    const variance = deltas.length && Number.isFinite(m)
      ? mean(deltas.map(v => (v - m) ** 2)) : null;

    let sameTransitions = 0;
    for (let i = 1; i < ds.length; i++) if (ds[i] === ds[i - 1]) sameTransitions++;

    return {
      n: x.length,
      lastDigitFrequency: freq.map(v => v / Math.max(1, ds.length)),
      lastDigitEntropy: entropy10(ds),
      sameLastDigitTransitionRate: ds.length > 1 ? sameTransitions / (ds.length - 1) : null,
      evenRate: ds.length ? ds.filter(d => d % 2 === 0).length / ds.length : null,
      highRate: ds.length ? ds.filter(d => d >= 5).length / ds.length : null,
      meanQuoteDelta: m,
      quoteDeltaStd: Number.isFinite(variance) ? Math.sqrt(variance) : null,
      upRate: deltas.length ? deltas.filter(v => v > 0).length / deltas.length : null,
      downRate: deltas.length ? deltas.filter(v => v < 0).length / deltas.length : null,
      flatRate: deltas.length ? deltas.filter(v => v === 0).length / deltas.length : null
    };
  }

  function enrichTick(raw) {
    const previous = liveTicks.length ? liveTicks[liveTicks.length - 1] : null;
    const row = {
      symbol: raw.symbol || currentSymbol(),
      quote: Number(raw.quote),
      epoch: Number(raw.epoch) || null,
      receivedAt: Number(raw.receivedAt) || Date.now(),
      pip_size: Number.isFinite(Number(raw.pip_size)) ? Number(raw.pip_size) : null,
      dna: null
    };
    row.dna = tickDNA(row, previous);
    return row;
  }

  function cycleHistory(cp) {
    if (!cp) return [];
    const symbol = currentSymbol();
    try {
      if (typeof cp.load === 'function') {
        const rows = cp.load(symbol);
        if (Array.isArray(rows)) return rows;
      }
    } catch (_) {}
    if (cp.historyBySymbol && Array.isArray(cp.historyBySymbol[symbol])) {
      return cp.historyBySymbol[symbol];
    }
    return [];
  }

  function currentCycle(cp) {
    return cp?.current || cp?.currentCycle || null;
  }

  function snapshots(cycle) {
    return Array.isArray(cycle?.tailTrajectory) ? cycle.tailTrajectory : [];
  }

  function tradeDepth(cycle) {
    const values = snapshots(cycle)
      .map(s => Number(s?.tradeNumber))
      .filter(Number.isFinite);

    const candidates = [
      Number(cycle?.winningTradeNumber),
      Number(cycle?.tradeNumber),
      Number(cycle?.trades),
      values.length ? Math.max(...values) : 0
    ].filter(Number.isFinite);

    return candidates.length ? Math.max(...candidates) : 0;
  }

  function snapshotAt(cycle, checkpoint) {
    const traj = snapshots(cycle);
    if (!traj.length) return null;

    if (checkpoint === 0) {
      return clone(
        traj.find(s => Number(s?.tradeNumber || 0) === 0 && s?.trigger === 'ENTRY') ||
        traj.find(s => Number(s?.tradeNumber || 0) === 0) ||
        traj[0]
      );
    }

    const exact = traj.filter(
      s => Number(s?.tradeNumber) === checkpoint && s?.trigger !== 'MATCH_DETECTED'
    );
    if (exact.length) {
      return clone(
        exact.find(s => s?.trigger === 'LOSS_AFTER_TICK') ||
        exact.find(s => s?.trigger === 'PURCHASE') ||
        exact[exact.length - 1]
      );
    }

    const prior = traj.filter(
      s => Number(s?.tradeNumber) <= checkpoint && s?.trigger !== 'MATCH_DETECTED'
    );
    return prior.length ? clone(prior[prior.length - 1]) : null;
  }

  function cohortRecord(store, id) {
    return store.cycles.find(c => String(c.id) === String(id)) || null;
  }

  function startCycle(cycle) {
    const store = loadStore();
    if (!store.armed || store.completedAt || store.cycles.length >= TARGET_CYCLES) return;

    const id = String(cycle?.id || '');
    if (!id || cohortRecord(store, id)) return;

    const symbol = cycle.symbol || currentSymbol();
    if (store.symbolAtArm && symbol !== store.symbolAtArm) return;

    const context = liveTicks
      .filter(t => t.symbol === symbol)
      .slice(-MAX_CONTEXT_TICKS)
      .map(clone);

    const entryTick = context.length ? context[context.length - 1] : null;

    const rec = {
      cohortIndex: store.cycles.length + 1,
      id,
      symbol,
      startedAt: new Date().toISOString(),
      startEpoch: entryTick?.epoch || null,
      targetDigit: Number.isFinite(Number(cycle?.targetDigit))
        ? Number(cycle.targetDigit)
        : Number.isFinite(Number(cycle?.predictedDigit))
          ? Number(cycle.predictedDigit)
          : Number(document.getElementById('predictedDigit')?.value),
      contextTicks: context,
      ticks: [],
      checkpoints: {},
      outcome: null,
      finalized: false
    };

    rec.entryFeatures = {
      tickDNA: entryTick?.dna || null,
      w5: windowFeatures(context, 5),
      w10: windowFeatures(context, 10),
      w25: windowFeatures(context, 25),
      w50: windowFeatures(context, 50),
      w100: windowFeatures(context, 100)
    };

    rec.checkpoints['0'] = {
      trade: 0,
      at: new Date().toISOString(),
      botSnapshot: snapshotAt(cycle, 0),
      tickDNA: entryTick?.dna || null,
      windows: {
        w5: windowFeatures(context, 5),
        w10: windowFeatures(context, 10),
        w25: windowFeatures(context, 25),
        w50: windowFeatures(context, 50)
      }
    };

    store.cycles.push(rec);
    saveStore(store);
    activeCycleId = id;
  }

  function captureCheckpoint(cycle) {
    const store = loadStore();
    if (!store.armed) return;
    const rec = cohortRecord(store, cycle?.id);
    if (!rec || rec.finalized) return;

    const depth = tradeDepth(cycle);
    const all = rec.contextTicks.concat(rec.ticks);

    for (const cp of CHECKPOINTS) {
      if (cp === 0 || depth < cp || rec.checkpoints[String(cp)]) continue;

      const lastTick = rec.ticks.length ? rec.ticks[rec.ticks.length - 1] :
        (rec.contextTicks.length ? rec.contextTicks[rec.contextTicks.length - 1] : null);

      rec.checkpoints[String(cp)] = {
        trade: cp,
        observedDepth: depth,
        at: new Date().toISOString(),
        botSnapshot: snapshotAt(cycle, cp),
        tickDNA: lastTick?.dna || null,
        windows: {
          w5: windowFeatures(all, 5),
          w10: windowFeatures(all, 10),
          w25: windowFeatures(all, 25),
          w50: windowFeatures(all, 50)
        }
      };
    }

    saveStore(store);
  }

  function finalizeCycle(cycle) {
    const store = loadStore();
    const rec = cohortRecord(store, cycle?.id);
    if (!rec || rec.finalized) return;

    const depth = tradeDepth(cycle);
    const winningTrade = Number(cycle?.winningTradeNumber);
    const status = cycle?.status || (Number.isFinite(winningTrade) ? 'WIN' : 'COMPLETE');

    rec.finalized = true;
    rec.endedAt = new Date().toISOString();
    rec.outcome = {
      status,
      winningTradeNumber: Number.isFinite(winningTrade) ? winningTrade : null,
      maximumTradeDepth: depth,
      beyond5: +(depth > 5),
      beyond10: +(depth > 10),
      beyond12: +(depth > 12),
      reached15: +(depth >= 15)
    };

    for (const cp of CHECKPOINTS) {
      if (depth >= cp && !rec.checkpoints[String(cp)]) {
        const all = rec.contextTicks.concat(rec.ticks);
        const lastTick = rec.ticks.length ? rec.ticks[rec.ticks.length - 1] :
          (rec.contextTicks.length ? rec.contextTicks[rec.contextTicks.length - 1] : null);
        rec.checkpoints[String(cp)] = {
          trade: cp,
          observedDepth: depth,
          at: new Date().toISOString(),
          botSnapshot: snapshotAt(cycle, cp),
          tickDNA: lastTick?.dna || null,
          windows: {
            w5: windowFeatures(all, 5),
            w10: windowFeatures(all, 10),
            w25: windowFeatures(all, 25),
            w50: windowFeatures(all, 50)
          }
        };
      }
    }

    if (store.cycles.filter(c => c.finalized).length >= TARGET_CYCLES) {
      store.completedAt = new Date().toISOString();
      store.armed = false;
    }

    saveStore(store);
    if (String(activeCycleId) === String(rec.id)) activeCycleId = null;
  }

  function onTick(event) {
    const raw = event?.detail;
    if (!raw || !Number.isFinite(Number(raw.quote))) return;

    const row = enrichTick(raw);
    liveTicks.push(row);
    if (liveTicks.length > MAX_LIVE_BUFFER) {
      liveTicks = liveTicks.slice(-MAX_LIVE_BUFFER);
    }

    const store = loadStore();
    if (!store.armed || !activeCycleId) return;

    const rec = cohortRecord(store, activeCycleId);
    if (!rec || rec.finalized || rec.symbol !== row.symbol) return;

    rec.ticks.push(clone(row));
    saveStore(store);
  }

  function arm() {
    if (!isDemoAccount()) {
      alert('Tick DNA Lab can only be armed on a verified Demo/Virtual account.');
      return;
    }

    const old = loadStore();
    const finalized = old.cycles.filter(c => c.finalized).length;
    if (old.armed && finalized < TARGET_CYCLES) {
      alert(`The current 20-cycle cohort is already armed (${finalized}/${TARGET_CYCLES} complete).`);
      return;
    }

    const store = emptyStore();
    store.armed = true;
    store.armedAt = new Date().toISOString();
    store.symbolAtArm = currentSymbol();
    store.accountAtArm = accountId();
    saveStore(store);
    activeCycleId = null;
    render();
  }

  function reset() {
    const ok = confirm('Reset the Tick DNA 20-cycle cohort? This deletes the locally stored cohort.');
    if (!ok) return;
    localStorage.removeItem(STORE_KEY);
    activeCycleId = null;
    render();
  }

  function exportData() {
    const store = loadStore();
    const payload = clone(store);
    payload.exportedAt = new Date().toISOString();
    payload.researchNote =
      'Forward-only shadow research. Tick DNA features are hypotheses and must not be treated as predictive until validated on unseen cycles.';

    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `tick-dna-tail-lab-${store.symbolAtArm || currentSymbol()}-${new Date().toISOString().replace(/[:.]/g, '-')}.json`;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      URL.revokeObjectURL(a.href);
      a.remove();
    }, 250);
  }

  function summary(store) {
    const done = store.cycles.filter(c => c.finalized);
    const count = done.length;
    const avg = key => count
      ? done.reduce((s,c) => s + Number(c.outcome?.[key] || 0), 0) / count
      : 0;
    const depths = done.map(c => Number(c.outcome?.maximumTradeDepth || 0));
    return {
      done: count,
      beyond5: avg('beyond5'),
      beyond10: avg('beyond10'),
      beyond12: avg('beyond12'),
      reached15: avg('reached15'),
      meanDepth: count ? depths.reduce((a,b) => a+b,0) / count : 0,
      maxDepth: count ? Math.max(...depths) : 0
    };
  }

  function setMinimized(v) {
    try { localStorage.setItem(MIN_KEY, v ? '1' : '0'); } catch (_) {}
    if (body) body.style.display = v ? 'none' : 'block';
    if (panel) {
      panel.style.width = v ? '255px' : '370px';
      panel.style.maxHeight = v ? '46px' : '620px';
    }
    const b = panel?.querySelector('[data-min]');
    if (b) b.textContent = v ? '+' : '−';
  }

  function ensurePanel() {
    if (panel && document.body.contains(panel)) return;

    panel = document.createElement('section');
    panel.id = 'tick-dna-tail-lab-panel';
    panel.style.cssText = [
      'position:fixed','left:12px','bottom:12px','z-index:2147483601',
      'width:370px','max-width:calc(100vw - 24px)','max-height:620px',
      'background:#07111f','border:1px solid #1d4ed8','border-radius:12px',
      'box-shadow:0 12px 35px rgba(0,0,0,.45)','color:#e5e7eb',
      'font-family:Inter,Arial,sans-serif','overflow:hidden'
    ].join(';');

    const header = document.createElement('div');
    header.style.cssText =
      'height:46px;display:flex;align-items:center;gap:8px;padding:0 10px;background:#0b1730;border-bottom:1px solid rgba(255,255,255,.08)';

    const title = document.createElement('div');
    title.style.cssText = 'flex:1;min-width:0';
    title.innerHTML = `
      <div style="font-size:12px;font-weight:900">Tick DNA → Tail Risk Lab</div>
      <div style="font-size:9px;color:#93c5fd">20 CYCLES · DEMO · FORWARD-ONLY · SHADOW</div>`;

    const min = document.createElement('button');
    min.dataset.min = '1';
    min.type = 'button';
    min.style.cssText =
      'width:28px;height:28px;border-radius:7px;border:1px solid #334155;background:#111827;color:#fff;font-size:18px;cursor:pointer';

    body = document.createElement('div');
    body.style.cssText = 'padding:10px;max-height:574px;overflow:auto';

    statusEl = document.createElement('div');
    statusEl.style.cssText = 'font-size:12px;font-weight:800;margin-bottom:8px';

    detailEl = document.createElement('div');
    detailEl.style.cssText = 'font-size:11px;line-height:1.5;color:#cbd5e1';

    const controls = document.createElement('div');
    controls.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;margin-top:10px';

    const mk = (label, color) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = label;
      b.style.cssText =
        `padding:7px 9px;border:0;border-radius:7px;background:${color};color:white;font-size:10px;font-weight:900;cursor:pointer`;
      return b;
    };

    armBtn = mk('ARM 20-CYCLE TEST', '#2563eb');
    exportBtn = mk('EXPORT JSON', '#047857');
    resetBtn = mk('RESET', '#7f1d1d');

    armBtn.onclick = arm;
    exportBtn.onclick = exportData;
    resetBtn.onclick = reset;
    min.onclick = () => {
      const isMin = body.style.display === 'none';
      setMinimized(!isMin);
    };

    controls.append(armBtn, exportBtn, resetBtn);
    body.append(statusEl, detailEl, controls);
    header.append(title, min);
    panel.append(header, body);
    document.body.appendChild(panel);

    const savedMin = localStorage.getItem(MIN_KEY) === '1';
    setMinimized(savedMin);
  }

  function render() {
    ensurePanel();
    const store = loadStore();
    const s = summary(store);
    const demo = isDemoAccount();

    statusEl.style.color = store.completedAt ? '#4ade80' : store.armed ? '#38bdf8' : '#fbbf24';
    statusEl.textContent = store.completedAt
      ? `COMPLETE · ${s.done}/${TARGET_CYCLES}`
      : store.armed
        ? `ARMED · ${s.done}/${TARGET_CYCLES} complete`
        : `NOT ARMED · ${demo ? 'Demo verified' : 'Demo not verified'}`;

    const active = activeCycleId ? `#${activeCycleId}` : 'none';

    detailEl.innerHTML = `
      <div><b>Symbol:</b> ${store.symbolAtArm || currentSymbol()}</div>
      <div><b>Active cycle:</b> ${active}</div>
      <div><b>Live tick buffer:</b> ${liveTicks.length}</div>
      <hr style="border:0;border-top:1px solid #1e293b;margin:8px 0">
      <div><b>Reached >5:</b> ${(s.beyond5*100).toFixed(1)}%</div>
      <div><b>Reached >10:</b> ${(s.beyond10*100).toFixed(1)}%</div>
      <div><b>Reached >12:</b> ${(s.beyond12*100).toFixed(1)}%</div>
      <div><b>Reached 15:</b> ${(s.reached15*100).toFixed(1)}%</div>
      <div><b>Mean depth:</b> ${s.meanDepth.toFixed(2)} · <b>Max:</b> ${s.maxDepth}</div>
      <hr style="border:0;border-top:1px solid #1e293b;margin:8px 0">
      <div style="color:#94a3b8">
        Captures full quote digits, digit-position structure, transitions, price movement,
        rolling 5/10/25/50/100-tick state, and bot snapshots at T0/T3/T5/T7/T10/T12/T15.
        No trading decision is changed.
      </div>`;

    armBtn.disabled = store.armed || !!store.completedAt;
    armBtn.style.opacity = armBtn.disabled ? '.45' : '1';
  }

  function pollCycles() {
    const cp = getCyclePerformance();
    if (!cp) {
      render();
      return;
    }

    const store = loadStore();
    if (!store.armed && !store.completedAt) {
      render();
      return;
    }

    const cur = currentCycle(cp);

    if (cur?.id && !cur.status) {
      if (String(activeCycleId || '') !== String(cur.id)) {
        startCycle(cur);
        activeCycleId = String(cur.id);
      }
      captureCheckpoint(cur);
    }

    const hist = cycleHistory(cp);
    if (hist.length !== lastHistorySize) {
      lastHistorySize = hist.length;
      for (const row of hist) {
        if (!row?.id) continue;
        const existing = cohortRecord(loadStore(), row.id);
        if (existing && !existing.finalized) finalizeCycle(row);
      }
    }

    // Some implementations mark the current object complete before moving it to history.
    if (cur?.id && cur.status && cohortRecord(loadStore(), cur.id)) {
      finalizeCycle(cur);
    }

    render();
  }

  window.addEventListener('digitmatchstar:tick', onTick);

  window.TickDNATailLab = Object.freeze({
    version: VERSION,
    export: exportData,
    store: () => clone(loadStore()),
    liveTicks: () => clone(liveTicks)
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      ensurePanel();
      setInterval(pollCycles, POLL_MS);
      render();
    }, { once: true });
  } else {
    ensurePanel();
    setInterval(pollCycles, POLL_MS);
    render();
  }

  console.info(`[${VERSION}] loaded`);
})();
