/*
 * DigitMatchStar — Under 9 Research + Execution Lab v2.0
 * Modes: SHADOW, DEMO, REAL
 * Default: SHADOW. Execution is single-tick DIGITUNDER barrier 9, flat stake.
 * Research purpose: validate whether selective P(9) filters can beat live proposal economics.
 */
(() => {
'use strict';

const VERSION = 'UNDER9-LAB-V2.1-PRIVATE-ADMIN';
const SYMBOL = 'R_10';
const STORE = `under9_lab_v2_${SYMBOL}`;
const PANEL_ID = 'under9-lab-v2-panel';
const DEFAULT_APP_ID = 1089;
const CFG = {
  symbol: SYMBOL,
  historyCount: 5000,
  maxLiveTicks: 5000,
  maxRecords: 30000,
  stake: 1,
  threshold: 0.06,
  thresholds: [0.08,0.07,0.06,0.05,0.04],
  cooldownMs: 250,
};

const S = {
  mode:'SHADOW', running:false, connected:false, authenticated:false,
  publicWs:null, tradeWs:null, pipSize:3,
  discoveryTicks:[], liveTicks:[], records:[], pendingShadow:null,
  activeTrade:null, pendingProposal:null, reconnectTimer:null,
  lastTradeAt:0, historicalLoaded:false, accountId:null,
  stats:{contracts:0,wins:0,losses:0,pnl:0},
  adminAuthorized:false, adminLastCheckedAt:0, adminCheckInFlight:false,
};

const $ = id => document.getElementById(id);
const nowISO = () => new Date().toISOString();
const clamp = (x,a,b)=>Math.max(a,Math.min(b,x));
const pct = v => v==null?'—':`${(100*v).toFixed(2)}%`;
const money = v => `${v<0?'-':'+'}$${Math.abs(v||0).toFixed(2)}`;
const last=(a,n)=>a.slice(Math.max(0,a.length-n));

function getToken(){
  return localStorage.getItem('active_token') || localStorage.getItem('derivToken') ||
         (S.mode==='REAL'?localStorage.getItem('derivTokenReal'):localStorage.getItem('derivTokenDemo')) || '';
}
function getAccount(){
  return localStorage.getItem('active_account') || localStorage.getItem('derivAccount') ||
         (S.mode==='REAL'?localStorage.getItem('derivRealAccount'):localStorage.getItem('derivDemoAccount')) || '';
}
function getAppId(){ return localStorage.getItem('deriv_app_id') || localStorage.getItem('deriv_client_id') || DEFAULT_APP_ID; }


async function ensureAdminAuthorized(force=false){
  const now=Date.now();
  if(!force && S.adminAuthorized && now-S.adminLastCheckedAt<60000) return true;
  if(S.adminCheckInFlight) return false;
  S.adminCheckInFlight=true;
  try{
    const token=getToken();
    const accountId=getAccount();
    if(!token || !accountId){
      S.adminAuthorized=false; S.adminLastCheckedAt=now; hidePrivateLab(); return false;
    }
    const response=await fetch('/api/capture-access',{
      method:'POST',
      headers:{'Content-Type':'application/json','Authorization':`Bearer ${token}`},
      credentials:'same-origin',
      body:JSON.stringify({account_id:accountId})
    });
    if(!response.ok){
      S.adminAuthorized=false; S.adminLastCheckedAt=now; hidePrivateLab(); return false;
    }
    const data=await response.json().catch(()=>({}));
    S.adminAuthorized=!!(
      data.allowed===true || data.authorized===true || data.captureAllowed===true ||
      data.captureAdmin===true || data.ok===true
    );
    S.adminLastCheckedAt=now;
    if(!S.adminAuthorized) hidePrivateLab();
    return S.adminAuthorized;
  }catch(_){
    S.adminAuthorized=false; S.adminLastCheckedAt=now; hidePrivateLab(); return false;
  }finally{S.adminCheckInFlight=false;}
}

function hidePrivateLab(){
  const p=document.getElementById(PANEL_ID); if(p) p.remove();
  S.running=false;
  if(S.publicWs){try{S.publicWs.close()}catch(_){}} S.publicWs=null; S.connected=false;
  if(S.tradeWs){try{S.tradeWs.close()}catch(_){}} S.tradeWs=null; S.authenticated=false;
}

function load(){
  try{
    const x=JSON.parse(localStorage.getItem(STORE)||'{}');
    if(Array.isArray(x.records))S.records=x.records.slice(-CFG.maxRecords);
    if(Array.isArray(x.discoveryTicks))S.discoveryTicks=x.discoveryTicks.slice(-CFG.historyCount);
    if(Array.isArray(x.liveTicks))S.liveTicks=x.liveTicks.slice(-CFG.maxLiveTicks);
    if(x.stats)S.stats=x.stats;
    if(x.mode)S.mode=x.mode;
    if(typeof x.running==='boolean')S.running=x.running;
  }catch(_){ }
  // Never auto-resume REAL after reload.
  if(S.mode==='REAL'){ S.mode='SHADOW'; S.running=false; }
}
function save(){
  try{ localStorage.setItem(STORE,JSON.stringify({records:S.records.slice(-CFG.maxRecords),discoveryTicks:S.discoveryTicks.slice(-CFG.historyCount),liveTicks:S.liveTicks.slice(-CFG.maxLiveTicks),stats:S.stats,mode:S.mode,running:S.running})); }catch(_){ }
}

function digitFromQuote(q,pip=S.pipSize){
  const n=Number(q); if(!Number.isFinite(n))return null;
  const s=n.toFixed(pip); const d=Number(s[s.length-1]); return Number.isInteger(d)?d:null;
}
function rate9(arr,n){const a=last(arr,n);return a.length?a.filter(x=>x.digit===9).length/a.length:0.1;}
function gap9(arr){for(let i=arr.length-1,g=0;i>=0;i--,g++){if(arr[i].digit===9)return g;}return arr.length;}
function count9(arr,n){return last(arr,n).filter(x=>x.digit===9).length;}
function trans9(arr,prev,maxN=1500){const a=last(arr,maxN);let d=0,n=0;for(let i=1;i<a.length;i++){if(a[i-1].digit===prev){d++;if(a[i].digit===9)n++;}}return d>=25?n/d:0.1;}
function entropy(arr,n=100){const a=last(arr,n);if(!a.length)return 1;const c=Array(10).fill(0);a.forEach(x=>c[x.digit]++);let h=0;for(const z of c){if(!z)continue;const p=z/a.length;h-=p*Math.log(p);}return h/Math.log(10);}
function non9Run(arr){let n=0;for(let i=arr.length-1;i>=0;i--){if(arr[i].digit===9)break;n++;}return n;}

function featureUniverse(){
  // Discovery history is allowed to inform the descriptive model; live outcomes are never backfilled.
  return [...S.discoveryTicks, ...S.liveTicks].slice(-(CFG.historyCount+CFG.maxLiveTicks));
}
function estimateP9(){
  const a=featureUniverse(); const prev=a.length?a[a.length-1].digit:0;
  const r10=rate9(a,10),r20=rate9(a,20),r50=rate9(a,50),r100=rate9(a,100),tr=trans9(a,prev);
  const g=gap9(a),c5=count9(a,5),c10=count9(a,10),run=non9Run(a),ent=entropy(a,100);
  let p=.20*.10+.10*r10+.15*r20+.20*r50+.15*r100+.20*tr;
  if(c5>=2)p+=.005; if(c10===0&&g>=10)p+=.003; if(run>=20)p+=.004; if(ent<.90)p+=.003;
  p=clamp(p,.02,.20);
  return {p9:p, winProb:1-p, features:{prevDigit:prev,rate9_10:r10,rate9_20:r20,rate9_50:r50,rate9_100:r100,transitionTo9:tr,gapSince9:g,count9_5:c5,count9_10:c10,consecutiveNon9:run,entropy100:ent}};
}

function makePrediction(){
  const a=featureUniverse(); if(a.length<300)return null;
  const e=estimateP9();
  return {frozenAt:nowISO(),p9:e.p9,winProb:e.winProb,features:e.features,accept:e.p9<=CFG.threshold};
}
function scoreShadow(digit,epoch,quote){
  const p=S.pendingShadow;if(!p)return;
  const win=digit!==9;
  S.records.push({kind:'SHADOW',mode:'SHADOW',symbol:SYMBOL,predictedAt:p.frozenAt,outcomeAt:nowISO(),epoch,quote,digit,p9:p.p9,accepted:p.accept,under9Win:win,features:p.features});
  S.pendingShadow=null; trimSave();
}
function trimSave(){ if(S.records.length>CFG.maxRecords)S.records.splice(0,S.records.length-CFG.maxRecords); save(); }

async function loadHistory(){
  if(S.historicalLoaded || !S.publicWs || S.publicWs.readyState!==1)return;
  S.publicWs.send(JSON.stringify({ticks_history:SYMBOL,end:'latest',count:CFG.historyCount,style:'ticks',adjust_start_time:1,req_id:92001}));
}

function onPublic(data){
  if(data.msg_type==='history' && data.history){
    const prices=data.history.prices||[], times=data.history.times||[]; const out=[];
    for(let i=0;i<prices.length;i++){const d=digitFromQuote(prices[i]);if(d!=null)out.push({digit:d,quote:Number(prices[i]),epoch:Number(times[i]||0),source:'HISTORICAL_DISCOVERY'});}
    S.discoveryTicks=out.slice(-CFG.historyCount);S.historicalLoaded=true;save();render();return;
  }
  if(data.msg_type!=='tick'||!data.tick)return;
  if(Number.isFinite(Number(data.tick.pip_size)))S.pipSize=Number(data.tick.pip_size);
  const d=digitFromQuote(data.tick.quote,S.pipSize);if(d==null)return;
  scoreShadow(d,data.tick.epoch,Number(data.tick.quote));
  S.liveTicks.push({digit:d,quote:Number(data.tick.quote),epoch:Number(data.tick.epoch),source:'LIVE_FORWARD'});
  if(S.liveTicks.length>CFG.maxLiveTicks)S.liveTicks.shift();
  S.pendingShadow=makePrediction();
  if(S.running && S.mode!=='SHADOW') maybeExecute();
  render();
}

function connectPublic(){
  try{
    const ws=new WebSocket(`wss://ws.derivws.com/websockets/v3?app_id=${encodeURIComponent(getAppId())}`);S.publicWs=ws;
    ws.onopen=()=>{S.connected=true;ws.send(JSON.stringify({ticks:SYMBOL,subscribe:1,req_id:91001}));loadHistory();render();};
    ws.onmessage=e=>{let d;try{d=JSON.parse(e.data)}catch{return;} if(!d.error)onPublic(d);};
    ws.onclose=()=>{S.connected=false;render();setTimeout(connectPublic,3000);};
  }catch(_){setTimeout(connectPublic,3000);}
}

async function getAuthenticatedWsUrl(){
  if(!(await ensureAdminAuthorized(true)))throw new Error('Private admin authorization required');
  const token=getToken(),account_id=getAccount(),app_id=getAppId();
  if(!token)throw new Error(`No ${S.mode} API token found`);
  if(!account_id)throw new Error(`No ${S.mode} account ID found`);
  const r=await fetch('/api/deriv-ws-url',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token,account_id,app_id})});
  const j=await r.json().catch(()=>({})); if(!r.ok||!j.websocket_url)throw new Error(j.error||'Failed to get authenticated Deriv WebSocket URL');
  return j.websocket_url;
}
async function ensureTradeWs(){
  if(S.tradeWs && S.tradeWs.readyState===1)return S.tradeWs;
  const url=await getAuthenticatedWsUrl();
  return await new Promise((resolve,reject)=>{
    const ws=new WebSocket(url);S.tradeWs=ws;
    const timer=setTimeout(()=>reject(new Error('Trading socket timeout')),10000);
    ws.onopen=()=>{clearTimeout(timer);S.authenticated=true;S.accountId=getAccount();ws.send(JSON.stringify({balance:1,subscribe:1,req_id:93001}));resolve(ws);render();};
    ws.onmessage=e=>{let d;try{d=JSON.parse(e.data)}catch{return;}onTradeMessage(d);};
    ws.onerror=()=>{}; ws.onclose=()=>{S.authenticated=false;S.tradeWs=null;render();};
  });
}
function onTradeMessage(d){
  if(d.error){
    const msg=d.error.message||'Deriv error';
    if(S.pendingProposal||S.activeTrade){recordExecutionError(msg);}
    S.pendingProposal=null;S.activeTrade=null;render();return;
  }
  if(d.msg_type==='proposal' && S.pendingProposal && d.proposal?.id){
    const pp=S.pendingProposal; pp.ask=Number(d.proposal.ask_price);pp.payout=Number(d.proposal.payout);pp.proposalId=d.proposal.id;
    const profit=pp.payout-pp.ask;pp.breakEven=pp.payout>0?pp.ask/pp.payout:null;pp.proposalProfit=profit;
    S.tradeWs.send(JSON.stringify({buy:d.proposal.id,price:pp.ask,req_id:94002})); return;
  }
  if(d.msg_type==='buy' && d.buy?.contract_id && S.pendingProposal){
    const pp=S.pendingProposal;S.pendingProposal=null;
    S.activeTrade={...pp,contractId:Number(d.buy.contract_id),boughtAt:nowISO(),buyPrice:Number(d.buy.buy_price||pp.ask)};
    S.tradeWs.send(JSON.stringify({proposal_open_contract:1,contract_id:S.activeTrade.contractId,subscribe:1,req_id:94003}));render();return;
  }
  if(d.msg_type==='proposal_open_contract' && S.activeTrade){
    const c=d.proposal_open_contract;if(Number(c.contract_id)!==Number(S.activeTrade.contractId))return;
    if(c.is_sold){
      const t=S.activeTrade;S.activeTrade=null;
      const profit=Number(c.profit||0),win=profit>0;
      S.stats.contracts++; if(win)S.stats.wins++; else S.stats.losses++; S.stats.pnl+=profit;
      S.records.push({kind:'EXECUTION',mode:S.mode,symbol:SYMBOL,predictedAt:t.prediction.frozenAt,executedAt:t.requestedAt,settledAt:nowISO(),p9:t.prediction.p9,features:t.prediction.features,stake:t.ask||CFG.stake,payout:t.payout,breakEvenProbability:t.breakEven,contractId:t.contractId,result:win?'WIN':'LOSS',profit,exitTick:c.exit_tick??null});
      trimSave();render();
    }
  }
}
function recordExecutionError(msg){S.records.push({kind:'EXECUTION_ERROR',mode:S.mode,at:nowISO(),message:msg});trimSave();}

