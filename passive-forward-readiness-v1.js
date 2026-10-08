/*
 * DigitMatchStar Passive Forward Readiness Lab V1
 * AUTO-RUN · FORWARD-ONLY · SHADOW-ONLY · NO TRADING
 *
 * Purpose:
 *   Continuously evaluate the current rank #1 digit without requiring START BOT.
 *   Each observation freezes rank #1 at T0 and watches only future ticks.
 *   Observations are non-overlapping to avoid duplicate/correlated counting.
 *
 * This module NEVER places, sizes, blocks, stops, restarts, or changes a trade.
 */
(() => {
  'use strict';

  const VERSION = 'PASSIVE-FORWARD-READINESS-V1';
  const DB_NAME = 'DigitMatchStarPassiveResearch';
  const DB_VERSION = 1;
  const STORE = 'readiness';
  const KEY = 'passive-forward-readiness-v1';
  const MAX_FORWARD = 20;
  const TARGET_OBSERVATIONS = 1000;
  const PANEL_ID = 'dms-passive-readiness-panel';

  let dbReady = false;
  let cache = null;
  let active = null;
  let ticks = [];
  let lastEpoch = null;
  let panel = null;
  let statusEl = null;
  let detailEl = null;

  const clone = v => {
    try { return JSON.parse(JSON.stringify(v)); }
    catch (_) { return null; }
  };

  function emptyStore() {
    return {
      schema: 'DIGITMATCHSTAR_PASSIVE_FORWARD_READINESS_V1',
      version: VERSION,
      createdAt: new Date().toISOString(),
      autoRun: true,
      maxForwardTicks: MAX_FORWARD,
      targetObservations: TARGET_OBSERVATIONS,
      definition: {
        entry: 'freeze current rank #1 on a canonical live tick',
        outcome: 'first future recurrence of that frozen digit',
        noMatch20: 'digit did not recur within 20 future canonical ticks',
        overlapPolicy: 'non-overlapping observations',
        execution: 'shadow only; no trading action'
      },
      observations: []
    };
  }

  function normalize(x) {
    const base = emptyStore();
    if (!x || typeof x !== 'object') return base;
    return {
      ...base,
      ...x,
      observations: Array.isArray(x.observations) ? x.observations : []
    };
  }

  function openDB() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        if (!req.result.objectStoreNames.contains(STORE)) {
          req.result.createObjectStore(STORE);
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error || new Error('IndexedDB open failed'));
    });
  }

  async function load() {
    const db = await openDB();
    try {
      const value = await new Promise((resolve, reject) => {
        const tx = db.transaction(STORE, 'readonly');
        const req = tx.objectStore(STORE).get(KEY);
        req.onsuccess = () => resolve(req.result || null);
        req.onerror = () => reject(req.error || new Error('IndexedDB read failed'));
      });
      cache = normalize(value);
    } finally {
      db.close();
    }
  }

  async function save() {
    if (!cache) return;
    const db = await openDB();
    try {
      await new Promise((resolve, reject) => {
        const tx = db.transaction(STORE, 'readwrite');
        tx.objectStore(STORE).put(cache, KEY);
        tx.oncomplete = resolve;
        tx.onerror = () => reject(tx.error || new Error('IndexedDB write failed'));
      });
    } finally {
      db.close();
    }
  }

  function canonical(raw) {
    if (!raw) return null;

    const tick = raw?.detail || raw;
    const q = Number(
      tick?.quote ??
      tick?.price ??
      tick?.raw?.quote
    );

    if (!Number.isFinite(q)) return null;

    const epoch = Number(
      tick?.epoch ??
      tick?.raw?.epoch
    ) || null;

    const pip = Number.isFinite(Number(tick?.pip_size))
      ? Number(tick.pip_size)
      : Number.isFinite(Number(tick?.raw?.pip_size))
        ? Number(tick.raw.pip_size)
        : 3;

    const formatted =
      typeof tick?.formattedQuote === 'string'
        ? tick.formattedQuote
        : q.toFixed(pip);

    const m = String(formatted).match(/(\d)\D*$/);
    const digit = m ? Number(m[1]) : null;

    return {
      symbol:
        tick?.symbol ||
        tick?.raw?.symbol ||
        document.getElementById('symbol')?.value ||
        'UNKNOWN',
      quote: q,
      formattedQuote: formatted,
      epoch,
      digit,
      pip_size: pip,
      receivedAt: Date.now()
    };
  }

  function rankSnapshot() {
    const serverScore = window.SERVER_EXECUTION?.state?.digit_score || null;
    const serverDigit = Number(serverScore?.selected_digit);

    if (
      Number.isInteger(serverDigit) &&
      serverDigit >= 0 &&
      serverDigit <= 9
    ) {
      const row = Array.isArray(serverScore?.ranking)
        ? serverScore.ranking.find(x => Number(x?.digit) === serverDigit)
        : null;

      return {
        source: 'server_digit_score',
        digit: serverDigit,
        score: Number.isFinite(Number(row?.score)) ? Number(row.score) : null,
        topMargin: Number.isFinite(Number(serverScore?.top_margin))
          ? Number(serverScore.top_margin)
          : null,
        historyCount: Number.isFinite(Number(serverScore?.history_count))
          ? Number(serverScore.history_count)
          : null,
        strength: null
      };
    }

    const rec = window.digitIntelligenceEngine?.currentRecommendation || null;
    const digit = Number(rec?.digit);

    if (
      Number.isInteger(digit) &&
      digit >= 0 &&
      digit <= 9
    ) {
      return {
        source: 'browser_digit_intelligence',
        digit,
        score: Number.isFinite(Number(rec?.score)) ? Number(rec.score) : null,
        topMargin: Number.isFinite(Number(rec?.topMargin))
          ? Number(rec.topMargin)
          : null,
        historyCount: null,
        strength: rec?.strength ?? rec?.confidenceLabel ?? null
      };
    }

    return null;
  }

  function currentSymbol() {
    return (
      window.SERVER_EXECUTION?.state?.symbol ||
      document.getElementById('symbol')?.value ||
      'UNKNOWN'
    );
  }

  function startObservation(tick) {
    const rank = rankSnapshot();
    if (!rank) return false;

    active = {
      id: `pf-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      startedAt: new Date().toISOString(),
      symbol: tick.symbol || currentSymbol(),
      targetDigit: rank.digit,
      rankSource: rank.source,
      rankScore: rank.score,
      topMargin: rank.topMargin,
      historyCount: rank.historyCount,
      strength: rank.strength,
      entryEpoch: tick.epoch,
      entryDigit: tick.digit,
      entryQuote: tick.formattedQuote,
      futureTicksObserved: 0,
      futureDigits: [],
      matched: false,
      matchDepth: null,
      matchEpoch: null,
      completedAt: null,
      noMatch20: false
    };

    return true;
  }

  function finalizeActive({ matched, tick = null }) {
    if (!active) return;

    active.matched = !!matched;
    active.matchDepth = matched ? active.futureTicksObserved : null;
    active.matchEpoch = matched ? tick?.epoch ?? null : null;
    active.noMatch20 = !matched;
    active.completedAt = new Date().toISOString();

    cache.observations.push(active);

    if (cache.observations.length > 10000) {
      cache.observations = cache.observations.slice(-10000);
    }

    active = null;
    save().catch(err => console.error('[Passive Readiness] save failed', err));
  }

  function summary() {
    const rows = cache?.observations || [];
    const matched = rows.filter(r => r?.matched);
    const depths = matched
      .map(r => Number(r?.matchDepth))
      .filter(Number.isFinite)
      .sort((a, b) => a - b);

    const pct = n => rows.length ? n / rows.length : 0;
    const q = p => {
      if (!depths.length) return null;
      const idx = Math.min(
        depths.length - 1,
        Math.max(0, Math.ceil(p * depths.length) - 1)
      );
      return depths[idx];
    };

    const byBand = {
      d1_3: rows.filter(r => r.matched && r.matchDepth <= 3).length,
      d4_6: rows.filter(r => r.matched && r.matchDepth >= 4 && r.matchDepth <= 6).length,
      d7_10: rows.filter(r => r.matched && r.matchDepth >= 7 && r.matchDepth <= 10).length,
      d11_15: rows.filter(r => r.matched && r.matchDepth >= 11 && r.matchDepth <= 15).length,
      d16_20: rows.filter(r => r.matched && r.matchDepth >= 16 && r.matchDepth <= 20).length,
      noMatch20: rows.filter(r => r.noMatch20).length
    };

    return {
      version: VERSION,
      observations: rows.length,
      active: !!active,
      matched: matched.length,
      matchRate20: pct(matched.length),
      noMatch20: byBand.noMatch20,
      noMatch20Rate: pct(byBand.noMatch20),
      medianDepth: q(0.50),
      p90Depth: q(0.90),
      p95Depth: q(0.95),
      maxDepth: depths.length ? depths[depths.length - 1] : null,
      bands: byBand,
      progress: Math.min(1, rows.length / TARGET_OBSERVATIONS)
    };
  }

  function onTick(event) {
    if (!dbReady || !cache?.autoRun) return;

    const tick = canonical(event);
    if (!tick || !Number.isInteger(tick.digit)) return;

    if (
      tick.epoch &&
      lastEpoch &&
      Number(tick.epoch) <= Number(lastEpoch)
    ) {
      return;
    }

    if (tick.epoch) lastEpoch = tick.epoch;

    ticks.push(tick);
    if (ticks.length > 500) ticks.shift();

    if (active) {
      if (
        active.symbol &&
        tick.symbol &&
        String(active.symbol) !== String(tick.symbol)
      ) {
        // Do not cross markets inside one forward observation.
        active = null;
      } else {
        active.futureTicksObserved += 1;
        active.futureDigits.push(tick.digit);

        if (tick.digit === active.targetDigit) {
          finalizeActive({ matched: true, tick });
        } else if (active.futureTicksObserved >= MAX_FORWARD) {
          finalizeActive({ matched: false, tick });
        }
      }
    }

    if (!active && (cache.observations?.length || 0) < TARGET_OBSERVATIONS) {
      startObservation(tick);
    }

    render();
  }

  function ensurePanel() {
    if (panel && document.body.contains(panel)) return;

    panel = document.createElement('section');
    panel.id = PANEL_ID;
    panel.style.cssText = [
      'position:fixed',
      'right:12px',
      'top:82px',
      'z-index:2147483604',
      'width:360px',
      'max-width:calc(100vw - 24px)',
      'background:#07111f',
      'border:1px solid #1d4ed8',
      'border-radius:12px',
      'box-shadow:0 12px 35px rgba(0,0,0,.45)',
      'color:#e5e7eb',
      'font-family:Inter,Arial,sans-serif',
      'padding:10px'
    ].join(';');

    statusEl = document.createElement('div');
    statusEl.style.cssText =
      'font-size:12px;font-weight:900;color:#60a5fa;margin-bottom:7px';

    detailEl = document.createElement('div');
    detailEl.style.cssText =
      'font-size:10px;line-height:1.5;color:#cbd5e1';

    panel.append(statusEl, detailEl);
    document.body.appendChild(panel);
  }

  function render() {
    ensurePanel();
    const s = summary();

    statusEl.textContent =
      `AUTO FORWARD RESEARCH · ${s.observations}/${TARGET_OBSERVATIONS}`;

    detailEl.innerHTML = `
      <div><b>Mode:</b> SHADOW ONLY · no START required</div>
      <div><b>Active:</b> ${
        active
          ? `digit ${active.targetDigit} · future ${active.futureTicksObserved}/${MAX_FORWARD}`
          : 'waiting for rank #1'
      }</div>
      <div><b>Matched ≤20:</b> ${s.matched}/${s.observations} · ${(100 * s.matchRate20).toFixed(1)}%</div>
      <div><b>No match by 20:</b> ${s.noMatch20} · ${(100 * s.noMatch20Rate).toFixed(1)}%</div>
      <div><b>Median depth:</b> ${s.medianDepth ?? '—'} · <b>P95:</b> ${s.p95Depth ?? '—'}</div>
      <div><b>Bands:</b> 1–3 ${s.bands.d1_3} · 4–6 ${s.bands.d4_6} · 7–10 ${s.bands.d7_10} · 11–15 ${s.bands.d11_15} · 16–20 ${s.bands.d16_20}</div>
      <div style="margin-top:5px;color:#fbbf24"><b>Research only:</b> this module never places or changes a trade.</div>
    `;
  }

  function exportJSON() {
    const payload = {
      ...clone(cache),
      summary: summary(),
      exportedAt: new Date().toISOString()
    };

    const blob = new Blob(
      [JSON.stringify(payload, null, 2)],
      { type: 'application/json;charset=utf-8' }
    );

    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download =
      `passive-forward-readiness-${currentSymbol()}-${new Date().toISOString().replace(/[:.]/g, '-')}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  async function boot() {
    ensurePanel();
    try {
      await load();
    } catch (err) {
      console.error('[Passive Readiness] load failed', err);
      cache = emptyStore();
    }

    dbReady = true;
    cache.autoRun = true;
    await save().catch(() => {});
    render();

    console.info(
      `[${VERSION}] auto-running forward research; START BOT is not required.`
    );
  }

  window.addEventListener('digitmatchstar:tick', onTick);

  window.DMSPassiveReadiness = Object.freeze({
    version: VERSION,
    summary: () => clone(summary()),
    store: () => clone(cache),
    active: () => clone(active),
    export: exportJSON
  });

  if (document.readyState === 'loading') {
    document.addEventListener(
      'DOMContentLoaded',
      () => boot().catch(console.error),
      { once: true }
    );
  } else {
    boot().catch(console.error);
  }
})();
