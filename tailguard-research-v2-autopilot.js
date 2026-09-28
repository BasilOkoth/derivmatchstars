/*
 * DigitMatchStar TailGuard Research v1.0
 * RESEARCH-ONLY SHADOW MODE + DEMO-ONLY AUTOPILOT.
 *
 * This module NEVER places, blocks, stops, retries, sizes, or modifies a trade.
 * It observes the existing cyclePerformance/tailTrajectory data, evaluates
 * experimental TailGuard checkpoints, stores shadow decisions, and exports
 * forward-only research records for later validation.
 *
 * Evidence basis for v1 thresholds: R_10 research export 2026-09-27.
 * Thresholds are hypotheses, not proven profitability rules.
 */
(function () {
  'use strict';

  const VERSION = 'TG-R2.0-AUTOPILOT';
  const STORAGE_KEY = 'digitmatchstar_tailguard_research_v1';
  const MAX_RECORDS = 2000;
  const POLL_MS = 350;

  const CFG = Object.freeze({
    // Entry shadow filter: pass if either signal is present.
    entryMinNextTickP: 0.115,
    entryMinTargetFreq50: 0.10,

    // T3 is observation-only in v1; no shadow stop is generated here.
    t3Freq50Green: 0.10,
    t3Freq100Green: 0.10,

    // T5: report-derived early warning.
    t5Freq50Floor: 0.10,
    t5Freq100Floor: 0.10,
    t5GapP90Amber: 0.90,
    t5ExtendAmber: 1.80,

    // T7: report-derived stronger tail signature.
    t7Freq50Floor: 0.10,
    t7Freq100Floor: 0.10,
    t7GapP90Red: 1.00,
    t7ExtendRed: 2.00,
    t7GapP90Amber: 0.80,
    t7ExtendAmber: 1.60,

    // Proposed research horizon only. Does not alter the live bot.
    researchMaxTrade: 10
  });

  const CHECKPOINTS = [0, 3, 5, 7];
  let lastSeenCycleId = null;
  let lastHistorySize = -1;
  let currentShadow = null;
  let panel = null;
  let panelBody = null;

  function num(v) {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  function pct(v, digits = 1) {
    return Number.isFinite(v) ? `${(v * 100).toFixed(digits)}%` : '—';
  }

  function dec(v, digits = 2) {
    return Number.isFinite(v) ? Number(v).toFixed(digits) : '—';
  }

  function safeClone(v) {
    try { return JSON.parse(JSON.stringify(v)); } catch (_) { return null; }
  }

  function globalBinding(name) {
    try {
      // Indirect eval deliberately reads only known global bindings from the
      // already-loaded classic bot script. It does not execute user content.
      return (0, eval)(`typeof ${name} !== 'undefined' ? ${name} : null`);
    } catch (_) {
      return null;
    }
  }

  function getCyclePerformance() {
    return globalBinding('cyclePerformance') || window.cyclePerformance || null;
  }

  function getPostStopTracker() {
    return globalBinding('postStopDepthTracker') || window.postStopDepthTracker || null;
  }

  function detectMode() {
    const names = ['tradingMode', 'currentTradingMode', 'tradeMode', 'botMode', 'mode'];
    for (const name of names) {
      const v = globalBinding(name);
      if (typeof v === 'string') {
        const s = v.trim().toUpperCase();
        if (s.includes('AI')) return 'AI_AUTO';
        if (s.includes('INSTANT')) return 'INSTANT';
      }
    }

    const ids = ['tradingMode', 'tradeMode', 'mode', 'modeSelect', 'mode-toggle'];
    for (const id of ids) {
      const el = document.getElementById(id);
      if (!el) continue;
      const raw = String(el.value || el.dataset?.mode || el.textContent || '').toUpperCase();
      if (raw.includes('AI')) return 'AI_AUTO';
      if (raw.includes('INSTANT')) return 'INSTANT';
    }

    const active = Array.from(document.querySelectorAll('button, [role="button"], [data-mode]'))
      .filter(el => el.classList.contains('active') || el.getAttribute('aria-pressed') === 'true' || el.dataset?.active === 'true');
    for (const el of active) {
      const raw = String(el.dataset?.mode || el.textContent || '').toUpperCase();
      if (raw.includes('AI')) return 'AI_AUTO';
      if (raw.includes('INSTANT')) return 'INSTANT';
    }
    return 'UNKNOWN';
  }

  function loadStore() {
    try {
      const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
      return {
        schema: 'DIGITMATCHSTAR_TAILGUARD_RESEARCH_V1',
        version: VERSION,
        createdAt: parsed.createdAt || new Date().toISOString(),
        records: Array.isArray(parsed.records) ? parsed.records : []
      };
    } catch (_) {
      return { schema: 'DIGITMATCHSTAR_TAILGUARD_RESEARCH_V1', version: VERSION, createdAt: new Date().toISOString(), records: [] };
    }
  }

  function saveStore(store) {
    try {
      if (store.records.length > MAX_RECORDS) store.records = store.records.slice(-MAX_RECORDS);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
    } catch (_) {}
  }

  function snapshots(cycle) {
    return Array.isArray(cycle?.tailTrajectory) ? cycle.tailTrajectory : [];
  }

  function snapshotAt(cycle, tradeNumber) {
    const traj = snapshots(cycle);
    if (!traj.length) return null;

    if (tradeNumber === 0) {
      return traj.find(s => Number(s?.tradeNumber || 0) === 0 && s?.trigger === 'ENTRY')
        || traj.find(s => Number(s?.tradeNumber || 0) === 0)
        || traj[0];
    }

    const exact = traj.filter(s => Number(s?.tradeNumber) === tradeNumber && s?.trigger !== 'MATCH_DETECTED');
    if (exact.length) {
      // Prefer the state after the loss because it reflects the information
      // available before deciding whether another recovery trade is justified.
      return exact.find(s => s?.trigger === 'LOSS_AFTER_TICK')
        || exact.find(s => s?.trigger === 'PURCHASE')
        || exact[exact.length - 1];
    }

    const prior = traj.filter(s => Number(s?.tradeNumber) <= tradeNumber && s?.trigger !== 'MATCH_DETECTED');
    return prior.length ? prior[prior.length - 1] : null;
  }

  function extractFeatures(s) {
    if (!s) return null;
    return {
      at: num(s.at),
      trigger: s.trigger || null,
      tradeNumber: num(s.tradeNumber),
      digit: num(s.digit),
      nextTickProbability: num(s.nextTickProbability),
      modelSupport: num(s.modelSupport),
      aiScore: num(s.aiScore),
      p5: num(s.p5),
      p10: num(s.p10),
      s20: num(s.s20),
      etm: num(s.etm),
      gap: num(s.gap),
      p90: num(s.p90),
      gapP90: num(s.gapP90),
      avgGap: num(s.avgGap),
      extendRatio: num(s.extendRatio),
      persistenceScore: num(s.persistenceScore),
      consecutiveExtendingGaps: num(s.consecutiveExtendingGaps),
      targetFreq20: num(s.targetFreq20),
      targetFreq50: num(s.targetFreq50),
      targetFreq100: num(s.targetFreq100),
      entropy: num(s.entropy),
      chi2: num(s.chi2),
      dominance: num(s.dominance),
      regimeLabel: s.regimeLabel || null,
      unstable: Boolean(s.unstable)
    };
  }

  function has(...xs) { return xs.every(Number.isFinite); }

  function evaluateEntry(f) {
    if (!f) return { level: 'UNKNOWN', shadowAction: 'NONE', reason: 'No entry snapshot available' };
    const p = f.nextTickProbability;
    const f50 = f.targetFreq50;
    if (!Number.isFinite(p) && !Number.isFinite(f50)) {
      return { level: 'UNKNOWN', shadowAction: 'NONE', reason: 'Entry signals unavailable' };
    }
    const pass = (Number.isFinite(p) && p >= CFG.entryMinNextTickP)
      || (Number.isFinite(f50) && f50 >= CFG.entryMinTargetFreq50);
    return pass
      ? { level: 'GREEN', shadowAction: 'PASS', reason: `entry evidence present: nextP ${pct(p)} / f50 ${pct(f50)}` }
      : { level: 'RED', shadowAction: 'SHADOW_REJECT', reason: `both entry signals below research floors: nextP ${pct(p)} / f50 ${pct(f50)}` };
  }

  function evaluateT3(f) {
    if (!f) return { level: 'UNKNOWN', shadowAction: 'NONE', reason: 'No Trade 3 snapshot yet' };
    const f50 = f.targetFreq50;
    const f100 = f.targetFreq100;
    if (!has(f50, f100)) return { level: 'UNKNOWN', shadowAction: 'NONE', reason: 'T3 frequency signals unavailable' };
    if (f50 >= CFG.t3Freq50Green || f100 >= CFG.t3Freq100Green) {
      return { level: 'GREEN', shadowAction: 'MONITOR', reason: `recent frequency supported: f50 ${pct(f50)} / f100 ${pct(f100)}` };
    }
    return { level: 'AMBER', shadowAction: 'MONITOR', reason: `both recent frequencies below 10%: f50 ${pct(f50)} / f100 ${pct(f100)}` };
  }

  function evaluateT5(f) {
    if (!f) return { level: 'UNKNOWN', shadowAction: 'NONE', reason: 'No Trade 5 snapshot yet' };
    const f50 = f.targetFreq50, f100 = f.targetFreq100, gp = f.gapP90, er = f.extendRatio;
    if (has(f50, f100) && f50 < CFG.t5Freq50Floor && f100 < CFG.t5Freq100Floor) {
      return { level: 'RED', shadowAction: 'SHADOW_STOP', reason: `T5 dual-frequency weakness: f50 ${pct(f50)} / f100 ${pct(f100)}` };
    }
    if ((Number.isFinite(gp) && gp >= CFG.t5GapP90Amber) || (Number.isFinite(er) && er >= CFG.t5ExtendAmber)
        || (Number.isFinite(f50) && f50 < CFG.t5Freq50Floor) || (Number.isFinite(f100) && f100 < CFG.t5Freq100Floor)) {
      return { level: 'AMBER', shadowAction: 'MONITOR', reason: `T5 caution: f50 ${pct(f50)}, f100 ${pct(f100)}, gap/P90 ${dec(gp)}, extend ${dec(er)}` };
    }
    return { level: 'GREEN', shadowAction: 'CONTINUE', reason: `T5 profile inside research comfort zone` };
  }

  function evaluateT7(f) {
    if (!f) return { level: 'UNKNOWN', shadowAction: 'NONE', reason: 'No Trade 7 snapshot yet' };
    const f50 = f.targetFreq50, f100 = f.targetFreq100, gp = f.gapP90, er = f.extendRatio;
    const weakFreq = has(f50, f100) && f50 < CFG.t7Freq50Floor && f100 < CFG.t7Freq100Floor;
    const extendedTail = has(gp, er) && gp >= CFG.t7GapP90Red && er >= CFG.t7ExtendRed;
    if (weakFreq || extendedTail) {
      const why = [
        weakFreq ? `dual-frequency weakness f50 ${pct(f50)} / f100 ${pct(f100)}` : null,
        extendedTail ? `extension gap/P90 ${dec(gp)} / extend ${dec(er)}` : null
      ].filter(Boolean).join('; ');
      return { level: 'RED', shadowAction: 'SHADOW_STOP', reason: `T7 tail signature: ${why}` };
    }
    if ((Number.isFinite(f50) && f50 < CFG.t7Freq50Floor)
        || (Number.isFinite(f100) && f100 < CFG.t7Freq100Floor)
        || (Number.isFinite(gp) && gp >= CFG.t7GapP90Amber)
        || (Number.isFinite(er) && er >= CFG.t7ExtendAmber)) {
      return { level: 'AMBER', shadowAction: 'MONITOR', reason: `T7 caution: f50 ${pct(f50)}, f100 ${pct(f100)}, gap/P90 ${dec(gp)}, extend ${dec(er)}` };
    }
    return { level: 'GREEN', shadowAction: 'CONTINUE', reason: `T7 profile inside research comfort zone` };
  }

  function evaluateCheckpoint(cp, f) {
    if (cp === 0) return evaluateEntry(f);
    if (cp === 3) return evaluateT3(f);
    if (cp === 5) return evaluateT5(f);
    if (cp === 7) return evaluateT7(f);
    return { level: 'UNKNOWN', shadowAction: 'NONE', reason: 'Unsupported checkpoint' };
  }

  function evaluateCycle(cycle) {
    if (!cycle?.id) return null;
    const checkpoints = {};
    for (const cp of CHECKPOINTS) {
      const snap = snapshotAt(cycle, cp);
      // Do not pretend a checkpoint occurred if the cycle has not reached it.
      const reached = cp === 0 || snapshots(cycle).some(s => Number(s?.tradeNumber) >= cp);
      if (!reached) {
        checkpoints[String(cp)] = { reached: false, features: null, decision: { level: 'PENDING', shadowAction: 'NONE', reason: `Waiting for Trade ${cp}` } };
        continue;
      }
      const f = extractFeatures(snap);
      checkpoints[String(cp)] = { reached: true, features: f, decision: evaluateCheckpoint(cp, f) };
    }

    let firstShadowStop = null;
    if (checkpoints['0']?.decision?.shadowAction === 'SHADOW_REJECT') firstShadowStop = 0;
    else {
      for (const cp of [5, 7]) {
        if (checkpoints[String(cp)]?.decision?.shadowAction === 'SHADOW_STOP') { firstShadowStop = cp; break; }
      }
    }

    const trades = Array.isArray(cycle.trades) ? cycle.trades : [];
    let savedExposure = 0;
    if (Number.isFinite(firstShadowStop) && firstShadowStop > 0) {
      savedExposure = trades
        .filter(t => Number(t?.tradeNumber) > firstShadowStop)
        .reduce((a, t) => a + (num(t?.stake) || 0), 0);
    }

    return {
      id: String(cycle.id),
      symbol: cycle.symbol || null,
      digit: num(cycle.digit),
      observedAt: new Date().toISOString(),
      mode: detectMode(),
      status: cycle.status || null,
      tailClass: cycle.tailClass || null,
      winningTradeNumber: num(cycle.winningTradeNumber),
      actualTradeCount: trades.length,
      actualNetPnL: num(cycle.netPnL),
      actualTotalInvestment: num(cycle.totalInvestment),
      actualMaxStake: num(cycle.maxStake),
      firstShadowStop,
      shadowWouldEnter: firstShadowStop !== 0,
      shadowSavedExposureFromObservedTrades: Number(savedExposure.toFixed(8)),
      checkpoints
    };
  }

  function mergeRecord(store, record) {
    const i = store.records.findIndex(r => r.id === record.id);
    if (i >= 0) {
      // Preserve the first observed mode when known; later DOM state may change
      // after the cycle has completed.
      const prev = store.records[i];
      if (prev.mode && prev.mode !== 'UNKNOWN' && record.mode === 'UNKNOWN') record.mode = prev.mode;
      store.records[i] = record;
    } else {
      store.records.push(record);
    }
    saveStore(store);
  }

  function ingestCurrent() {
    const cp = getCyclePerformance();
    if (!cp) return;
    const store = loadStore();

    const cur = cp.currentCycle;
    if (cur?.id) {
      currentShadow = evaluateCycle(cur);
      lastSeenCycleId = String(cur.id);
      mergeRecord(store, currentShadow);
    }

    const history = Array.isArray(cp.history) ? cp.history : [];
    if (history.length !== lastHistorySize) {
      lastHistorySize = history.length;
      // Re-evaluate the last few records so final status/win depth/P&L are captured.
      history.slice(-8).forEach(c => {
        const rec = evaluateCycle(c);
        if (rec) mergeRecord(store, rec);
        if (String(c?.id || '') === lastSeenCycleId) currentShadow = rec;
      });
    }
    renderPanel();
  }

  function levelColor(level) {
    if (level === 'GREEN') return '#22c55e';
    if (level === 'AMBER') return '#f59e0b';
    if (level === 'RED') return '#ef4444';
    if (level === 'PENDING') return '#64748b';
    return '#94a3b8';
  }

  function ensurePanel() {
    if (panel && document.body.contains(panel)) return;
    panel = document.createElement('section');
    panel.id = 'dms-tailguard-research-panel';
    panel.style.cssText = [
      'position:fixed','right:12px','bottom:12px','z-index:2147483000','width:min(390px,calc(100vw - 24px))',
      'font-family:Inter,system-ui,sans-serif','background:rgba(15,23,42,.97)','color:#e2e8f0',
      'border:1px solid rgba(148,163,184,.35)','border-radius:14px','box-shadow:0 18px 55px rgba(0,0,0,.45)',
      'overflow:hidden','font-size:12px'
    ].join(';');

    const head = document.createElement('div');
    head.style.cssText = 'display:flex;align-items:center;justify-content:space-between;gap:8px;padding:9px 11px;background:#0f172a;border-bottom:1px solid rgba(148,163,184,.22)';
    head.innerHTML = `<div><b>🛡️ TailGuard Research</b> <span style="opacity:.65">${VERSION}</span><div style="font-size:10px;color:#fbbf24;margin-top:2px">SHADOW ONLY — does not stop live trades</div></div>`;
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.textContent = '–';
    toggle.title = 'Collapse TailGuard research panel';
    toggle.style.cssText = 'border:0;background:#1e293b;color:#e2e8f0;border-radius:8px;width:28px;height:28px;cursor:pointer;font-weight:800';
    head.appendChild(toggle);

    panelBody = document.createElement('div');
    panelBody.style.cssText = 'padding:10px 11px;max-height:55vh;overflow:auto';

    toggle.addEventListener('click', () => {
      const hidden = panelBody.style.display === 'none';
      panelBody.style.display = hidden ? 'block' : 'none';
      toggle.textContent = hidden ? '–' : '+';
    });

    panel.append(head, panelBody);
    document.body.appendChild(panel);
  }

  function summaryStats(records) {
    const completed = records.filter(r => r.status === 'WIN' || r.status === 'STOPPED');
    const ai = completed.filter(r => r.mode === 'AI_AUTO');
    const instant = completed.filter(r => r.mode === 'INSTANT');
    const unknown = completed.filter(r => r.mode === 'UNKNOWN');
    const shadowReject = completed.filter(r => r.firstShadowStop === 0).length;
    const shadowStop5 = completed.filter(r => r.firstShadowStop === 5).length;
    const shadowStop7 = completed.filter(r => r.firstShadowStop === 7).length;
    return { completed: completed.length, ai: ai.length, instant: instant.length, unknown: unknown.length, shadowReject, shadowStop5, shadowStop7 };
  }

  function renderPanel() {
    if (!document.body) return;
    ensurePanel();
    if (!panelBody) return;
    const store = loadStore();
    const s = summaryStats(store.records);
    const r = currentShadow;

    const cps = [0, 3, 5, 7].map(cp => {
      const d = r?.checkpoints?.[String(cp)]?.decision || { level: 'PENDING', reason: 'No active cycle' };
      const label = cp === 0 ? 'ENTRY' : `T${cp}`;
      return `<div style="display:grid;grid-template-columns:46px 58px 1fr;gap:6px;align-items:start;margin:5px 0">
        <b>${label}</b>
        <span style="font-weight:800;color:${levelColor(d.level)}">${d.level}</span>
        <span style="opacity:.84">${escapeHtml(d.reason || '')}</span>
      </div>`;
    }).join('');

    panelBody.innerHTML = `
      <div style="display:flex;justify-content:space-between;gap:8px;margin-bottom:8px">
        <span>Mode: <b>${escapeHtml(r?.mode || detectMode())}</b></span>
        <span>Cycle: <b>${escapeHtml(r?.id ? r.id.slice(-8) : '—')}</b></span>
      </div>
      ${cps}
      <div style="margin-top:9px;padding-top:8px;border-top:1px solid rgba(148,163,184,.18);display:grid;grid-template-columns:1fr 1fr;gap:4px 10px">
        <span>Completed logged</span><b>${s.completed}</b>
        <span>AI AUTO</span><b>${s.ai}</b>
        <span>Instant</span><b>${s.instant}</b>
        <span>Unknown mode</span><b>${s.unknown}</b>
        <span>Shadow reject @ entry</span><b>${s.shadowReject}</b>
        <span>Shadow stop @ T5</span><b>${s.shadowStop5}</b>
        <span>Shadow stop @ T7</span><b>${s.shadowStop7}</b>
      </div>
      <div style="display:flex;gap:6px;margin-top:9px">
        <button id="tg-export" style="flex:1;border:1px solid #334155;background:#1e293b;color:#e2e8f0;padding:7px;border-radius:8px;cursor:pointer;font-weight:700">Export research</button>
        <button id="tg-clear" style="border:1px solid #7f1d1d;background:#450a0a;color:#fecaca;padding:7px 9px;border-radius:8px;cursor:pointer">Clear</button>
      </div>
      <div style="font-size:10px;opacity:.62;margin-top:7px">Thresholds are forward-validation hypotheses from a very small natural-tail sample. They are intentionally not connected to trade execution.</div>
    `;

    panelBody.querySelector('#tg-export')?.addEventListener('click', exportResearch, { once: true });
    panelBody.querySelector('#tg-clear')?.addEventListener('click', clearResearch, { once: true });
  }

  function escapeHtml(v) {
    return String(v ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  }

  function exportResearch() {
    const cp = getCyclePerformance();
    const tracker = getPostStopTracker();
    const store = loadStore();
    const payload = {
      schema: 'DIGITMATCHSTAR_TAILGUARD_FORWARD_RESEARCH_V1',
      generatedAt: new Date().toISOString(),
      moduleVersion: VERSION,
      researchOnly: true,
      liveTradingModified: false,
      config: CFG,
      source: {
        symbol: cp?.stats?.symbol || null,
        cyclePerformanceStats: safeClone(cp?.stats || null),
        postStopDepthTrackerSummary: safeClone(tracker?.summary || tracker?.stats || null)
      },
      summary: summaryStats(store.records),
      records: store.records
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `tailguard-forward-research-${payload.source.symbol || 'symbol'}-${new Date().toISOString().replace(/[:.]/g,'-')}.json`;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  }

  function clearResearch() {
    if (!confirm('Clear TailGuard research records from this browser? This does not clear the bot\'s own research history.')) return;
    localStorage.removeItem(STORAGE_KEY);
    currentShadow = null;
    lastHistorySize = -1;
    renderPanel();
  }

  // Public API for future explicit integration. The polling adapter means the
  // current bot does not need to be modified beyond loading this file.
  window.DMSTailGuardResearch = Object.freeze({
    version: VERSION,
    config: CFG,
    evaluateCycle: cycle => safeClone(evaluateCycle(cycle)),
    export: exportResearch,
    clear: clearResearch,
    getRecords: () => safeClone(loadStore().records),
    getSummary: () => safeClone(summaryStats(loadStore().records)),
    researchOnly: true
  });

  function start() {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => { ensurePanel(); renderPanel(); }, { once: true });
    } else {
      ensurePanel(); renderPanel();
    }
    setInterval(ingestCurrent, POLL_MS);
    setTimeout(ingestCurrent, 50);
  }

  start();
})();


/* ========================================================================
 * DigitMatchStar TailGuard Research Autopilot v2
 * DEMO-ONLY autonomous research runner.
 *
 * Purpose:
 * - select AI AUTO where the existing UI exposes it
 * - set the visible max-trades-per-cycle control to 10 where discoverable
 * - start the EXISTING bot automatically on DEMO
 * - collect up to 5 completed cycles per local calendar day
 * - stop the existing bot after the fifth completed cycle
 * - immediately stop if the account becomes REAL or cannot be proven DEMO
 *
 * It does NOT implement a second trading engine and does NOT call Deriv buy APIs.
 * All execution remains inside the existing DigitMatchStar bot.
 * ======================================================================== */
(function () {
  'use strict';

  const AP_VERSION = 'TG-AUTOPILOT-R1.0';
  const STATE_KEY = 'digitmatchstar_tailguard_autopilot_state_v1';
  const POLL_MS = 250;

  const CFG = Object.freeze({
    enabled: true,
    demoOnly: true,
    requiredMode: 'AI_AUTO',
    maxCyclesPerDay: 5,
    desiredMaxTradesPerCycle: 10,
    autoSelectAiAuto: true,
    autoSetVisibleTradeLimit: true,
    autoStart: true,
    autoStopAtDailyLimit: true
  });

  let panel = null;
  let statusEl = null;
  let detailEl = null;
  let lastActionAt = 0;
  let initialized = false;

  function now() { return Date.now(); }
  function localDayKey(ts = Date.now()) {
    const d = new Date(ts);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  }
  function safeClone(v) {
    try { return JSON.parse(JSON.stringify(v)); } catch (_) { return null; }
  }
  function globalBinding(name) {
    try { return (0, eval)(`typeof ${name} !== 'undefined' ? ${name} : null`); }
    catch (_) { return null; }
  }
  function callGlobal(name, ...args) {
    try {
      const fn = globalBinding(name);
      if (typeof fn === 'function') return { ok: true, value: fn(...args) };
    } catch (error) { return { ok: false, error }; }
    return { ok: false, error: new Error(`${name} unavailable`) };
  }
  function getCyclePerformance() {
    return globalBinding('cyclePerformance') || window.cyclePerformance || null;
  }
  function getBotRunning() {
    for (const name of ['botRunning', 'isBotRunning', 'running']) {
      const v = globalBinding(name);
      if (typeof v === 'boolean') return v;
    }
    const btn = document.getElementById('toggleButton');
    if (btn) {
      const t = String(btn.textContent || '').toUpperCase();
      if (t.includes('STOP')) return true;
      if (t.includes('START')) return false;
    }
    return null;
  }

  function loadState() {
    let s = {};
    try { s = JSON.parse(localStorage.getItem(STATE_KEY) || '{}') || {}; } catch (_) {}
    return {
      schema: 'DIGITMATCHSTAR_TAILGUARD_AUTOPILOT_V1',
      version: AP_VERSION,
      dayKey: s.dayKey || null,
      cyclesToday: Number.isFinite(Number(s.cyclesToday)) ? Number(s.cyclesToday) : 0,
      knownCompletedIds: Array.isArray(s.knownCompletedIds) ? s.knownCompletedIds : [],
      startedAt: s.startedAt || null,
      lastCompletedAt: s.lastCompletedAt || null,
      lastStopReason: s.lastStopReason || null,
      enabled: s.enabled !== false
    };
  }
  function saveState(s) {
    try { localStorage.setItem(STATE_KEY, JSON.stringify(s)); } catch (_) {}
  }

  function detectAccountType() {
    // Prefer explicit global account-type fields when available.
    const candidates = [
      globalBinding('accountType'),
      globalBinding('currentAccountType'),
      globalBinding('selectedAccountType'),
      globalBinding('isRealAccount')
    ];
    for (const v of candidates) {
      if (typeof v === 'boolean') return v ? 'REAL' : 'DEMO';
      if (typeof v === 'string') {
        const s = v.toUpperCase();
        if (s.includes('REAL')) return 'REAL';
        if (s.includes('DEMO') || s.includes('VIRTUAL')) return 'DEMO';
      }
    }

    // DigitMatchStar's existing account toggle styling maps checked -> REAL.
    const toggle =
      document.querySelector('.account-toggle input[type="checkbox"]') ||
      document.querySelector('input[type="checkbox"][id*="account" i]') ||
      document.querySelector('input[type="checkbox"][name*="account" i]');
    if (toggle) return toggle.checked ? 'REAL' : 'DEMO';

    // Last resort: inspect account controls only, not arbitrary page prose.
    const areas = Array.from(document.querySelectorAll('.account-toggle-container,[id*="account" i],[class*="account" i]')).slice(0, 30);
    const text = areas.map(el => String(el.textContent || '')).join(' ').toUpperCase();
    if (text.includes('REAL') && !text.includes('DEMO')) return 'REAL';
    if (text.includes('DEMO') && !text.includes('REAL')) return 'DEMO';
    return 'UNKNOWN';
  }

  function detectMode() {
    const names = ['tradingMode', 'currentTradingMode', 'tradeMode', 'botMode', 'mode'];
    for (const name of names) {
      const v = globalBinding(name);
      if (typeof v === 'string') {
        const s = v.trim().toUpperCase();
        if (s.includes('AI')) return 'AI_AUTO';
        if (s.includes('INSTANT')) return 'INSTANT';
      }
    }
    for (const el of document.querySelectorAll('select,button,[role="button"],input[type="radio"]')) {
      const raw = String(
        el.value ||
        el.dataset?.mode ||
        el.getAttribute?.('aria-label') ||
        el.textContent ||
        ''
      ).toUpperCase();
      const active =
        el.tagName === 'SELECT' ||
        el.checked === true ||
        el.classList?.contains('active') ||
        el.getAttribute?.('aria-pressed') === 'true' ||
        el.dataset?.active === 'true';
      if (!active) continue;
      if (raw.includes('AI AUTO') || (raw.includes('AI') && raw.includes('AUTO'))) return 'AI_AUTO';
      if (raw.includes('INSTANT')) return 'INSTANT';
    }
    return 'UNKNOWN';
  }

  function selectAiAuto() {
    if (detectMode() === 'AI_AUTO') return true;

    // Select element option.
    for (const sel of document.querySelectorAll('select')) {
      const opt = Array.from(sel.options || []).find(o => {
        const t = `${o.textContent || ''} ${o.value || ''}`.toUpperCase();
        return t.includes('AI AUTO') || (t.includes('AI') && t.includes('AUTO'));
      });
      if (opt) {
        sel.value = opt.value;
        sel.dispatchEvent(new Event('input', { bubbles: true }));
        sel.dispatchEvent(new Event('change', { bubbles: true }));
        return true;
      }
    }

    // Button / role button / label.
    const clickable = Array.from(document.querySelectorAll('button,[role="button"],label,[data-mode]'));
    const ai = clickable.find(el => {
      const t = `${el.textContent || ''} ${el.dataset?.mode || ''} ${el.getAttribute?.('aria-label') || ''}`.trim().toUpperCase();
      return t.includes('AI AUTO') || (t.includes('AI') && t.includes('AUTO'));
    });
    if (ai && typeof ai.click === 'function') {
      ai.click();
      return true;
    }
    return false;
  }

  function setVisibleTradeLimitTo10() {
    let changed = false;
    const inputs = Array.from(document.querySelectorAll('input[type="number"],input[inputmode="numeric"]'));
    for (const input of inputs) {
      const idText = `${input.id || ''} ${input.name || ''} ${input.getAttribute('aria-label') || ''}`.toUpperCase();
      let nearby = '';
      try {
        nearby = `${input.closest('label')?.textContent || ''} ${input.parentElement?.textContent || ''}`.toUpperCase();
      } catch (_) {}
      const hay = `${idText} ${nearby}`;
      if (!(/MAX.{0,12}TRADE|TRADE.{0,12}LIMIT|MAX.{0,12}CYCLE/.test(hay))) continue;

      if (String(input.value) !== String(CFG.desiredMaxTradesPerCycle)) {
        const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
        if (nativeSetter) nativeSetter.call(input, String(CFG.desiredMaxTradesPerCycle));
        else input.value = String(CFG.desiredMaxTradesPerCycle);
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
      }
      changed = true;
    }
    return changed;
  }

  function completedIds() {
    const cp = getCyclePerformance();
    const history = Array.isArray(cp?.history) ? cp.history : [];
    return history
      .filter(c => c?.id && (c.status === 'WIN' || c.status === 'STOPPED'))
      .map(c => String(c.id));
  }

  function refreshDailyState() {
    const state = loadState();
    const today = localDayKey();
    const ids = completedIds();

    if (state.dayKey !== today) {
      state.dayKey = today;
      state.cyclesToday = 0;
      state.knownCompletedIds = ids.slice(-500);
      state.startedAt = new Date().toISOString();
      state.lastCompletedAt = null;
      state.lastStopReason = null;
      saveState(state);
      return state;
    }

    // First install on an existing day: seed existing history without counting it.
    if (!initialized && state.knownCompletedIds.length === 0 && state.cyclesToday === 0) {
      state.knownCompletedIds = ids.slice(-500);
      if (!state.startedAt) state.startedAt = new Date().toISOString();
      saveState(state);
      return state;
    }

    const known = new Set(state.knownCompletedIds);
    const newlyCompleted = ids.filter(id => !known.has(id));
    if (newlyCompleted.length) {
      state.cyclesToday += newlyCompleted.length;
      state.lastCompletedAt = new Date().toISOString();
      state.knownCompletedIds = Array.from(new Set([...state.knownCompletedIds, ...newlyCompleted])).slice(-1000);
      saveState(state);
    }
    return state;
  }

  function stopExistingBot(reason) {
    const running = getBotRunning();
    if (running === false) return true;

    let r = callGlobal('stopBot');
    if (!r.ok) {
      const btn = document.getElementById('toggleButton');
      const text = String(btn?.textContent || '').toUpperCase();
      if (btn && text.includes('STOP')) {
        btn.click();
        r = { ok: true };
      }
    }
    if (r.ok) {
      const s = loadState();
      s.lastStopReason = reason;
      saveState(s);
      lastActionAt = now();
      return true;
    }
    return false;
  }

  function startExistingBot() {
    const running = getBotRunning();
    if (running === true) return true;

    let r = callGlobal('startBot');
    if (!r.ok) {
      const btn = document.getElementById('toggleButton');
      const text = String(btn?.textContent || '').toUpperCase();
      if (btn && text.includes('START')) {
        btn.click();
        r = { ok: true };
      }
    }
    if (r.ok) {
      lastActionAt = now();
      return true;
    }
    return false;
  }

  function ensurePanel() {
    if (panel && document.body.contains(panel)) return;
    panel = document.createElement('section');
    panel.id = 'dms-tailguard-autopilot-panel';
    panel.style.cssText = [
      'position:fixed','left:12px','bottom:12px','z-index:2147482999',
      'width:min(330px,calc(100vw - 24px))','font-family:Inter,system-ui,sans-serif',
      'background:rgba(2,6,23,.97)','color:#e2e8f0','border:1px solid rgba(56,189,248,.35)',
      'border-radius:14px','box-shadow:0 18px 55px rgba(0,0,0,.45)','padding:10px 12px','font-size:12px'
    ].join(';');
    panel.innerHTML = `
      <div style="display:flex;justify-content:space-between;gap:8px;align-items:center">
        <b>🤖 TailGuard Autopilot</b>
        <span style="font-size:10px;color:#38bdf8">${AP_VERSION}</span>
      </div>
      <div style="font-size:10px;color:#fbbf24;margin:3px 0 7px">DEMO-ONLY autonomous research</div>
      <div id="tg-ap-status" style="font-weight:800;margin-bottom:4px">Starting…</div>
      <div id="tg-ap-detail" style="opacity:.82;line-height:1.35"></div>
      <button id="tg-ap-toggle" type="button" style="margin-top:8px;width:100%;border:1px solid #334155;background:#0f172a;color:#e2e8f0;padding:7px;border-radius:8px;cursor:pointer;font-weight:700">Pause autopilot</button>
    `;
    document.body.appendChild(panel);
    statusEl = panel.querySelector('#tg-ap-status');
    detailEl = panel.querySelector('#tg-ap-detail');
    panel.querySelector('#tg-ap-toggle')?.addEventListener('click', () => {
      const s = loadState();
      s.enabled = !s.enabled;
      saveState(s);
      if (!s.enabled) stopExistingBot('Autopilot manually paused');
      render(s, detectAccountType(), detectMode(), getBotRunning(), s.enabled ? 'Resuming…' : 'Paused');
    });
  }

  function render(state, account, mode, running, message) {
    ensurePanel();
    if (!statusEl || !detailEl) return;
    const limitReached = state.cyclesToday >= CFG.maxCyclesPerDay;
    statusEl.textContent = message || (limitReached ? 'Daily research complete' : running ? 'Research running' : 'Waiting');
    statusEl.style.color = limitReached ? '#22c55e' : account === 'REAL' ? '#ef4444' : '#38bdf8';
    detailEl.innerHTML = `
      Account: <b>${account}</b><br>
      Mode: <b>${mode}</b><br>
      Bot: <b>${running === true ? 'RUNNING' : running === false ? 'STOPPED' : 'UNKNOWN'}</b><br>
      Today: <b>${state.cyclesToday}/${CFG.maxCyclesPerDay} cycles</b><br>
      Max trades/cycle target: <b>${CFG.desiredMaxTradesPerCycle}</b><br>
      Autopilot: <b>${state.enabled ? 'ENABLED' : 'PAUSED'}</b>
      ${state.lastStopReason ? `<br>Last stop: <b>${String(state.lastStopReason).replace(/[&<>]/g,'')}</b>` : ''}
    `;
    const b = panel?.querySelector('#tg-ap-toggle');
    if (b) b.textContent = state.enabled ? 'Pause autopilot' : 'Resume autopilot';
  }

  function tick() {
    if (!document.body) return;
    ensurePanel();

    const state = refreshDailyState();
    initialized = true;
    const account = detectAccountType();
    let mode = detectMode();
    const running = getBotRunning();

    if (!state.enabled || !CFG.enabled) {
      render(state, account, mode, running, 'Autopilot paused');
      return;
    }

    // Hard safety boundary: autonomous mode is never allowed on REAL.
    if (account !== 'DEMO') {
      if (running === true) stopExistingBot(account === 'REAL' ? 'REAL account detected — autonomous research blocked' : 'Account type not proven DEMO');
      render(state, account, mode, getBotRunning(),
        account === 'REAL' ? 'Blocked on REAL account' : 'Waiting for confirmed DEMO account');
      return;
    }

    if (CFG.autoStopAtDailyLimit && state.cyclesToday >= CFG.maxCyclesPerDay) {
      if (running !== false) stopExistingBot(`Daily limit reached: ${CFG.maxCyclesPerDay} completed cycles`);
      render(state, account, mode, getBotRunning(), 'Daily research complete');
      return;
    }

    if (CFG.autoSetVisibleTradeLimit) setVisibleTradeLimitTo10();

    if (CFG.autoSelectAiAuto && mode !== CFG.requiredMode && now() - lastActionAt > 1200) {
      selectAiAuto();
      lastActionAt = now();
      mode = detectMode();
    }

    // Do not start until AI AUTO is actually confirmed.
    if (mode !== CFG.requiredMode) {
      if (running === true) stopExistingBot('AI AUTO not confirmed');
      render(state, account, mode, getBotRunning(), 'Waiting for AI AUTO');
      return;
    }

    if (CFG.autoStart && running !== true && now() - lastActionAt > 1500) {
      const started = startExistingBot();
      render(state, account, mode, getBotRunning(), started ? 'Starting autonomous research…' : 'Could not start bot automatically');
      return;
    }

    render(state, account, mode, running, running === true ? 'Autonomous research running' : 'Waiting to start');
  }

  function start() {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => {
        ensurePanel();
        setInterval(tick, POLL_MS);
        setTimeout(tick, 300);
      }, { once: true });
    } else {
      ensurePanel();
      setInterval(tick, POLL_MS);
      setTimeout(tick, 300);
    }
  }

  window.DMSTailGuardAutopilot = Object.freeze({
    version: AP_VERSION,
    config: CFG,
    getState: () => safeClone(loadState()),
    pause: () => {
      const s = loadState(); s.enabled = false; saveState(s);
      stopExistingBot('Autopilot API pause');
      return safeClone(s);
    },
    resume: () => {
      const s = loadState(); s.enabled = true; saveState(s);
      return safeClone(s);
    },
    resetToday: () => {
      const s = loadState();
      s.dayKey = localDayKey(); s.cyclesToday = 0; s.knownCompletedIds = completedIds().slice(-500);
      s.startedAt = new Date().toISOString(); s.lastCompletedAt = null; s.lastStopReason = null;
      saveState(s); return safeClone(s);
    },
    demoOnly: true
  });

  start();
})();