async function maybeExecute(force=false){
  if(!(await ensureAdminAuthorized(true)))return;
  if(!S.running || S.mode==='SHADOW' || S.activeTrade || S.pendingProposal)return;
  if(Date.now()-S.lastTradeAt<CFG.cooldownMs)return;
  const prediction=makePrediction();if(!prediction)return;
  if(!force && !prediction.accept)return;
  try{
    const ws=await ensureTradeWs();
    if(ws.readyState!==1)return;
    S.lastTradeAt=Date.now();
    S.pendingProposal={prediction,requestedAt:nowISO(),mode:S.mode};
    ws.send(JSON.stringify({proposal:1,amount:CFG.stake,basis:'stake',contract_type:'DIGITUNDER',currency:'USD',duration:1,duration_unit:'t',underlying_symbol:SYMBOL,barrier:'9',req_id:94001}));
    render();
  }catch(e){recordExecutionError(String(e.message||e));render();}
}

function thresholdStats(th){
  const a=S.records.filter(r=>r.kind==='SHADOW' && r.p9<=th);const wins=a.filter(r=>r.under9Win).length,loss=a.length-wins;
  return {n:a.length,winRate:a.length?wins/a.length:null,nineRate:a.length?loss/a.length:null,simPnl:wins*.09-loss*1};
}
function exportJSON(){
  const payload={schema:'DIGITMATCHSTAR_UNDER9_LAB_V2',generatedAt:nowISO(),version:VERSION,researchOnly:false,defaultMode:'SHADOW',currentMode:S.mode,symbol:SYMBOL,config:CFG,methodology:{historicalUsage:'DISCOVERY_ONLY',liveRecords:'FORWARD_ONLY',predictionFrozenBeforeOutcome:true},executionStats:S.stats,thresholds:Object.fromEntries(CFG.thresholds.map(t=>[String(t),thresholdStats(t)])),records:S.records};
  const b=new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=`under9-lab-${SYMBOL}-${new Date().toISOString().replace(/[:.]/g,'-')}.json`;document.body.appendChild(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove();},1000);
}

