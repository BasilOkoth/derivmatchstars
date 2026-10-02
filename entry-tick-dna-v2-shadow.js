/*
 * DigitMatchStar Entry Tick DNA V2 Shadow Validation
 * FORWARD-ONLY · ENTRY/T0 ONLY · DEMO-ONLY · SHADOW-ONLY
 *
 * Frozen from the 2026-10-02 R_10 cohort (96 finalized cycles):
 *   Baseline tail >=15: 22/96 = 22.9%
 *   adjRepeats>=1 AND w25 meanQuoteDelta>0: 7/11 = 63.6%
 *
 * This module NEVER places, blocks, sizes, stops, extends, or changes a trade.
 * It only records what the frozen entry filter WOULD have done.
 */
(() => {
  'use strict';

  const VERSION = 'ENTRY-TICK-DNA-V2-FROZEN-SHADOW-2026-10-02-CYCLECAPTURE-FIX';
  const DB_NAME = 'DigitMatchStarTickDNA';
  const DB_VERSION = 1;
  const DB_STORE = 'validation';
  const DB_RECORD_KEY = 'entry-tick-dna-v2-shadow-r10';
  const TARGET_CYCLES = 100;
  const MAX_BUFFER = 500;
  const CONTEXT_TICKS = 100;
  const POLL_MS = 300;
  const MIN_KEY = 'matchstar_panel_min_entry_tick_dna_v2';

  const FROZEN_MODEL = Object.freeze({
    name: 'Entry Tick DNA V2',
    frozenAt: '2026-10-02T11:47:06.124Z',
    discoveryCohort: 'R_10 · 96 finalized cycles · uncensored through trade 20',
    target: 'maximumTradeDepth >= 15',
    baseline: Object.freeze({ n: 96, tails15: 22, rate: 22 / 96 }),
    rules: Object.freeze([
      Object.freeze({ key: 'adjacentRepeats', op: '>=', threshold: 1, points: 50 }),
      Object.freeze({ key: 'w25MeanQuoteDelta', op: '>', threshold: 0, points: 50 })
    ]),
    bands: Object.freeze([
      Object.freeze({ score: 100, label: 'HIGH', shadowAction: 'SKIP_CANDIDATE' }),
      Object.freeze({ score: 50, label: 'WATCH', shadowAction: 'ACCEPT' }),
      Object.freeze({ score: 0, label: 'LOW', shadowAction: 'ACCEPT' })
    ]),
    discoveryResult: Object.freeze({
      highRiskN: 11,
      highRiskTails15: 7,
      highRiskTailRate: 7 / 11,
      tailCapture: 7 / 22,
      falseRejects: 4,
      residualAcceptedTailRate: 15 / 85
    })
  });

  let liveTicks = [];
  let activeCycleId = null;
  let lastHistorySize = -1;
  let cache = null;
  let ready = false;
  let persistenceState = 'starting';
  let persistenceError = null;
  let writeChain = Promise.resolve();
  let panel, body, statusEl, detailEl, armBtn, exportBtn, resetBtn;
  let lifecycleHookInstalled = false;
  let lastCapturedCycleText = null;

  function clone(v) { try { return JSON.parse(JSON.stringify(v)); } catch (_) { return null; } }
  function globalBinding(name) { try { return (0, eval)(`typeof ${name} !== 'undefined' ? ${name} : null`); } catch (_) { return null; } }
  function cyclePerformance() { return globalBinding('cyclePerformance') || window.cyclePerformance || null; }
  function currentSymbol() { return document.getElementById('symbol')?.value || window.tickFormat?.symbol || 'UNKNOWN'; }
  function accountId() { return String(localStorage.getItem('active_account') || localStorage.getItem('derivDemoAccount') || localStorage.getItem('derivAccount') || '').trim(); }
  function accountMode() {
    const stored = String(localStorage.getItem('selectedAccountMode') || '').toUpperCase();
    if (stored === 'DEMO' || stored === 'REAL') return stored;
    const toggle = document.getElementById('accTypeToggle');
    if (toggle) return toggle.checked ? 'REAL' : 'DEMO';
    const id = accountId().toUpperCase();
    if (id.startsWith('VRTC')) return 'DEMO';
    const hints = [
      localStorage.getItem('account_type'),
      localStorage.getItem('trading_account_type'),
      document.body?.innerText?.match(/\b(Demo|Virtual)\b/i)?.[0]
    ].filter(Boolean).join(' ').toLowerCase();
    if (hints.includes('demo') || hints.includes('virtual')) return 'DEMO';
    if (hints.includes('real')) return 'REAL';
    return 'UNKNOWN';
  }
  function isDemoAccount() { return accountMode() === 'DEMO'; }

  function emptyStore() {
    return {
      schema: 'DIGITMATCHSTAR_ENTRY_TICK_DNA_V2_SHADOW',
      version: VERSION,
      createdAt: new Date().toISOString(),
      armed: false,
      armedAt: null,
      completedAt: null,
      targetCycles: TARGET_CYCLES,
      symbolAtArm: null,
      frozenModel: clone(FROZEN_MODEL),
      cycles: []
    };
  }
  function normalizeStore(x) {
    if (!x || typeof x !== 'object') return emptyStore();
    return Object.assign(emptyStore(), x, { version: VERSION, frozenModel: clone(FROZEN_MODEL), cycles: Array.isArray(x.cycles) ? x.cycles : [] });
  }

  function openDB() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => { if (!req.result.objectStoreNames.contains(DB_STORE)) req.result.createObjectStore(DB_STORE); };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error || new Error('IndexedDB open failed'));
    });
  }
  async function idbGet() {
    const db = await openDB();
    try { return await new Promise((resolve, reject) => {
      const tx = db.transaction(DB_STORE, 'readonly');
      const req = tx.objectStore(DB_STORE).get(DB_RECORD_KEY);
      req.onsuccess = () => resolve(req.result || null);
      req.onerror = () => reject(req.error || new Error('IndexedDB read failed'));
    }); } finally { db.close(); }
  }
  async function idbPut(v) {
    const db = await openDB();
    try { await new Promise((resolve, reject) => {
      const tx = db.transaction(DB_STORE, 'readwrite');
      tx.objectStore(DB_STORE).put(v, DB_RECORD_KEY);
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error || new Error('IndexedDB write failed'));
      tx.onabort = () => reject(tx.error || new Error('IndexedDB write aborted'));
    }); } finally { db.close(); }
  }
  async function idbDelete() {
    const db = await openDB();
    try { await new Promise((resolve, reject) => {
      const tx = db.transaction(DB_STORE, 'readwrite');
      tx.objectStore(DB_STORE).delete(DB_RECORD_KEY);
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error || new Error('IndexedDB delete failed'));
    }); } finally { db.close(); }
  }
  function loadStore() { if (!cache) cache = emptyStore(); return cache; }
  function saveStore(s) {
    cache = normalizeStore(s);
    writeChain = writeChain.then(() => idbPut(cache)).catch(err => { persistenceState = 'error'; persistenceError = String(err?.message || err); });
  }
  async function initPersistence() {
    try { cache = normalizeStore(await idbGet()); persistenceState = cache?.cycles?.length ? 'ready' : 'ready-empty'; ready = true; }
    catch (e) { cache = emptyStore(); persistenceState = 'error'; persistenceError = String(e?.message || e); ready = true; }
  }

  function formatQuote(t) {
    if (!t) return null;
    if (typeof t.formattedQuote === 'string' && t.formattedQuote) return t.formattedQuote;
    const q = Number(t.quote); if (!Number.isFinite(q)) return null;
    const p = Number.isFinite(Number(t.pip_size)) ? Number(t.pip_size) : 3;
    return q.toFixed(p);
  }
  function digitsOf(s) { return String(s || '').replace(/[^0-9]/g, '').split('').filter(Boolean).map(Number); }
  function lastDigit(t) { const d = digitsOf(formatQuote(t)); return d.length ? d[d.length - 1] : null; }
  function adjacentRepeats(t) {
    const d = digitsOf(formatQuote(t)); let n = 0;
    for (let i = 1; i < d.length; i++) if (d[i] === d[i-1]) n++;
    return n;
  }
  function enrich(raw) {
    const prev = liveTicks.length ? liveTicks[liveTicks.length - 1] : null;
    const q = Number(raw.quote), pq = Number(prev?.quote);
    return {
      symbol: raw.symbol || currentSymbol(), quote: q, epoch: Number(raw.epoch) || null,
      receivedAt: Number(raw.receivedAt) || Date.now(), pip_size: Number.isFinite(Number(raw.pip_size)) ? Number(raw.pip_size) : null,
      formattedQuote: typeof raw.formattedQuote === 'string' ? raw.formattedQuote : null,
      lastDigit: null, adjacentRepeats: null, quoteDelta: Number.isFinite(q) && Number.isFinite(pq) ? q-pq : null
    };
  }
  function meanQuoteDelta(rows, n) {
    const x = rows.slice(-n); if (x.length < 2) return null;
    const qs = x.map(r => Number(r.quote)).filter(Number.isFinite); if (qs.length < 2) return null;
    let sum = 0; for (let i=1;i<qs.length;i++) sum += qs[i]-qs[i-1];
    return sum / (qs.length-1);
  }
  function entropyLastDigits(rows, n) {
    const ds = rows.slice(-n).map(r => Number(r.lastDigit)).filter(Number.isInteger); if (!ds.length) return null;
    const c = Array(10).fill(0); ds.forEach(d => c[d]++);
    let h = 0; c.forEach(v => { if (v) { const p=v/ds.length; h -= p*Math.log2(p); } }); return h;
  }
  function targetFreq(rows, n, digit) {
    const ds = rows.slice(-n).map(r => Number(r.lastDigit)).filter(Number.isInteger); if (!ds.length || !Number.isInteger(digit)) return null;
    return ds.filter(d => d===digit).length / ds.length;
  }

  function scoreEntry(entryTick, context, targetDigit) {
    const ar = Number(entryTick?.adjacentRepeats);
    const drift25 = meanQuoteDelta(context, 25);
    const repeatHit = Number.isFinite(ar) && ar >= 1;
    const driftHit = Number.isFinite(drift25) && drift25 > 0;
    const score = (repeatHit ? 50 : 0) + (driftHit ? 50 : 0);
    const band = score === 100 ? 'HIGH' : score === 50 ? 'WATCH' : 'LOW';
    return {
      version: VERSION,
      score, band,
      shadowAction: band === 'HIGH' ? 'SKIP_CANDIDATE' : 'ACCEPT',
      features: {
        adjacentRepeats: ar,
        w25MeanQuoteDelta: drift25,
        immediateQuoteDelta: Number(entryTick?.quoteDelta),
        immediateDirection: Number(entryTick?.quoteDelta) > 0 ? 1 : Number(entryTick?.quoteDelta) < 0 ? -1 : 0,
        entryLastDigit: Number(entryTick?.lastDigit),
        targetDigit: Number(targetDigit),
        entryTargetMatchesLastDigit: Number(entryTick?.lastDigit) === Number(targetDigit),
        targetFreq5: targetFreq(context, 5, Number(targetDigit)),
        targetFreq10: targetFreq(context, 10, Number(targetDigit)),
        targetFreq25: targetFreq(context, 25, Number(targetDigit)),
        entropy5: entropyLastDigits(context, 5),
        entropy10: entropyLastDigits(context, 10),
        entropy25: entropyLastDigits(context, 25)
      },
      ruleHits: { adjacentRepeatsGte1: repeatHit, positiveDrift25: driftHit }
    };
  }

  function cycleHistory(cp) {
    if (!cp) return []; const symbol = currentSymbol();
    try { if (typeof cp.load === 'function') { const x=cp.load(symbol); if (Array.isArray(x)) return x; } } catch (_) {}
    if (cp.historyBySymbol && Array.isArray(cp.historyBySymbol[symbol])) return cp.historyBySymbol[symbol];
    return [];
  }
  function currentCycle(cp) { return cp?.current || cp?.currentCycle || null; }
  function tradeDepth(c) {
    const traj = Array.isArray(c?.tailTrajectory) ? c.tailTrajectory : [];
    const nums = traj.map(s=>Number(s?.tradeNumber)).filter(Number.isFinite);
    const tradeLen = Array.isArray(c?.trades) ? c.trades.length : 0;
    const vals=[Number(c?.winningTradeNumber),Number(c?.tradeNumber),tradeLen,nums.length?Math.max(...nums):0].filter(Number.isFinite);
    return vals.length ? Math.max(...vals) : 0;
  }
  function cycleTarget(c) {
    for (const v of [c?.digit,c?.targetDigit,c?.predictedDigit,document.getElementById('predictedDigit')?.value]) {
      const n=Number(v); if (Number.isInteger(n) && n>=0 && n<=9) return n;
    }
    return null;
  }
  function recById(store,id) { return store.cycles.find(r=>String(r.id)===String(id)) || null; }

  function startCycle(c) {
    const s=loadStore(); if (!s.armed || s.completedAt || s.cycles.length>=TARGET_CYCLES) return;
    const id=String(c?.id||''); if (!id || recById(s,id)) return;
    const symbol=c?.symbol||currentSymbol(); if (s.symbolAtArm && symbol!==s.symbolAtArm) return;
    let context=liveTicks.filter(t=>t.symbol===symbol).slice(-CONTEXT_TICKS).map(clone);
    // Robust fallback: if the shadow listener missed the latest public tick,
    // use the bot's authoritative lastTick rather than losing the cycle.
    const authoritative = window.lastTick;
    if ((!context.length || (authoritative?.epoch && Number(context[context.length-1]?.epoch)!==Number(authoritative.epoch))) && authoritative && Number.isFinite(Number(authoritative.quote))) {
      const row=enrich(authoritative); row.lastDigit=lastDigit(row); row.adjacentRepeats=adjacentRepeats(row);
      context=[...context, row].slice(-CONTEXT_TICKS);
    }
    const entry=context.length?context[context.length-1]:null;
    const target=cycleTarget(c);
    const risk=scoreEntry(entry,context,target);
    s.cycles.push({
      cohortIndex:s.cycles.length+1,id,symbol,startedAt:new Date().toISOString(),startEpoch:entry?.epoch||null,
      targetDigit:target, entryTick:clone(entry), entryContextSummary:{ n:context.length, w25MeanQuoteDelta:meanQuoteDelta(context,25) },
      frozenEntryRisk:risk, outcome:null, finalized:false
    });
    saveStore(s); activeCycleId=id;
  }
  function finalizeCycle(c) {
    const s=loadStore(); const r=recById(s,c?.id); if (!r || r.finalized) return;
    const depth=tradeDepth(c), win=Number(c?.winningTradeNumber);
    r.finalized=true; r.endedAt=new Date().toISOString();
    r.outcome={ status:c?.status || (Number.isFinite(win)?'WIN':'COMPLETE'), winningTradeNumber:Number.isFinite(win)?win:null, maximumTradeDepth:depth, reached15:+(depth>=15) };
    if (s.cycles.filter(x=>x.finalized).length>=TARGET_CYCLES) { s.completedAt=new Date().toISOString(); s.armed=false; }
    saveStore(s);
    lastCapturedCycleText = `#${r.cohortIndex} · digit ${r.targetDigit ?? '?'} · depth ${depth} · ${r.frozenEntryRisk?.band || '?'} / ${r.frozenEntryRisk?.shadowAction || '?'}`;
    if (String(activeCycleId)===String(r.id)) activeCycleId=null;
  }
  function installLifecycleHook() {
    if (lifecycleHookInstalled) return true;
    const cp = cyclePerformance();
    if (!cp || typeof cp.startCycle !== 'function' || typeof cp.completeCycle !== 'function') return false;
    if (cp.__entryTickDNAV2Hooked) { lifecycleHookInstalled = true; return true; }

    const originalStartCycle = cp.startCycle.bind(cp);
    cp.startCycle = function(contract, pending = null) {
      const out = originalStartCycle(contract, pending);
      try { if (this.current?.id) startCycle(this.current); } catch (err) { console.error(`[${VERSION}] start capture failed`, err); }
      return out;
    };

    const originalCompleteCycle = cp.completeCycle.bind(cp);
    cp.completeCycle = function(status = 'WIN', reason = null) {
      const completed = originalCompleteCycle(status, reason);
      try { if (completed?.id) finalizeCycle(completed); } catch (err) { console.error(`[${VERSION}] completion capture failed`, err); }
      return completed;
    };

    if (typeof cp.abortActiveCycle === 'function') {
      const originalAbort = cp.abortActiveCycle.bind(cp);
      cp.abortActiveCycle = function(reason = 'Stopped before confirmed win') {
        const completed = originalAbort(reason);
        try { if (completed?.id) finalizeCycle(completed); } catch (err) { console.error(`[${VERSION}] abort capture failed`, err); }
        return completed;
      };
    }

    cp.__entryTickDNAV2Hooked = true;
    lifecycleHookInstalled = true;
    console.info(`[${VERSION}] direct cycle lifecycle hook installed`);
    return true;
  }

  function poll() {
    if (!ready) return render();
    const cp=cyclePerformance(); if (!cp) return render();
    installLifecycleHook();
    const s=loadStore(); if (!s.armed && !s.completedAt) return render();
    const cur=currentCycle(cp);
    if (cur?.id && String(cur.status||'ACTIVE').toUpperCase()==='ACTIVE') {
      if (String(activeCycleId||'')!==String(cur.id)) { startCycle(cur); activeCycleId=String(cur.id); }
    }
    const hist=cycleHistory(cp); if (hist.length!==lastHistorySize) { lastHistorySize=hist.length; for (const row of hist) if (row?.id && recById(loadStore(),row.id) && !recById(loadStore(),row.id).finalized) finalizeCycle(row); }
    if (cur?.id && String(cur.status||'').toUpperCase()!=='ACTIVE' && recById(loadStore(),cur.id)) finalizeCycle(cur);
    render();
  }
  function onTick(ev) {
    const raw=ev?.detail; if (!raw || !Number.isFinite(Number(raw.quote))) return;
    const row=enrich(raw); row.lastDigit=lastDigit(row); row.adjacentRepeats=adjacentRepeats(row);
    liveTicks.push(row); if (liveTicks.length>MAX_BUFFER) liveTicks=liveTicks.slice(-MAX_BUFFER);
  }

  function summary(s) {
    const rows=s.cycles.filter(r=>r.finalized && r.outcome);
    const tails=rows.filter(r=>r.outcome.reached15===1);
    const high=rows.filter(r=>r.frozenEntryRisk?.band==='HIGH');
    const highTails=high.filter(r=>r.outcome.reached15===1);
    const accepted=rows.filter(r=>r.frozenEntryRisk?.shadowAction!=='SKIP_CANDIDATE');
    const acceptedTails=accepted.filter(r=>r.outcome.reached15===1);
    return {
      done:rows.length,tails:tails.length,baseline:rows.length?tails.length/rows.length:0,
      highN:high.length,highTails:highTails.length,highTailRate:high.length?highTails.length/high.length:0,
      tailCapture:tails.length?highTails.length/tails.length:0,
      falseRejects:high.length-highTails.length,
      rejectRate:rows.length?high.length/rows.length:0,
      acceptanceRate:rows.length?accepted.length/rows.length:0,
      residualTailRate:accepted.length?acceptedTails.length/accepted.length:0,
      acceptedN:accepted.length,acceptedTails:acceptedTails.length
    };
  }

  function arm() {
    try {
      const mode = accountMode();
      if (mode !== 'DEMO') {
        statusEl.textContent = `ARM BLOCKED · account mode=${mode}`;
        statusEl.style.color = '#f87171';
        alert(`Entry Tick DNA V2 shadow cohort can only be armed on Demo/Virtual. Current detected mode: ${mode}.`);
        return false;
      }
      const s=loadStore();
      if (s.armed) { render(); return true; }
      if (s.cycles.length && !s.completedAt) {
        alert('This shadow cohort already contains data. Reset first to start a completely fresh cohort.');
        return false;
      }
      if (s.completedAt) {
        alert('This cohort is complete. Export it, then reset before starting another cohort.');
        return false;
      }
      s.armed=true;
      s.armedAt=new Date().toISOString();
      s.symbolAtArm=currentSymbol();
      s.frozenModel=clone(FROZEN_MODEL);
      saveStore(s);
      persistenceState = 'armed-saving';
      render();
      writeChain.then(() => { persistenceState = 'ready'; render(); }).catch(() => render());
      console.info(`[${VERSION}] ARMED`, { symbol: s.symbolAtArm, mode });
      return true;
    } catch (err) {
      persistenceState = 'arm-error';
      persistenceError = String(err?.message || err);
      console.error(`[${VERSION}] ARM failed`, err);
      try { alert('Entry Tick DNA ARM error: ' + (err?.message || err)); } catch (_) {}
      render();
      return false;
    }
  }
  async function reset() {
    if (!confirm('Reset Entry Tick DNA V2 shadow cohort? Export first if you need the data.')) return;
    await idbDelete(); cache=emptyStore(); activeCycleId=null; saveStore(cache); render();
  }
  function exportData() {
    const s=loadStore(); const blob=new Blob([JSON.stringify(s,null,2)],{type:'application/json'}); const a=document.createElement('a');
    a.href=URL.createObjectURL(blob); a.download=`entry-tick-dna-v2-shadow-${s.symbolAtArm||currentSymbol()}-${new Date().toISOString().replace(/[:.]/g,'-')}.json`; a.click(); setTimeout(()=>URL.revokeObjectURL(a.href),1000);
  }

  function setMinimized(v) { if (!body) return; body.style.display=v?'none':'block'; localStorage.setItem(MIN_KEY,v?'1':'0'); }
  function ensurePanel() {
    if (panel && document.body.contains(panel)) return;
    panel=document.createElement('section'); panel.id='entry-tick-dna-v2-panel';
    panel.style.cssText='position:fixed;right:12px;bottom:12px;z-index:2147483602;width:380px;max-width:calc(100vw - 24px);max-height:630px;background:#0b1020;border:1px solid #7c3aed;border-radius:12px;box-shadow:0 12px 35px rgba(0,0,0,.45);color:#e5e7eb;font-family:Inter,Arial,sans-serif;overflow:hidden';
    const head=document.createElement('div'); head.style.cssText='height:48px;display:flex;align-items:center;gap:8px;padding:0 10px;background:#17112c;border-bottom:1px solid rgba(255,255,255,.08)';
    const title=document.createElement('div'); title.style.cssText='flex:1;min-width:0'; title.innerHTML='<div style="font-size:12px;font-weight:900">Entry Tick DNA V2 · SHADOW</div><div style="font-size:9px;color:#c4b5fd">T0 ONLY · FROZEN FILTER · NEW 100-CYCLE COHORT</div>';
    const min=document.createElement('button'); min.textContent='−'; min.style.cssText='width:28px;height:28px;border-radius:7px;border:1px solid #334155;background:#111827;color:#fff;cursor:pointer';
    body=document.createElement('div'); body.style.cssText='padding:10px;max-height:580px;overflow:auto';
    statusEl=document.createElement('div'); statusEl.style.cssText='font-size:12px;font-weight:800;margin-bottom:8px';
    detailEl=document.createElement('div'); detailEl.style.cssText='font-size:11px;line-height:1.5;color:#cbd5e1';
    const controls=document.createElement('div'); controls.style.cssText='display:flex;gap:6px;flex-wrap:wrap;margin-top:10px';
    const mk=(label,bg)=>{const b=document.createElement('button');b.type='button';b.textContent=label;b.style.cssText=`padding:7px 9px;border:0;border-radius:7px;background:${bg};color:white;font-size:10px;font-weight:900;cursor:pointer`;return b;};
    armBtn=mk('ARM FRESH 100-CYCLE SHADOW','#7c3aed'); exportBtn=mk('EXPORT JSON','#047857'); resetBtn=mk('RESET','#7f1d1d');
    armBtn.addEventListener('click', (e)=>{ e.preventDefault(); e.stopPropagation(); arm(); }); exportBtn.addEventListener('click',(e)=>{e.preventDefault();exportData();}); resetBtn.addEventListener('click',(e)=>{e.preventDefault();reset();}); min.addEventListener('click',(e)=>{e.preventDefault();setMinimized(body.style.display!=='none');});
    controls.append(armBtn,exportBtn,resetBtn); body.append(statusEl,detailEl,controls); head.append(title,min); panel.append(head,body); document.body.appendChild(panel);
    setMinimized(localStorage.getItem(MIN_KEY)==='1');
  }
  function render() {
    ensurePanel(); const s=loadStore(), x=summary(s);
    statusEl.style.color=s.completedAt?'#4ade80':s.armed?'#38bdf8':'#fbbf24';
    statusEl.textContent=s.completedAt?`COMPLETE · ${x.done}/${TARGET_CYCLES}`:s.armed?`ARMED · ${x.done}/${TARGET_CYCLES} finalized`:`NOT ARMED · ${isDemoAccount()?'Demo verified':'Demo not verified'}`;
    const active=activeCycleId?recById(s,activeCycleId):null; const risk=active?.frozenEntryRisk;
    detailEl.innerHTML=`
      <div><b>Frozen rule:</b> adjacent repeats ≥1 <b>AND</b> 25-tick drift &gt;0 → HIGH / shadow SKIP</div>
      <div><b>Discovery:</b> 7/11 HIGH entries reached ≥15 (63.6%); baseline 22/96 (22.9%)</div>
      <div><b>Storage:</b> ${persistenceState}${persistenceError?` · <span style="color:#fca5a5">${persistenceError}</span>`:''}</div>
      <div><b>Cycle hook:</b> ${lifecycleHookInstalled?'CONNECTED':'waiting for bot lifecycle'}</div>
      <div><b>Last captured cycle:</b> ${lastCapturedCycleText || '—'}</div>
      <hr style="border:0;border-top:1px solid #2e2445;margin:8px 0">
      <div><b>Overall ≥15:</b> ${x.done?`${x.tails}/${x.done} · ${(100*x.baseline).toFixed(1)}%`:'—'}</div>
      <div><b>HIGH shadow risk:</b> ${x.highN?`${x.highTails}/${x.highN} · ${(100*x.highTailRate).toFixed(1)}%`:'—'}</div>
      <div><b>Tail capture:</b> ${x.tails?`${x.highTails}/${x.tails} · ${(100*x.tailCapture).toFixed(1)}%`:'—'}</div>
      <div><b>Rejected if active:</b> ${x.done?`${x.highN}/${x.done} · ${(100*x.rejectRate).toFixed(1)}%`:'—'}</div>
      <div><b>False rejects:</b> ${x.done?x.falseRejects:'—'}</div>
      <div><b>Accepted entries:</b> ${x.done?`${x.acceptedN}/${x.done} · ${(100*x.acceptanceRate).toFixed(1)}%`:'—'}</div>
      <div><b>Residual ≥15 if HIGH skipped:</b> ${x.acceptedN?`${x.acceptedTails}/${x.acceptedN} · ${(100*x.residualTailRate).toFixed(1)}%`:'—'}</div>
      <hr style="border:0;border-top:1px solid #2e2445;margin:8px 0">
      ${risk?`<div><b>Current entry:</b> ${risk.band} · ${risk.score}/100 · <b>${risk.shadowAction}</b></div><div>adjRepeats=${risk.features.adjacentRepeats} · drift25=${Number.isFinite(risk.features.w25MeanQuoteDelta)?risk.features.w25MeanQuoteDelta.toFixed(6):'n/a'} · digit=${risk.features.targetDigit}</div>`:'<div><b>Current entry:</b> waiting</div>'}
      <div style="margin-top:6px;color:#fbbf24"><b>SHADOW ONLY:</b> this panel never blocks or changes a trade. It measures what the frozen filter would have done.</div>`;
    armBtn.disabled=s.armed||!!s.completedAt; armBtn.style.opacity=armBtn.disabled?'.45':'1';
  }

  window.addEventListener('digitmatchstar:tick',onTick);
  window.EntryTickDNAV2=Object.freeze({version:VERSION,model:()=>clone(FROZEN_MODEL),store:()=>clone(loadStore()),summary:()=>clone(summary(loadStore())),export:exportData,arm,reset,accountMode});

  async function boot() { ensurePanel(); render(); await initPersistence(); installLifecycleHook(); render(); setInterval(poll,POLL_MS); console.info(`[${VERSION}] loaded · shadow-only`); }
  if (document.readyState==='loading') document.addEventListener('DOMContentLoaded',()=>boot().catch(console.error),{once:true}); else boot().catch(console.error);
})();
