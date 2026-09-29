/*
 * DigitMatchStar Rise/Fall Cloud Sync + UI Diagnostics v1.2
 * Loads AFTER rise-fall-research-v1-private.js.
 * Does not change candidate definitions, evidence thresholds, or trade logic.
 */
(() => {
'use strict';

const VERSION = 'RISEFALL-CLOUD-UI-V1.2';
const SYMBOL = 'R_10';
const API = '/api/rise-fall-cloud-state';
const DB_NAME = 'digitmatchstar_research_persistence_v1';
const DB_STORE = 'kv';
const STORE = `risefall_lab_v1_ui_${SYMBOL}`;
const COHORT_STORE = `risefall_lab_v1_cohort_${SYMBOL}`;
const PROGRESS_STORE = `risefall_lab_v1_progress_${SYMBOL}`;
const DEVICE_KEY = 'risefall_cloud_device_v1';
const SYNC_MS = 30_000;
const LEASE_FRESH_MS = 90_000;

const C = {
  deviceId: localStorage.getItem(DEVICE_KEY) || `RFDEV-${crypto?.randomUUID?.() || (Date.now()+'-'+Math.random().toString(36).slice(2))}`,
  cloud: null,
  status: 'CHECKING',
  message: 'Checking cloud…',
  lastSyncAt: null,
  syncBusy: false,
  remoteTicks: 0,
  restoreAvailable: false,
  collectorBusy: false,
  configured: true,
  lastError: '',
};
localStorage.setItem(DEVICE_KEY, C.deviceId);

const $ = id => document.getElementById(id);
const pct = v => v == null || !Number.isFinite(Number(v)) ? '—' : `${(Number(v)*100).toFixed(2)}%`;
const esc = s => String(s ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
const shortDev = d => d ? String(d).slice(-8) : '—';
function token(){ return localStorage.getItem('active_token') || localStorage.getItem('derivToken') || localStorage.getItem('derivTokenDemo') || localStorage.getItem('derivTokenReal') || ''; }
function account(){ return localStorage.getItem('active_account') || localStorage.getItem('derivAccount') || localStorage.getItem('derivDemoAccount') || localStorage.getItem('derivRealAccount') || ''; }
function lab(){ return window.DMSRiseFallLab; }
function snap(){ try { return lab()?.getSnapshot?.() || null; } catch (_) { return null; } }

async function callCloud(action, state=null, forceTakeover=false){
  const t=token(), a=account();
  if(!t||!a) throw new Error('Login/admin account is required for cloud sync.');
  const r=await fetch(API,{method:'POST',headers:{'Content-Type':'application/json','Authorization':`Bearer ${t}`},credentials:'same-origin',body:JSON.stringify({action,account_id:a,symbol:SYMBOL,device_id:C.deviceId,state,force_takeover:forceTakeover})});
  const j=await r.json().catch(()=>({}));
  if(!r.ok){ const e=new Error(j.error||`Cloud sync HTTP ${r.status}`); e.status=r.status; e.data=j; throw e; }
  return j;
}

function stableCandidate(c){return {key:c.key,label:c.label,tagKeys:Array.isArray(c.tagKeys)?c.tagKeys:null,type:c.type,side:c.side,n:c.n,rise:c.rise,fall:c.fall,equal:c.equal,discoveryWinRate:c.discoveryWinRate,discoveryEdge:c.discoveryEdge};}
function seedTicksFromSnapshot(s){
  const recs=(s?.forwardRecords||[]).slice(-80); const out=[];
  if(recs.length && Number.isFinite(Number(recs[0].entryQuote))) out.push({quote:Number(recs[0].entryQuote),epoch:Math.max(0,Number(recs[0].epoch||0)-1),source:'CLOUD_SEED'});
  for(const r of recs){if(Number.isFinite(Number(r.exitQuote))&&Number.isFinite(Number(r.epoch)))out.push({quote:Number(r.exitQuote),epoch:Number(r.epoch),source:'CLOUD_SEED'});}
  for(let i=0;i<out.length;i++){const a=Number(out[i-1]?.quote),b=Number(out[i].quote);out[i].direction=i===0?'EQUAL':b>a?'RISE':b<a?'FALL':'EQUAL';}
  return out.slice(-80);
}
function compactCloudState(s){
  const seed=seedTicksFromSnapshot(s);
  const candidates=(s?.candidates||[]).map(stableCandidate);
  return {
    schema:'DIGITMATCHSTAR_RISEFALL_CLOUD_V1',
    version:VERSION,
    sourceLabVersion:s?.version||null,
    symbol:SYMBOL,
    savedAt:new Date().toISOString(),
    cohort:{...(s?.cohort||{}),candidates,featureSeedTicks:seed},
    progress:{
      candidateProgress:(s?.candidates||[]).map(c=>({key:c.key,forwardN:Number(c.forwardN||c.forward?.n||0),forwardWins:Number(c.forwardWins||c.forward?.wins||0),forwardLosses:Number(c.forwardLosses||c.forward?.losses||0)})),
      totalForwardTicks:Number(s?.collection?.totalForwardTicks||0),
      forwardStartEpoch:s?.cohort?.forwardStartEpoch??null,
      lastFeatureEpoch:s?.collection?.lastFeatureEpoch??null,
      collectionGapEvents:Number(s?.collection?.collectionGapEvents||0),
      stats:s?.executionStats||{contracts:0,wins:0,losses:0,pnl:0},
      forwardRecords:(s?.forwardRecords||[]).slice(-300),
      executionRecords:(s?.executionRecords||[]).slice(-100),
      liveTicks:seed,
      seenEpochQueue:(s?.forwardRecords||[]).slice(-15000).map(r=>Number(r.epoch)).filter(Number.isFinite),
      persistedAt:new Date().toISOString(),
      compactPersistence:true,
    },
    ui:{mode:'SHADOW',autoSide:s?.autoSide||'AUTO',stake:Number(s?.stake||1),runner:false,wakeLockRequested:false},
  };
}

function openDb(){return new Promise((resolve,reject)=>{const q=indexedDB.open(DB_NAME,1);q.onupgradeneeded=()=>{if(!q.result.objectStoreNames.contains(DB_STORE))q.result.createObjectStore(DB_STORE);};q.onsuccess=()=>resolve(q.result);q.onerror=()=>reject(q.error);});}
async function putLocal(key,value){
  try{const db=await openDb();await new Promise((resolve,reject)=>{const tx=db.transaction(DB_STORE,'readwrite');tx.objectStore(DB_STORE).put(value,key);tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);});}catch(_){}
  try{localStorage.setItem(key,value);}catch(_){}
}
async function restoreCloud(){
  if(!C.cloud) return;
  const x=C.cloud, c=x.cohort||{}, p=x.progress||{};
  if(!c.cohortId || !Array.isArray(c.candidates) || !c.candidates.length) throw new Error('Cloud state does not contain a valid cohort registry.');
  const cohortRegistry={cohortId:c.cohortId,cohortCreatedAt:c.cohortCreatedAt||null,candidatesFrozenAt:c.candidatesFrozenAt||null,candidateSetHash:c.candidateSetHash||null,historicalHash:c.historicalHash||null,hashAlgorithm:c.hashAlgorithm||'FNV1A32',discoveryStartEpoch:c.discoveryStartEpoch||null,discoveryEndEpoch:c.discoveryEndEpoch||null,forwardStartEpoch:c.forwardStartEpoch||null,featureSeedTicks:Array.isArray(c.featureSeedTicks)?c.featureSeedTicks.slice(-80):[],candidates:c.candidates};
  const progress={candidateProgress:p.candidateProgress||[],totalForwardTicks:Number(p.totalForwardTicks||0),forwardStartEpoch:p.forwardStartEpoch||c.forwardStartEpoch||null,lastFeatureEpoch:p.lastFeatureEpoch||null,collectionGapEvents:Number(p.collectionGapEvents||0),stats:p.stats||{contracts:0,wins:0,losses:0,pnl:0},forwardRecords:(p.forwardRecords||[]).slice(-300),executionRecords:(p.executionRecords||[]).slice(-100),liveTicks:(p.liveTicks||c.featureSeedTicks||[]).slice(-80),seenEpochQueue:(p.seenEpochQueue||[]).slice(-15000),persistedAt:new Date().toISOString(),compactPersistence:true};
  const ui={mode:'SHADOW',autoSide:x.ui?.autoSide||'AUTO',stake:Number(x.ui?.stake||1),runner:false,wakeLockRequested:false,minimized:false,panelPos:null};
  await putLocal(COHORT_STORE,JSON.stringify(cohortRegistry)); await putLocal(PROGRESS_STORE,JSON.stringify(progress)); await putLocal(STORE,JSON.stringify(ui));
  location.reload();
}

function localTicks(){return Number(snap()?.collection?.totalForwardTicks||0);}
function sameCohort(a,b){return !!a && !!b && a===b;}
function activeOtherCollector(){return !!(C.cloud?.collectorDeviceId && C.cloud.collectorDeviceId!==C.deviceId && Date.now()-Number(C.cloud.collectorHeartbeatAt||0)<LEASE_FRESH_MS);}

async function loadCloud(){
  if(C.syncBusy)return; C.syncBusy=true;
  try{
    const j=await callCloud('load'); C.cloud=j.state||null; C.remoteTicks=Number(C.cloud?.progress?.totalForwardTicks||0); C.collectorBusy=activeOtherCollector();
    const s=snap(); const lt=Number(s?.collection?.totalForwardTicks||0), lc=s?.cohort?.cohortId||null, rc=C.cloud?.cohort?.cohortId||null;
    C.restoreAvailable=!!C.cloud && (C.remoteTicks>lt || !sameCohort(lc,rc));
    if(!C.cloud){C.status='LOCAL';C.message='Cloud empty — ready to seed from this device.';}
    else if(C.collectorBusy){C.status='VIEWER';C.message=`Collector active on device ${shortDev(C.cloud.collectorDeviceId)}.`;}
    else if(C.restoreAvailable){C.status='RESTORE';C.message=`Cloud has ${C.remoteTicks.toLocaleString()} ticks; restore is available.`;}
    else {C.status='SYNCED';C.message='Cloud and this device are aligned.';}
    C.lastError='';
  }catch(e){C.lastError=e.message||String(e);C.status=e.status===503?'SETUP':'ERROR';C.message=C.lastError;C.configured=e.status!==503;}
  finally{C.syncBusy=false;renderEnhancements();}
}

async function pushCloud(force=false){
  if(C.syncBusy)return; const s=snap(); if(!s?.cohort?.cohortId)return; C.syncBusy=true;
  try{
    const state=compactCloudState(s); const j=await callCloud('save',state,force); C.cloud=j.state; C.remoteTicks=Number(C.cloud?.progress?.totalForwardTicks||0); C.lastSyncAt=Date.now(); C.status='SYNCED';C.message=`Cloud saved · ${C.remoteTicks.toLocaleString()} ticks`;C.restoreAvailable=false;C.collectorBusy=false;C.lastError='';
  }catch(e){C.lastError=e.message||String(e); if(e.status===409&&e.data?.state){C.cloud=e.data.state;C.remoteTicks=Number(C.cloud?.progress?.totalForwardTicks||0);C.collectorBusy=e.data.error==='collector_busy';C.restoreAvailable=C.remoteTicks>localTicks();C.status=C.collectorBusy?'VIEWER':'RESTORE';C.message=C.collectorBusy?`Another collector is active (${shortDev(C.cloud.collectorDeviceId)}).`:'Cloud is newer than this device.';}else{C.status=e.status===503?'SETUP':'ERROR';C.message=C.lastError;}}
  finally{C.syncBusy=false;renderEnhancements();}
}

async function claimDevice(){
  if(!confirm('Take over cloud collection on this device? Use this only after restoring the newest cloud state.'))return;
  try{await pushCloud(true);}catch(_){}
}

function gateRow(label,pass,value,target){const cls=pass?'rf-good':'rf-bad';return `<div class="rfdiag-row"><span>${esc(label)}</span><b class="${cls}">${pass?'✓':'✕'} ${esc(value)}</b><em>${esc(target||'')}</em></div>`;}
function diagnostics(s){
  const sig=s?.currentSignal, f=sig?.forward||{}, be=Number(s?.economics?.assumedBreakEvenWinRate||0.5260389269), minN=300, minWR=.54;
  const sideOK=!!sig?.side && (s.autoSide==='AUTO'||s.autoSide===sig.side);
  const n=Number(f.n||0), wr=Number(f.winRate||0), low=Number(f.lower95||0);
  const autoExec=(s?.executionRecords||[]).filter(x=>x.kind==='EXECUTION'&&x.source==='AUTO').length;
  const manual=(s?.executionRecords||[]).filter(x=>x.kind==='EXECUTION'&&x.source==='MANUAL').length;
  const lastSkip=[...(s?.executionRecords||[])].reverse().find(x=>x.kind==='AUTO_SKIP');
  const ready=!!s.runner&&s.currentMode!=='SHADOW'&&sideOK&&n>=minN&&wr>=minWR&&low>=be&&sig?.status==='AUTO_READY';
  return `<div id="rfdiag" class="rf-panel rfdiag-panel"><div class="rf-title">AUTO DIAGNOSTICS <span class="rfdiag-pill ${ready?'pass':'wait'}">${ready?'READY':'WAITING'}</span></div>
    ${gateRow('Runner',!!s.runner,s.runner?'ON':'OFF','must be ON')}
    ${gateRow('Trade mode',s.currentMode!=='SHADOW',s.currentMode,'DEMO or REAL')}
    ${gateRow('Side filter',sideOK,`${s.autoSide} · signal ${sig?.side||'—'}`,'must allow signal')}
    ${gateRow('Forward support',n>=minN,`${n} / ${minN}`,'')}
    ${gateRow('Observed win rate',wr>=minWR,pct(wr),`≥ ${pct(minWR)}`)}
    ${gateRow('Lower 95%',low>=be,pct(low),`≥ ${pct(be)}`)}
    <div class="rfdiag-summary"><b>${ready?'AUTO MAY REQUEST A LIVE PROPOSAL':'NO AUTO TRADE YET'}</b><span>${esc(sig?.candidate?.label||sig?.status||'No frozen match')}</span></div>
    <div class="rfdiag-mini"><span>Auto trades <b>${autoExec}</b></span><span>Manual trades <b>${manual}</b></span>${lastSkip?`<span>Last skip: ${esc(lastSkip.reason||'proposal gate')}</span>`:''}</div></div>`;
}
function cloudPanel(s){
  const lt=Number(s?.collection?.totalForwardTicks||0), rt=Number(C.remoteTicks||0); const tone=C.status==='SYNCED'?'rf-good':C.status==='ERROR'?'rf-bad':'rf-amber';
  return `<div id="rfcloud" class="rf-panel rfcloud-panel"><div class="rf-title">CLOUD RESEARCH BACKUP <span class="${tone}">${esc(C.status)}</span></div>
    <div class="rfcloud-grid"><div><span>This device</span><b>${lt.toLocaleString()} ticks</b></div><div><span>Cloud</span><b>${rt.toLocaleString()} ticks</b></div><div><span>Device</span><b>${shortDev(C.deviceId)}</b></div><div><span>Collector</span><b>${shortDev(C.cloud?.collectorDeviceId)}</b></div></div>
    <div class="rf-small">${esc(C.message)}</div>
    <div class="rfcloud-actions"><button id="rfcloud-load" class="rf-btn">CHECK CLOUD</button><button id="rfcloud-push" class="rf-btn">SYNC NOW</button>${C.restoreAvailable?'<button id="rfcloud-restore" class="rf-btn danger">RESTORE CLOUD</button>':''}${C.collectorBusy?'<button id="rfcloud-claim" class="rf-btn danger">TAKE OVER</button>':''}</div>
    ${C.status==='SETUP'?'<div class="rf-small rf-bad" style="margin-top:6px">Cloud store needs Upstash/Vercel KV environment variables.</div>':''}</div>`;
}

function ensureCss(){if($('rfcloud-style'))return;const st=document.createElement('style');st.id='rfcloud-style';st.textContent=`#risefall-lab-v1-panel{width:390px!important;background:linear-gradient(180deg,#071522,#07111c)!important;border-color:#31516d!important}.rf-head{background:linear-gradient(90deg,#0d2943,#123753)!important}.rfdiag-panel{border-color:#31506a!important}.rfdiag-pill{float:right;font-size:9px;padding:2px 6px;border-radius:999px}.rfdiag-pill.pass{background:rgba(49,201,130,.15);color:#54e39a}.rfdiag-pill.wait{background:rgba(243,189,79,.13);color:#ffd166}.rfdiag-row{display:grid;grid-template-columns:1.2fr 1fr .8fr;gap:6px;align-items:center;padding:5px 0;border-bottom:1px solid rgba(123,163,193,.09)}.rfdiag-row span{color:#8ea9bf}.rfdiag-row em{font-style:normal;text-align:right;color:#6f8da6;font-size:9px}.rfdiag-summary{margin-top:8px;padding:8px;border-radius:8px;background:#07141f}.rfdiag-summary b,.rfdiag-summary span{display:block}.rfdiag-summary span{font-size:9px;color:#86a4bb;margin-top:2px}.rfdiag-mini{display:flex;gap:10px;flex-wrap:wrap;margin-top:6px;color:#7898b0;font-size:9px}.rfcloud-panel{border-color:#2b6685!important;background:linear-gradient(180deg,rgba(17,55,79,.45),rgba(8,23,35,.75))!important}.rfcloud-grid{display:grid;grid-template-columns:1fr 1fr;gap:5px;margin-bottom:7px}.rfcloud-grid>div{padding:6px;border-radius:7px;background:#07141f}.rfcloud-grid span,.rfcloud-grid b{display:block}.rfcloud-grid span{font-size:9px;color:#7899b4}.rfcloud-actions{display:grid;grid-template-columns:1fr 1fr;gap:5px;margin-top:7px}.rfcloud-actions .danger{border-color:#9a4a55;background:#4e2028}.rf-cand.good{box-shadow:inset 0 0 0 1px rgba(49,201,130,.07)}.rf-cand.bad{opacity:.88}.rf-metric b{font-size:12px}`;document.head.appendChild(st);}
function renderEnhancements(){
  const s=snap(), body=$('rf-body'); if(!s||!body)return; ensureCss();
  $('rfcloud-wrap')?.remove(); const wrap=document.createElement('div');wrap.id='rfcloud-wrap';wrap.innerHTML=cloudPanel(s)+diagnostics(s);body.prepend(wrap);
  $('rfcloud-load')?.addEventListener('click',loadCloud);$('rfcloud-push')?.addEventListener('click',()=>pushCloud(false));$('rfcloud-restore')?.addEventListener('click',()=>{if(confirm(`Restore the cloud cohort with ${C.remoteTicks.toLocaleString()} ticks on this device? The page will reload in SHADOW mode.`))restoreCloud().catch(e=>alert(e.message));});$('rfcloud-claim')?.addEventListener('click',claimDevice);
  const sub=$('rf-mini-sub');if(sub)sub.textContent=`1 tick · ${SYMBOL} · cloud ${C.status.toLowerCase()}`;
}

async function cycle(){
  const s=snap(); if(!s)return;
  if(!C.cloud){await loadCloud();if(!C.cloud&&C.status!=='SETUP'&&C.status!=='ERROR'&&Number(s.collection?.totalForwardTicks||0)>0)await pushCloud(false);return;}
  C.collectorBusy=activeOtherCollector();
  const lt=Number(s.collection?.totalForwardTicks||0), rt=Number(C.cloud?.progress?.totalForwardTicks||0);
  if(C.collectorBusy){C.status='VIEWER';C.message=`Another device is the active cloud collector (${shortDev(C.cloud.collectorDeviceId)}).`;return renderEnhancements();}
  if(rt>lt || C.cloud?.cohort?.cohortId!==s.cohort?.cohortId){C.restoreAvailable=true;C.status='RESTORE';C.message=`Cloud is newer/different (${rt.toLocaleString()} ticks). Restore before collecting here.`;return renderEnhancements();}
  if(lt>=rt) await pushCloud(false);
}

function boot(){
  if(!lab()){setTimeout(boot,500);return;} ensureCss(); renderEnhancements(); loadCloud().then(()=>cycle());
  setInterval(renderEnhancements,1000); setInterval(cycle,SYNC_MS);
  window.addEventListener('pagehide',()=>{try{const s=snap();if(s&&C.cloud?.collectorDeviceId===C.deviceId)navigator.sendBeacon?.(API,new Blob([]));}catch(_){}});
  window.DMSRiseFallCloud={version:VERSION,load:loadCloud,sync:()=>pushCloud(false),restore:restoreCloud,claim:claimDevice,getState:()=>({...C})};
}
boot();
})();