async function setMode(m){
  if(!(await ensureAdminAuthorized(true)))return;
  if(m==='REAL') S.running=false;
  S.mode=m;S.authenticated=false;if(S.tradeWs){try{S.tradeWs.close()}catch(_){}}S.tradeWs=null;save();render();
}
async function toggleRun(){if(!(await ensureAdminAuthorized(true)))return;S.running=!S.running;save();render();if(S.running&&S.mode!=='SHADOW')maybeExecute();}

function makePanel(){
  if(!S.adminAuthorized)return;
  if($(PANEL_ID))return;const p=document.createElement('div');p.id=PANEL_ID;
  p.style.cssText='position:fixed;right:12px;bottom:12px;z-index:2147483644;width:355px;max-height:570px;overflow:auto;background:#0f172a;color:#e2e8f0;border:1px solid #334155;border-radius:12px;box-shadow:0 12px 30px rgba(0,0,0,.4);font:12px/1.35 system-ui,-apple-system,Segoe UI,Roboto,sans-serif';
  p.innerHTML='<div id="u9v2-head" style="display:flex;justify-content:space-between;align-items:center;padding:9px 10px;background:#111827;cursor:move"><div><b>UNDER 9 LAB</b><div style="font-size:10px;color:#94a3b8">'+VERSION+'</div></div><button id="u9v2-min">−</button></div><div id="u9v2-body" style="padding:10px"></div>';
  document.body.appendChild(p);let col=false;$('u9v2-min').onclick=()=>{col=!col;$('u9v2-body').style.display=col?'none':'block';$('u9v2-min').textContent=col?'+':'−';};
  let drag=null;$('u9v2-head').addEventListener('pointerdown',e=>{if(e.target.closest('button'))return;const r=p.getBoundingClientRect();drag={dx:e.clientX-r.left,dy:e.clientY-r.top};p.style.right='auto';p.style.bottom='auto';});document.addEventListener('pointermove',e=>{if(!drag)return;p.style.left=Math.max(0,Math.min(innerWidth-p.offsetWidth,e.clientX-drag.dx))+'px';p.style.top=Math.max(0,Math.min(innerHeight-p.offsetHeight,e.clientY-drag.dy))+'px';});document.addEventListener('pointerup',()=>drag=null);
}
function render(){
  if(!S.adminAuthorized){hidePrivateLab();return;}
  makePanel();const el=$('u9v2-body');if(!el)return;const pred=S.pendingShadow||makePrediction();
  const rows=CFG.thresholds.map(t=>{const x=thresholdStats(t);return `<tr><td>≤${(t*100).toFixed(0)}%</td><td>${x.n}</td><td>${pct(x.winRate)}</td><td>${pct(x.nineRate)}</td><td>${money(x.simPnl)}</td></tr>`}).join('');
  const modeColor=S.mode==='REAL'?'#fecaca':S.mode==='DEMO'?'#fde68a':'#bfdbfe';
  el.innerHTML=`
    <div style="margin-bottom:7px">Feed: <b>${S.connected?'CONNECTED':'OFFLINE'}</b> · Historical: <b>${S.discoveryTicks.length}/${CFG.historyCount}</b></div>
    <div style="display:flex;gap:5px;margin-bottom:7px">
      <button id="u9-shadow" style="flex:1">SHADOW</button><button id="u9-demo" style="flex:1">DEMO</button><button id="u9-real" style="flex:1">REAL</button>
    </div>
    <div style="padding:7px;border-radius:8px;background:#111827;margin-bottom:7px">Mode: <b style="color:${modeColor}">${S.mode}</b> · Runner: <b>${S.running?'ON':'OFF'}</b><br>Rule: trade only when P(9) ≤ ${(CFG.threshold*100).toFixed(0)}% · Flat stake $${CFG.stake.toFixed(2)}</div>
    <button id="u9-run" style="width:100%;padding:7px;margin-bottom:7px">${S.running?'STOP':'START'} ${S.mode}</button>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:5px;margin-bottom:7px"><div style="background:#111827;padding:6px">Next P(9)<br><b>${pred?pct(pred.p9):'warming'}</b></div><div style="background:#111827;padding:6px">Under-9<br><b>${pred?pct(pred.winProb):'—'}</b></div><div style="background:#111827;padding:6px">Executed<br><b>${S.stats.contracts}</b></div><div style="background:#111827;padding:6px">Exec P&L<br><b>${money(S.stats.pnl)}</b></div></div>
    <table style="width:100%;font-size:10px;text-align:right"><thead><tr><th align="left">P9</th><th>N</th><th>Win</th><th>9 rate</th><th>Sim P&L</th></tr></thead><tbody>${rows}</tbody></table>
    <div style="font-size:10px;color:#94a3b8;margin-top:6px">Historical 5,000 ticks are discovery only. All scored shadow outcomes are future-only. DEMO/REAL use live Deriv proposal prices; Panel and execution are restricted to the authorized admin account. REAL starts only after you press START REAL.</div>
    <button id="u9-export" style="width:100%;margin-top:7px;padding:7px">Export Under-9 JSON</button>`;
  $('u9-shadow').onclick=()=>setMode('SHADOW');$('u9-demo').onclick=()=>setMode('DEMO');$('u9-real').onclick=()=>setMode('REAL');$('u9-run').onclick=toggleRun;$('u9-export').onclick=exportJSON;
}

window.DMSUnder9Lab={
  version:VERSION,
  getSnapshot:()=>S.adminAuthorized?({version:VERSION,mode:S.mode,running:S.running,stats:S.stats,pending:S.pendingShadow,historicalTicks:S.discoveryTicks.length,liveTicks:S.liveTicks.length,privateAdmin:true}):null,
  exportReport:()=>{if(S.adminAuthorized)exportJSON();},
  setMode,
  start:async()=>{if(!(await ensureAdminAuthorized(true)))return;S.running=true;save();render();if(S.mode!=='SHADOW')maybeExecute();},
  stop:()=>{S.running=false;save();render();}
};

async function bootPrivateLab(){
  load();
  const ok=await ensureAdminAuthorized(true);
  if(!ok)return;
  makePanel();render();connectPublic();
  setInterval(async()=>{
    const ok=await ensureAdminAuthorized(true);
    if(!ok)hidePrivateLab();
  },60000);
}
bootPrivateLab();
})();
