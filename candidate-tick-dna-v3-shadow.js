/*
 * DigitMatchStar Candidate Tick DNA V3.7
 * FORWARD-ONLY · EXACT CANDIDATE TICK · DEMO-ONLY · SHADOW-ONLY
 *
 * Scientific target:
 *   At the exact pre-purchase tick, define candidateDigit = that tick's last digit.
 *   Then observe only future ticks and measure the forward recurrence gap of that same digit.
 *
 * This module NEVER changes, blocks, sizes, stops, or places a trade.
 */
(() => {
  'use strict';

  const VERSION = 'CANDIDATE-TICK-DNA-V3.7-EXACT-ALIGNED-CLOUD';
  const DB_NAME = 'DigitMatchStarTickDNA';
  const DB_VERSION = 1;
  const DB_STORE = 'validation';
  const DB_RECORD_KEY = 'candidate-tick-dna-v3-aligned-r10';
  const TARGET = 100;
  const MAX_FORWARD = 20;
  const CONTEXT = 100;
  const PANEL_KEY = 'matchstar_panel_min_candidate_tick_dna_v37';

  let cache = null;
  let ready = false;
  let liveTicks = [];
  let active = null;
  let panel, body, statusEl, detailEl, armBtn, exportBtn, resetBtn;
  let cloudStatus = 'starting';

  const clone = v => { try { return JSON.parse(JSON.stringify(v)); } catch (_) { return null; } };
  const currentSymbol = () => document.getElementById('symbol')?.value || window.tickFormat?.symbol || 'R_10';
  const accountMode = () => {
    const stored = String(localStorage.getItem('selectedAccountMode') || '').toUpperCase();
    if (stored === 'DEMO' || stored === 'REAL') return stored;
    const t = document.getElementById('accTypeToggle');
    if (t) return t.checked ? 'REAL' : 'DEMO';
    return 'UNKNOWN';
  };

  function emptyStore() {
    return {
      schema: 'DIGITMATCHSTAR_CANDIDATE_TICK_DNA_V3_ALIGNED',
      version: VERSION,
      createdAt: new Date().toISOString(),
      armed: false,
      armedAt: null,
      completedAt: null,
      targetCandidates: TARGET,
      symbolAtArm: null,
      definition: {
        candidateDigit: 'exact last digit of the exact tick presented to executeTrade before first purchase',
        outcome: 'forward recurrence gap of that same digit on future ticks only',
        tail15: 'forwardGap >= 15, or no recurrence through future tick 20'
      },
      candidates: []
    };
  }

  function normalize(x) {
    const base = emptyStore();
    if (!x || typeof x !== 'object') return base;
    return Object.assign(base, x, {
      schema: base.schema,
      version: VERSION,
      candidates: Array.isArray(x.candidates) ? x.candidates : []
    });
  }

  function openDB() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        if (!req.result.objectStoreNames.contains(DB_STORE)) req.result.createObjectStore(DB_STORE);
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error || new Error('IndexedDB open failed'));
    });
  }
  async function idbGet() {
    const db = await openDB();
    try {
      return await new Promise((resolve, reject) => {
        const tx = db.transaction(DB_STORE, 'readonly');
        const req = tx.objectStore(DB_STORE).get(DB_RECORD_KEY);
        req.onsuccess = () => resolve(req.result || null);
        req.onerror = () => reject(req.error || new Error('IndexedDB read failed'));
      });
    } finally { db.close(); }
  }
  async function idbPut(v) {
    const db = await openDB();
    try {
      await new Promise((resolve, reject) => {
        const tx = db.transaction(DB_STORE, 'readwrite');
        tx.objectStore(DB_STORE).put(v, DB_RECORD_KEY);
        tx.oncomplete = resolve;
        tx.onerror = () => reject(tx.error || new Error('IndexedDB write failed'));
      });
    } finally { db.close(); }
  }
  async function idbDelete() {
    const db = await openDB();
    try {
      await new Promise((resolve, reject) => {
        const tx = db.transaction(DB_STORE, 'readwrite');
        tx.objectStore(DB_STORE).delete(DB_RECORD_KEY);
        tx.oncomplete = resolve;
        tx.onerror = () => reject(tx.error || new Error('IndexedDB delete failed'));
      });
    } finally { db.close(); }
  }

  function saveStore(s) {
    cache = normalize(s);
    idbPut(cache).then(() => {
      window.DMSResearchCloud?.syncKey?.(DB_RECORD_KEY).catch(() => {});
    }).catch(err => console.error('[Candidate DNA] IDB save failed', err));
  }
  function store() { if (!cache) cache = emptyStore(); return cache; }

  function formatQuote(raw) {
    if (!raw) return null;
    if (typeof raw.formattedQuote === 'string' && raw.formattedQuote) return raw.formattedQuote;
    if (typeof raw.formattedPrice === 'string' && raw.formattedPrice) return raw.formattedPrice;
    const q = Number(raw.quote ?? raw.price ?? raw.raw?.quote);
    if (!Number.isFinite(q)) return null;
    const p = Number.isFinite(Number(raw.pip_size)) ? Number(raw.pip_size)
      : Number.isFinite(Number(raw.decimals)) ? Number(raw.decimals)
      : Number.isFinite(Number(raw.raw?.pip_size)) ? Number(raw.raw.pip_size)
      : 3;
    return q.toFixed(p);
  }
  function digitOf(raw) {
    const explicit = Number(raw?.digit);
    if (Number.isInteger(explicit) && explicit >= 0 && explicit <= 9) return explicit;
    const s = formatQuote(raw);
    if (!s) return null;
    const m = s.match(/(\d)\D*$/);
    return m ? Number(m[1]) : null;
  }
  function quoteOf(raw) { return Number(raw?.quote ?? raw?.price ?? raw?.raw?.quote); }
  function epochOf(raw) { return Number(raw?.epoch ?? raw?.raw?.epoch) || null; }
  function canonical(raw) {
    const q = quoteOf(raw);
    if (!Number.isFinite(q)) return null;
    const formattedQuote = formatQuote(raw);
    const d = digitOf(raw);
    return {
      symbol: raw?.symbol || raw?.raw?.symbol || currentSymbol(),
      quote: q,
      formattedQuote,
      epoch: epochOf(raw),
      receivedAt: Number(raw?.receivedAt || raw?.time || Date.now()),
      pip_size: Number.isFinite(Number(raw?.pip_size)) ? Number(raw.pip_size)
        : Number.isFinite(Number(raw?.raw?.pip_size)) ? Number(raw.raw.pip_size)
        : Number.isFinite(Number(raw?.decimals)) ? Number(raw.decimals) : 3,
      digit: d
    };
  }
  function quoteDigits(row) {
    return String(row?.formattedQuote || '').replace(/[^0-9]/g, '').split('').map(Number);
  }
  function adjacentRepeats(row) {
    const ds = quoteDigits(row); let n = 0;
    for (let i = 1; i < ds.length; i++) if (ds[i] === ds[i-1]) n++;
    return n;
  }
  function meanDelta(rows, n) {
    const xs = rows.slice(-n).map(r => Number(r.quote)).filter(Number.isFinite);
    if (xs.length < 2) return null;
    let s = 0; for (let i=1;i<xs.length;i++) s += xs[i]-xs[i-1];
    return s/(xs.length-1);
  }
  function entropy(rows, n) {
    const ds = rows.slice(-n).map(r => Number(r.digit)).filter(Number.isInteger);
    if (!ds.length) return null;
    const c = Array(10).fill(0); ds.forEach(d => c[d]++);
    let h=0; for (const v of c) if (v) { const p=v/ds.length; h -= p*Math.log2(p); }
    return h;
  }
  function freq(rows,n,d) {
    const ds=rows.slice(-n).map(r=>Number(r.digit)).filter(Number.isInteger);
    return ds.length ? ds.filter(x=>x===d).length/ds.length : null;
  }

  function entryFeatures(entry, context) {
    const d = entry.digit;
    return {
      adjacentRepeats: adjacentRepeats(entry),
      w25MeanQuoteDelta: meanDelta(context,25),
      candidateFreq5: freq(context,5,d),
      candidateFreq10: freq(context,10,d),
      candidateFreq25: freq(context,25,d),
      candidateFreq50: freq(context,50,d),
      candidateFreq100: freq(context,100,d),
      entropy5: entropy(context,5), entropy10: entropy(context,10), entropy25: entropy(context,25),
      immediateQuoteDelta: context.length>=2 ? Number(context[context.length-1].quote)-Number(context[context.length-2].quote) : null,
      candidateLastDigit: d,
      alignmentGuaranteed: true
    };
  }

  function captureCandidate(rawTick) {
    try {
      const s = store();
      if (!s.armed || s.completedAt || s.candidates.filter(x=>x.finalized).length >= TARGET) return false;
      if (active && !active.finalized) return false;
      const entry = canonical(rawTick);
      if (!entry || !Number.isInteger(entry.digit)) return false;
      if (s.symbolAtArm && entry.symbol !== s.symbolAtArm) return false;

      // Ensure exact candidate tick is last member of the T0 context.
      let context = liveTicks.filter(t=>t.symbol===entry.symbol).slice(-(CONTEXT-1));
      const last = context[context.length-1];
      if (!last || !entry.epoch || Number(last.epoch)!==Number(entry.epoch)) context.push(entry);
      else context[context.length-1] = entry;
      context = context.slice(-CONTEXT);

      const rec = {
        cohortIndex: s.candidates.length + 1,
        id: `${Date.now()}-${Math.random().toString(36).slice(2,8)}`,
        symbol: entry.symbol,
        capturedAt: new Date().toISOString(),
        entryEpoch: entry.epoch,
        entryTick: clone(entry),
        candidateDigit: entry.digit,
        targetDigit: entry.digit,
        entryTargetMatchesLastDigit: true,
        contextN: context.length,
        entryFeatures: entryFeatures(entry, context),
        forwardTicksObserved: 0,
        forwardGap: null,
        recurrenceEpoch: null,
        tail15: null,
        noRecurrenceBy20: false,
        finalized: false
      };
      s.candidates.push(rec);
      active = rec;
      saveStore(s);
      render();
      return true;
    } catch (err) {
      console.error('[Candidate DNA] capture failed', err);
      return false;
    }
  }

  function onTick(ev) {
    const row = canonical(ev?.detail);
    if (!row) return;
    liveTicks.push(row);
    if (liveTicks.length > 600) liveTicks = liveTicks.slice(-600);

    if (!active || active.finalized) return;
    // Strictly future ticks only.
    if (active.entryEpoch && row.epoch && Number(row.epoch) <= Number(active.entryEpoch)) return;

    active.forwardTicksObserved += 1;
    if (Number(row.digit) === Number(active.candidateDigit)) {
      active.forwardGap = active.forwardTicksObserved;
      active.recurrenceEpoch = row.epoch;
      active.tail15 = active.forwardGap >= 15 ? 1 : 0;
      finalizeActive(false);
      return;
    }
    if (active.forwardTicksObserved >= MAX_FORWARD) {
      active.forwardGap = null;
      active.tail15 = 1;
      active.noRecurrenceBy20 = true;
      finalizeActive(true);
    }
  }

  function finalizeActive(noRecurrence) {
    if (!active) return;
    const s = store();
    const rec = s.candidates.find(x=>x.id===active.id);
    if (!rec) { active=null; return; }
    Object.assign(rec, clone(active), {
      finalized: true,
      finalizedAt: new Date().toISOString(),
      noRecurrenceBy20: !!noRecurrence
    });
    const done = s.candidates.filter(x=>x.finalized).length;
    if (done >= TARGET) { s.completedAt = new Date().toISOString(); s.armed = false; }
    active = null;
    saveStore(s);
    render();
  }

  function summary() {
    const rows = store().candidates.filter(x=>x.finalized);
    const tails = rows.filter(x=>x.tail15===1);
    const aligned = rows.filter(x=>x.entryTargetMatchesLastDigit===true);
    const gaps = rows.map(x=>Number(x.forwardGap)).filter(Number.isFinite);
    return {
      done: rows.length,
      tails: tails.length,
      tailRate: rows.length ? tails.length/rows.length : 0,
      aligned: aligned.length,
      alignmentRate: rows.length ? aligned.length/rows.length : 0,
      meanGap: gaps.length ? gaps.reduce((a,b)=>a+b,0)/gaps.length : null
    };
  }

  async function arm() {
    if (accountMode() !== 'DEMO') { alert('Candidate Tick DNA V3.7 is DEMO-only.'); return false; }
    const s = store();
    if (s.candidates.length && !s.completedAt) { alert('This cohort already has data. Reset first for a clean 100-candidate cohort.'); return false; }
    if (s.completedAt) { alert('This cohort is complete. Export it, then reset for a new cohort.'); return false; }
    s.armed=true; s.armedAt=new Date().toISOString(); s.symbolAtArm=currentSymbol(); saveStore(s); render(); return true;
  }
  async function reset() {
    if (!confirm('Reset Candidate Tick DNA V3.7 cohort? Export first if you need it.')) return;
    await idbDelete(); cache=emptyStore(); active=null; await idbPut(cache); render();
  }
  function exportData() {
    const s=store(); const blob=new Blob([JSON.stringify(s,null,2)],{type:'application/json'});
    const a=document.createElement('a'); a.href=URL.createObjectURL(blob);
    a.download=`candidate-tick-dna-v3-aligned-${s.symbolAtArm||currentSymbol()}-${new Date().toISOString().replace(/[:.]/g,'-')}.json`;
    a.click(); setTimeout(()=>URL.revokeObjectURL(a.href),1000);
  }

  function ensurePanel() {
    if (panel && document.body.contains(panel)) return;
    panel=document.createElement('section'); panel.id='candidate-tick-dna-v37-panel';
    panel.style.cssText='position:fixed;right:12px;bottom:12px;z-index:2147483603;width:395px;max-width:calc(100vw - 24px);max-height:650px;background:#07151a;border:1px solid #06b6d4;border-radius:12px;box-shadow:0 12px 35px rgba(0,0,0,.45);color:#e5e7eb;font-family:Inter,Arial,sans-serif;overflow:hidden';
    const head=document.createElement('div'); head.style.cssText='height:48px;display:flex;align-items:center;gap:8px;padding:0 10px;background:#082f49;border-bottom:1px solid rgba(255,255,255,.08)';
    const title=document.createElement('div'); title.style.cssText='flex:1'; title.innerHTML='<div style="font-size:12px;font-weight:900">Candidate Tick DNA V3.7 · EXACT ALIGNMENT</div><div style="font-size:9px;color:#a5f3fc">T0 ONLY · FORWARD RECURRENCE · SHADOW · CLOUD SYNC</div>';
    const min=document.createElement('button'); min.type='button'; min.textContent='−'; min.style.cssText='width:28px;height:28px;border-radius:7px;border:1px solid #334155;background:#111827;color:#fff';
    body=document.createElement('div'); body.style.cssText='padding:10px;max-height:590px;overflow:auto';
    statusEl=document.createElement('div'); statusEl.style.cssText='font-size:12px;font-weight:800;margin-bottom:8px';
    detailEl=document.createElement('div'); detailEl.style.cssText='font-size:11px;line-height:1.5;color:#cbd5e1';
    const controls=document.createElement('div'); controls.style.cssText='display:flex;gap:6px;flex-wrap:wrap;margin-top:10px';
    const mk=(txt,bg)=>{const b=document.createElement('button');b.type='button';b.textContent=txt;b.style.cssText=`padding:7px 9px;border:0;border-radius:7px;background:${bg};color:white;font-size:10px;font-weight:900`;return b;};
    armBtn=mk('ARM FRESH 100','#0891b2'); exportBtn=mk('EXPORT JSON','#047857'); resetBtn=mk('RESET','#7f1d1d');
    armBtn.onclick=e=>{e.preventDefault();arm();}; exportBtn.onclick=e=>{e.preventDefault();exportData();}; resetBtn.onclick=e=>{e.preventDefault();reset();};
    min.onclick=e=>{e.preventDefault();const hide=body.style.display!=='none';body.style.display=hide?'none':'block';localStorage.setItem(PANEL_KEY,hide?'1':'0');min.textContent=hide?'+':'−';};
    controls.append(armBtn,exportBtn,resetBtn); body.append(statusEl,detailEl,controls); head.append(title,min); panel.append(head,body); document.body.appendChild(panel);
    if(localStorage.getItem(PANEL_KEY)==='1'){body.style.display='none';min.textContent='+';}
  }
  function render() {
    ensurePanel(); const s=store(), x=summary();
    statusEl.style.color=s.completedAt?'#4ade80':s.armed?'#22d3ee':'#fbbf24';
    statusEl.textContent=s.completedAt?`COMPLETE · ${x.done}/${TARGET}`:s.armed?`ARMED · ${x.done}/${TARGET} finalized`:'NOT ARMED';
    const a=active;
    detailEl.innerHTML=`
      <div><b>Definition:</b> target digit = exact last digit of the exact candidate tick before first purchase.</div>
      <div><b>Outcome:</b> future recurrence gap of that same digit; no trading outcome is used.</div>
      <div><b>Cloud:</b> ${cloudStatus}</div>
      <hr style="border:0;border-top:1px solid #164e63;margin:8px 0">
      <div><b>Alignment:</b> ${x.done?`${x.aligned}/${x.done} · ${(100*x.alignmentRate).toFixed(1)}%`:'—'} ${x.done&&x.alignmentRate===1?'✓':''}</div>
      <div><b>Tail ≥15:</b> ${x.done?`${x.tails}/${x.done} · ${(100*x.tailRate).toFixed(1)}%`:'—'}</div>
      <div><b>Mean observed recurrence gap:</b> ${x.meanGap===null?'—':x.meanGap.toFixed(2)}</div>
      <div><b>Active candidate:</b> ${a?`digit ${a.candidateDigit} · future ticks ${a.forwardTicksObserved}/${MAX_FORWARD}`:'waiting'}</div>
      <div><b>Last candidate:</b> ${s.candidates.length?`#${s.candidates[s.candidates.length-1].cohortIndex} · digit ${s.candidates[s.candidates.length-1].candidateDigit}`:'—'}</div>
      <div style="margin-top:6px;color:#fbbf24"><b>SHADOW ONLY:</b> this module does not alter the bot's chosen trade digit or execution.</div>`;
    armBtn.disabled=s.armed||!!s.completedAt; armBtn.style.opacity=armBtn.disabled?'.45':'1';
  }

  window.addEventListener('digitmatchstar:tick', onTick);
  window.addEventListener('dms:research-cloud-status', ev => { cloudStatus = ev?.detail?.status || cloudStatus; render(); });

  window.CandidateTickDNAV3 = Object.freeze({
    version: VERSION,
    captureCandidate,
    store:()=>clone(store()),
    summary:()=>clone(summary()),
    arm,reset,export:exportData
  });

  async function boot() {
    ensurePanel();
    try { cache=normalize(await idbGet()); } catch (_) { cache=emptyStore(); }
    ready=true;
    try {
      await window.DMSResearchCloud?.syncKey?.(DB_RECORD_KEY);
      cache=normalize(await idbGet());
      cloudStatus=window.DMSResearchCloud?.status?.() || 'ready';
    } catch (_) { cloudStatus='local only / cloud unavailable'; }
    render();
    console.info(`[${VERSION}] loaded`);
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',()=>boot().catch(console.error),{once:true}); else boot().catch(console.error);
})();
