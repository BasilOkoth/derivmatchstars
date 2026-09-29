/* DigitMatchStar — Rise/Fall Stable Dashboard v4 — RED/GREEN
 * Presentation layer only. Uses existing DMSRiseFallLab and DMSRiseFallCloud APIs.
 * Does not change cohort definitions, research scoring, evidence thresholds, or trade logic.
 */
(() => {
  'use strict';

  const ROOT_ID = 'rf-stable-dashboard-v4';
  const OLD_PANEL_ID = 'risefall-lab-v1-panel';
  const STYLE_ID = 'rf-stable-dashboard-v4-style';
  let lastCandidateKey = null;
  let collapsed = false;
  let candidatesOpen = false;
  const POS_KEY = 'rf_stable_dashboard_v4_position';
  const WAKE_KEY = 'rf_stable_dashboard_v4_wake';
  let ownWakeLock = null;

  const $ = id => document.getElementById(id);
  const num = (v, d=0) => Number.isFinite(Number(v)) ? Number(v) : d;
  const pct = v => v == null || !Number.isFinite(Number(v)) ? '—' : `${(Number(v)*100).toFixed(2)}%`;
  const money = v => `${num(v)<0?'-':'+'}$${Math.abs(num(v)).toFixed(2)}`;
  const esc = s => String(s ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
  const lab = () => window.DMSRiseFallLab;
  const cloud = () => window.DMSRiseFallCloud;
  const snap = () => { try { return lab()?.getSnapshot?.() || null; } catch (_) { return null; } };

  function css(){
    if ($(STYLE_ID)) return;
    const st = document.createElement('style');
    st.id = STYLE_ID;
    st.textContent = `
      #${OLD_PANEL_ID}{display:none!important}
      #${ROOT_ID}{position:fixed;left:14px;top:92px;width:392px;height:min(760px,82vh);z-index:2147483000;background:#07121f;color:#e7f2fb;border:1px solid #2c4d68;border-radius:15px;box-shadow:0 18px 55px rgba(0,0,0,.48);font:12px/1.35 Inter,Arial,sans-serif;overflow:hidden;contain:layout paint}
      #${ROOT_ID} *{box-sizing:border-box}
      #${ROOT_ID}.rf-collapsed{height:48px;width:285px}
      #${ROOT_ID}.rf-collapsed .rfs-body{display:none}
      .rfs-head{height:48px;padding:8px 10px;display:flex;align-items:center;justify-content:space-between;background:linear-gradient(90deg,#0d2943,#143b58);border-bottom:1px solid #294a64;cursor:grab;user-select:none;touch-action:none}.rfs-head:active{cursor:grabbing}
      .rfs-head-title{font-weight:900;letter-spacing:.55px}.rfs-head-sub{display:block;color:#8fb1ca;font-size:10px;margin-top:2px}
      .rfs-head-actions{display:flex;gap:6px}.rfs-icon{border:1px solid #3a5f7a;background:#10283e;color:#eaf5fd;border-radius:8px;width:30px;height:30px;cursor:pointer}
      .rfs-body{height:calc(100% - 48px);overflow:auto;padding:9px;scrollbar-gutter:stable;overscroll-behavior:contain}
      .rfs-grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:7px}.rfs-card{background:#0a1a29;border:1px solid #203b50;border-radius:9px;padding:7px;min-height:53px}.rfs-card span{display:block;color:#7899b4;font-size:9px}.rfs-card b{display:block;margin-top:3px;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .rfs-section{background:#0a1a29;border:1px solid #203b50;border-radius:10px;padding:8px;margin-bottom:7px}.rfs-title{font-weight:800;color:#bdd9ee;margin-bottom:6px;display:flex;align-items:center;justify-content:space-between;gap:6px}.rfs-muted{color:#7899b4;font-size:10px}.rfs-good{color:#22c55e!important;text-shadow:0 0 12px rgba(34,197,94,.18)}.rfs-bad{color:#ef4444!important;text-shadow:0 0 12px rgba(239,68,68,.16)}.rfs-warn{color:#fbbf24!important}.rfs-passbox{background:rgba(34,197,94,.12)!important;border-color:rgba(34,197,94,.55)!important}.rfs-failbox{background:rgba(239,68,68,.12)!important;border-color:rgba(239,68,68,.55)!important}.rfs-neutralbox{background:#071522!important;border-color:#203b50!important}.rfs-row2{display:grid;grid-template-columns:1fr 1fr;gap:6px}.rfs-metric{background:#071522;border-radius:8px;padding:6px}.rfs-metric span{display:block;color:#7899b4;font-size:9px}.rfs-metric b{display:block;margin-top:2px}
      .rfs-actions{display:grid;grid-template-columns:repeat(2,1fr);gap:6px}.rfs-actions.three{grid-template-columns:repeat(3,1fr)}.rfs-btn{border:1px solid #355a75;background:#102a41;color:#edf7ff;border-radius:8px;padding:7px 6px;font-weight:800;font-size:10px;cursor:pointer;min-height:34px}.rfs-btn:hover{background:#153a58}.rfs-btn.active{background:#174d71;border-color:#5aa4d4}.rfs-btn.good{background:#14532d;border-color:#22c55e;color:#dcfce7}.rfs-btn.good:hover{background:#166534}.rfs-btn.danger{background:#7f1d1d;border-color:#ef4444;color:#fee2e2}.rfs-btn.danger:hover{background:#991b1b}.rfs-btn:disabled{opacity:.45;cursor:not-allowed}
      .rfs-gates{display:grid;grid-template-columns:1fr auto;gap:4px 8px}.rfs-gates span{color:#8ca8bc}.rfs-gates b{text-align:right}.rfs-candidate-list{display:none;margin-top:7px}.rfs-candidate-list.open{display:block}.rfs-cand{padding:7px 8px;border:1px solid rgba(120,160,190,.12);border-radius:8px;margin-top:5px;background:#071522}.rfs-cand.pass{background:rgba(34,197,94,.11);border-color:rgba(34,197,94,.55)}.rfs-cand.fail{background:rgba(239,68,68,.11);border-color:rgba(239,68,68,.55)}.rfs-cand.wait{background:rgba(251,191,36,.08);border-color:rgba(251,191,36,.35)}.rfs-cand:first-child{border-top:0}.rfs-cand strong{display:block;font-size:10px}.rfs-cand small{display:block;color:#7899b4;margin-top:2px}
      .rfs-statusline{font-size:10px;color:#8ba8bd;margin-top:5px;min-height:14px;word-break:break-word}
      .rfs-cloudgrid{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:6px}.rfs-cloudgrid .rfs-metric{min-height:47px}
      @media(max-width:520px){#${ROOT_ID}{left:5px;right:5px;top:74px;width:auto;height:78vh}.rfs-grid4{grid-template-columns:repeat(2,1fr)}#${ROOT_ID}.rf-collapsed{right:auto;width:285px}}
    `;
    document.head.appendChild(st);
  }

  function make(){
    if ($(ROOT_ID)) return;
    css();
    const root = document.createElement('div');
    root.id = ROOT_ID;
    root.innerHTML = `
      <div class="rfs-head">
        <div><div class="rfs-head-title">RISE / FALL LAB · RED/GREEN</div><span class="rfs-head-sub" id="rfs-head-sub">R_10 · waiting for lab…</span></div>
        <div class="rfs-head-actions"><button class="rfs-icon" id="rfs-export-top" title="Export report">⇩</button><button class="rfs-icon" id="rfs-min" title="Minimize">−</button></div>
      </div>
      <div class="rfs-body">
        <div class="rfs-grid4">
          <div class="rfs-card"><span>Forward ticks</span><b id="rfs-ticks">—</b></div>
          <div class="rfs-card"><span>Feed</span><b id="rfs-feed">—</b></div>
          <div class="rfs-card"><span>Mode</span><b id="rfs-mode">—</b></div>
          <div class="rfs-card"><span>Cohort</span><b id="rfs-cohort">—</b></div>
        </div>

        <div class="rfs-section">
          <div class="rfs-title"><span>CURRENT SIGNAL</span><span id="rfs-signal-status" class="rfs-muted">—</span></div>
          <div class="rfs-row2">
            <div class="rfs-metric"><span>Side</span><b id="rfs-side">—</b></div>
            <div class="rfs-metric"><span>Win rate</span><b id="rfs-wr">—</b></div>
            <div class="rfs-metric"><span>Forward N</span><b id="rfs-n">—</b></div>
            <div class="rfs-metric"><span>Lower 95%</span><b id="rfs-low">—</b></div>
          </div>
          <div class="rfs-statusline" id="rfs-candidate">No signal yet.</div>
        </div>

        <div class="rfs-section">
          <div class="rfs-title">AUTO CONTROL <span id="rfs-auto-ready" class="rfs-warn">WAITING</span></div>
          <div class="rfs-actions three" style="margin-bottom:6px">
            <button class="rfs-btn" id="rfs-mode-shadow">SHADOW</button><button class="rfs-btn" id="rfs-mode-demo">DEMO</button><button class="rfs-btn" id="rfs-mode-real">REAL</button>
          </div>
          <div class="rfs-actions three" style="margin-bottom:6px">
            <button class="rfs-btn" id="rfs-side-auto">AUTO</button><button class="rfs-btn good" id="rfs-side-rise">RISE</button><button class="rfs-btn danger" id="rfs-side-fall">FALL</button>
          </div>
          <div class="rfs-actions">
            <button class="rfs-btn good" id="rfs-run">START AUTO</button><button class="rfs-btn" id="rfs-screen">KEEP SCREEN ON</button>
          </div>
          <div class="rfs-gates" style="margin-top:8px">
            <span>Forward support ≥ 300</span><b id="rfs-gate-n">—</b>
            <span>Observed win rate ≥ 54%</span><b id="rfs-gate-wr">—</b>
            <span>Lower 95% ≥ break-even</span><b id="rfs-gate-low">—</b>
          </div>
          <div class="rfs-statusline" id="rfs-auto-note">AUTO remains blocked until every gate passes.</div>
        </div>

        <div class="rfs-section">
          <div class="rfs-title">MANUAL EXECUTION <span class="rfs-muted">1 tick</span></div>
          <div class="rfs-actions"><button class="rfs-btn good" id="rfs-trade-rise">TRADE RISE</button><button class="rfs-btn danger" id="rfs-trade-fall">TRADE FALL</button></div>
          <div class="rfs-grid4" style="margin-top:7px;margin-bottom:0">
            <div class="rfs-card"><span>Trades</span><b id="rfs-contracts">0</b></div>
            <div class="rfs-card"><span>Wins</span><b id="rfs-wins">0</b></div>
            <div class="rfs-card"><span>Losses</span><b id="rfs-losses">0</b></div>
            <div class="rfs-card"><span>P&L</span><b id="rfs-pnl">+$0.00</b></div>
          </div>
        </div>

        <div class="rfs-section">
          <div class="rfs-title">CLOUD BACKUP <span id="rfs-cloud-status" class="rfs-muted">—</span></div>
          <div class="rfs-cloudgrid"><div class="rfs-metric"><span>This device</span><b id="rfs-local-ticks">—</b></div><div class="rfs-metric"><span>Cloud</span><b id="rfs-cloud-ticks">—</b></div></div>
          <div class="rfs-actions"><button class="rfs-btn" id="rfs-cloud-check">CHECK CLOUD</button><button class="rfs-btn" id="rfs-cloud-sync">SYNC NOW</button></div>
          <div class="rfs-actions" style="margin-top:6px"><button class="rfs-btn danger" id="rfs-cloud-restore" style="display:none">RESTORE CLOUD</button><button class="rfs-btn danger" id="rfs-cloud-claim" style="display:none">TAKE OVER</button></div>
          <div class="rfs-statusline" id="rfs-cloud-msg">Waiting for cloud module…</div>
        </div>

        <div class="rfs-section">
          <div class="rfs-title">REPORT & CANDIDATES <button class="rfs-btn" id="rfs-toggle-cands" style="padding:4px 7px;min-height:26px">SHOW TOP 5</button></div>
          <div class="rfs-actions"><button class="rfs-btn good" id="rfs-export">EXPORT JSON REPORT</button><button class="rfs-btn" id="rfs-refresh">REFRESH VIEW</button></div>
          <div class="rfs-candidate-list" id="rfs-cands"></div>
        </div>
      </div>`;
    document.body.appendChild(root);
    restorePosition();
    bind();
    enableDrag();
  }


  function clampPosition(left, top){
    const root=$(ROOT_ID); if(!root) return {left,top};
    const w=root.offsetWidth||392, h=root.offsetHeight||48;
    const maxLeft=Math.max(0,window.innerWidth-w), maxTop=Math.max(0,window.innerHeight-Math.min(h,48));
    return {left:Math.max(0,Math.min(left,maxLeft)),top:Math.max(0,Math.min(top,maxTop))};
  }
  function savePosition(){const root=$(ROOT_ID);if(!root)return;try{localStorage.setItem(POS_KEY,JSON.stringify({left:parseFloat(root.style.left)||root.offsetLeft,top:parseFloat(root.style.top)||root.offsetTop}));}catch(_){}}
  function restorePosition(){const root=$(ROOT_ID);if(!root)return;try{const p=JSON.parse(localStorage.getItem(POS_KEY)||'null');if(p&&Number.isFinite(Number(p.left))&&Number.isFinite(Number(p.top))){const c=clampPosition(Number(p.left),Number(p.top));root.style.left=c.left+'px';root.style.top=c.top+'px';root.style.right='auto';}}catch(_){}}
  function enableDrag(){
    const root=$(ROOT_ID), head=root?.querySelector('.rfs-head'); if(!root||!head)return;
    let dragging=false, dx=0, dy=0, pointerId=null;
    head.addEventListener('pointerdown',e=>{
      if(e.target.closest('button'))return;
      dragging=true;pointerId=e.pointerId;dx=e.clientX-root.getBoundingClientRect().left;dy=e.clientY-root.getBoundingClientRect().top;
      try{head.setPointerCapture(pointerId);}catch(_){}
      e.preventDefault();
    });
    head.addEventListener('pointermove',e=>{
      if(!dragging||e.pointerId!==pointerId)return;
      const c=clampPosition(e.clientX-dx,e.clientY-dy);root.style.left=c.left+'px';root.style.top=c.top+'px';root.style.right='auto';
    });
    const end=e=>{if(!dragging)return;dragging=false;try{head.releasePointerCapture(pointerId);}catch(_){}pointerId=null;savePosition();};
    head.addEventListener('pointerup',end);head.addEventListener('pointercancel',end);
    window.addEventListener('resize',()=>{const r=root.getBoundingClientRect(),c=clampPosition(r.left,r.top);root.style.left=c.left+'px';root.style.top=c.top+'px';savePosition();});
  }

  async function requestOwnWakeLock(){
    try{localStorage.setItem(WAKE_KEY,'1');}catch(_){}
    if(!('wakeLock' in navigator)){setText('rfs-auto-note','Screen Wake Lock is not supported by this browser. Keep the tab visible or disable system sleep manually.','rfs-warn');return false;}
    try{if(ownWakeLock&&!ownWakeLock.released)return true;ownWakeLock=await navigator.wakeLock.request('screen');
      ownWakeLock.addEventListener('release',()=>{ownWakeLock=null;update();});update();return true;
    }catch(e){setText('rfs-auto-note',`Could not keep screen awake: ${e?.message||e}`,'rfs-bad');return false;}
  }
  async function releaseOwnWakeLock(){try{localStorage.removeItem(WAKE_KEY);}catch(_){};if(ownWakeLock){try{await ownWakeLock.release();}catch(_){}ownWakeLock=null;}update();}
  async function toggleWake(){
    const requested=localStorage.getItem(WAKE_KEY)==='1'||!!ownWakeLock;
    if(requested){await releaseOwnWakeLock(); try{await lab()?.releaseWakeLock?.();}catch(_){}}
    else {try{await lab()?.requestWakeLock?.();}catch(_){}; await requestOwnWakeLock();}
  }

  function setText(id, value, cls){ const el=$(id); if(!el)return; el.textContent=value; if(cls){el.classList.remove('rfs-good','rfs-bad','rfs-warn');el.classList.add(cls);} }
  function setActive(id, active){ const el=$(id); if(el)el.classList.toggle('active', !!active); }

  function bind(){
    $('rfs-min').onclick = () => { collapsed=!collapsed; $(ROOT_ID).classList.toggle('rf-collapsed',collapsed); $('rfs-min').textContent=collapsed?'□':'−'; };
    const doExport = () => lab()?.exportReport?.();
    $('rfs-export').onclick = doExport; $('rfs-export-top').onclick = doExport;
    $('rfs-refresh').onclick = update;
    $('rfs-mode-shadow').onclick = () => lab()?.setMode?.('SHADOW');
    $('rfs-mode-demo').onclick = () => lab()?.setMode?.('DEMO');
    $('rfs-mode-real').onclick = () => lab()?.setMode?.('REAL');
    $('rfs-side-auto').onclick = () => lab()?.setAutoSide?.('AUTO');
    $('rfs-side-rise').onclick = () => lab()?.setAutoSide?.('RISE');
    $('rfs-side-fall').onclick = () => lab()?.setAutoSide?.('FALL');
    $('rfs-run').onclick = () => { const s=snap(); if(!s)return; s.runner ? lab()?.stopAuto?.() : lab()?.startAuto?.(); };
    $('rfs-screen').onclick = () => toggleWake();
    $('rfs-trade-rise').onclick = () => lab()?.tradeRise?.();
    $('rfs-trade-fall').onclick = () => lab()?.tradeFall?.();
    $('rfs-cloud-check').onclick = () => cloud()?.load?.();
    $('rfs-cloud-sync').onclick = () => cloud()?.sync?.();
    $('rfs-cloud-restore').onclick = () => { if(confirm('Restore the newest cloud Rise/Fall cohort on this device? The page will reload in SHADOW mode.')) cloud()?.restore?.(); };
    $('rfs-cloud-claim').onclick = () => cloud()?.claim?.();
    $('rfs-toggle-cands').onclick = () => { candidatesOpen=!candidatesOpen; $('rfs-cands').classList.toggle('open',candidatesOpen); $('rfs-toggle-cands').textContent=candidatesOpen?'HIDE TOP 5':'SHOW TOP 5'; };
  }

  function renderCandidates(s){
    const box=$('rfs-cands'); if(!box)return;
    const cs=(s?.candidates||[]).slice(0,5);
    const key=cs.map(c=>`${c.key}:${c.forward?.n||0}:${c.forward?.winRate||''}:${c.forward?.lower95||''}`).join('|');
    if(key===lastCandidateKey)return; lastCandidateKey=key;
    box.innerHTML=cs.length?cs.map(c=>{const fn=num(c.forward?.n||c.forwardN), wr=num(c.forward?.winRate), low=num(c.forward?.lower95);const cls=(fn>=300&&wr>=.54&&low>=.5260389269)?'pass':(fn>=100&&wr<.5260389269)?'fail':'wait';return `<div class="rfs-cand ${cls}"><strong>${esc(c.label||c.key)} · <span class="${c.side==='RISE'?'rfs-good':'rfs-bad'}">${esc(c.side||'—')}</span></strong><small>N ${fn} · WR <span class="${wr>=.5260389269?'rfs-good':'rfs-bad'}">${pct(wr)}</span> · L95 <span class="${low>=.5260389269?'rfs-good':'rfs-bad'}">${pct(low)}</span> · ${esc(c.validationStatus||'')}</small></div>`;}).join(''):'<div class="rfs-muted">No frozen candidates yet.</div>';
  }

  function update(){
    const s=snap(); if(!s){setText('rfs-head-sub','R_10 · waiting for lab…');return;}
    const sig=s.currentSignal||{}, f=sig.forward||{}, stats=s.executionStats||{}, col=s.collection||{}, feed=s.feedHealth||{};
    const be=num(s.economics?.assumedBreakEvenWinRate,0.5260389269), n=num(f.n), wr=num(f.winRate), low=num(f.lower95);
    const sideOK=!!sig.side&&(s.autoSide==='AUTO'||s.autoSide===sig.side), autoReady=!!s.runner&&s.currentMode!=='SHADOW'&&sideOK&&n>=300&&wr>=.54&&low>=be&&sig.status==='AUTO_READY';

    setText('rfs-head-sub',`R_10 · ${feed.connected?'LIVE':'OFFLINE'} · ${s.currentMode||'SHADOW'}`);
    setText('rfs-ticks',num(col.totalForwardTicks).toLocaleString());
    setText('rfs-feed',feed.connected?'CONNECTED':'OFFLINE',feed.connected?'rfs-good':'rfs-bad');
    setText('rfs-mode',s.currentMode||'—');
    setText('rfs-cohort',(s.cohort?.cohortId||'—').slice(-10));
    setText('rfs-side',sig.side||'—',sig.side==='RISE'?'rfs-good':sig.side==='FALL'?'rfs-bad':'rfs-warn'); setText('rfs-wr',pct(f.winRate),wr>=be?'rfs-good':'rfs-bad'); setText('rfs-n',String(n),n>=300?'rfs-good':'rfs-bad'); setText('rfs-low',pct(f.lower95),low>=be?'rfs-good':'rfs-bad');
    [['rfs-wr',wr>=be],['rfs-n',n>=300],['rfs-low',low>=be]].forEach(([id,pass])=>{const card=$(id)?.closest('.rfs-metric');if(card){card.classList.remove('rfs-passbox','rfs-failbox');card.classList.add(pass?'rfs-passbox':'rfs-failbox');}});
    setText('rfs-signal-status',sig.status||'—',sig.status==='AUTO_READY'?'rfs-good':sig.status==='REJECTED'?'rfs-bad':'rfs-warn');
    setText('rfs-candidate',sig.candidate?.label||'No frozen candidate currently matches.');
    setText('rfs-auto-ready',autoReady?'READY':'WAITING',autoReady?'rfs-good':'rfs-warn');
    setText('rfs-gate-n',`${n}/300`,n>=300?'rfs-good':'rfs-bad'); setText('rfs-gate-wr',pct(wr),wr>=.54?'rfs-good':'rfs-bad'); setText('rfs-gate-low',`${pct(low)} / ${pct(be)}`,low>=be?'rfs-good':'rfs-bad');
    setText('rfs-auto-note',autoReady?'All evidence gates pass. AUTO may request a live proposal.':'AUTO blocked until the evidence gates and side/mode conditions all pass.');
    setActive('rfs-mode-shadow',s.currentMode==='SHADOW');setActive('rfs-mode-demo',s.currentMode==='DEMO');setActive('rfs-mode-real',s.currentMode==='REAL');
    setActive('rfs-side-auto',s.autoSide==='AUTO');setActive('rfs-side-rise',s.autoSide==='RISE');setActive('rfs-side-fall',s.autoSide==='FALL');
    $('rfs-run').textContent=s.runner?'STOP AUTO':'START AUTO'; $('rfs-run').classList.toggle('danger',!!s.runner);
    const wakeRequested=(localStorage.getItem(WAKE_KEY)==='1')||!!col.wakeLockRequested; const wakeActive=!!ownWakeLock||!!col.wakeLockActive; $('rfs-screen').textContent=wakeRequested?(wakeActive?'SCREEN ON ✓':'SCREEN REQUESTED'):'KEEP SCREEN ON'; $('rfs-screen').classList.toggle('active',wakeRequested);
    setText('rfs-contracts',String(num(stats.contracts)));setText('rfs-wins',String(num(stats.wins)),'rfs-good');setText('rfs-losses',String(num(stats.losses)),'rfs-bad');setText('rfs-pnl',money(stats.pnl),num(stats.pnl)>=0?'rfs-good':'rfs-bad');
    setText('rfs-local-ticks',`${num(col.totalForwardTicks).toLocaleString()} ticks`);

    const c=cloud()?.getState?.();
    if(c){setText('rfs-cloud-status',c.status||'—',c.status==='SYNCED'?'rfs-good':c.status==='ERROR'||c.status==='SETUP'?'rfs-bad':'rfs-warn');setText('rfs-cloud-ticks',`${num(c.remoteTicks).toLocaleString()} ticks`);setText('rfs-cloud-msg',c.message||'');$('rfs-cloud-restore').style.display=c.restoreAvailable?'block':'none';$('rfs-cloud-claim').style.display=c.collectorBusy?'block':'none';}
    else {setText('rfs-cloud-status','WAITING','rfs-warn');setText('rfs-cloud-ticks','—');setText('rfs-cloud-msg','Cloud module is still loading.');}
    renderCandidates(s);
  }

  function boot(){
    make();
    const wait=setInterval(()=>{if(lab()){clearInterval(wait);update();}},250);
    setTimeout(()=>clearInterval(wait),20000);
    setInterval(update,1000); // visual refresh only; research still scores every tick in the original lab engine.
    document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'){if(localStorage.getItem(WAKE_KEY)==='1'&&!ownWakeLock)requestOwnWakeLock();update();}});
    if(localStorage.getItem(WAKE_KEY)==='1')requestOwnWakeLock();
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
