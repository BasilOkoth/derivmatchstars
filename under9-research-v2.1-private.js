/*
 * DigitMatchStar — Under 9 Research + Execution Lab v2.0
 * Modes: SHADOW, DEMO, REAL
 * Default: SHADOW. Execution is single-tick DIGITUNDER barrier 9, flat stake.
 * Research purpose: validate whether selective P(9) filters can beat live proposal economics.
 */
(() => {
'use strict';

const VERSION = 'UNDER9-LAB-V2.6-DEDUP-WATCHLIST';
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
  breakEvenNineRate: 1 - (1 / 1.09),
  patternMinDiscoveryN: 30,
  patternMinPromisingForwardN: 50,
  patternMinValidatedForwardN: 200,
  comboMinDiscoveryN: 25,
  comboMaxCandidates: 20,
  staleFeedMs: 12000,
  watchdogIntervalMs: 4000,
  pingIntervalMs: 15000,
};

const S = {
  mode:'SHADOW', running:false, connected:false, authenticated:false,
  publicWs:null, tradeWs:null, pipSize:3,
  discoveryTicks:[], liveTicks:[], records:[], pendingShadow:null,
  activeTrade:null, pendingProposal:null, reconnectTimer:null,
  lastTradeAt:0, historicalLoaded:false, accountId:null,
  stats:{contracts:0,wins:0,losses:0,pnl:0},
  adminAuthorized:false, adminLastCheckedAt:0, adminCheckInFlight:false,
  lastPublicMessageAt:0, lastTickAt:0, lastTickEpoch:null,
  watchdogTimer:null, pingTimer:null, feedReconnects:0, staleReconnects:0,
  lastPublicError:'', publicReconnectAttempts:0,
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
    if(S.discoveryTicks.length>=300)S.historicalLoaded=true;
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
  const prev2=a.length>=2?a[a.length-2].digit:null;
  return {p9:p, winProb:1-p, features:{prevDigit:prev,prev2Digit:prev2,prevPair:prev2==null?null:`${prev2}${prev}`,rate9_10:r10,rate9_20:r20,rate9_50:r50,rate9_100:r100,transitionTo9:tr,gapSince9:g,count9_5:c5,count9_10:c10,consecutiveNon9:run,entropy100:ent}};
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
  S.lastTickAt=Date.now();
  S.lastTickEpoch=Number(data.tick.epoch||0);
  if(Number.isFinite(Number(data.tick.pip_size)))S.pipSize=Number(data.tick.pip_size);
  const d=digitFromQuote(data.tick.quote,S.pipSize);if(d==null)return;
  scoreShadow(d,data.tick.epoch,Number(data.tick.quote));
  S.liveTicks.push({digit:d,quote:Number(data.tick.quote),epoch:Number(data.tick.epoch),source:'LIVE_FORWARD'});
  if(S.liveTicks.length>CFG.maxLiveTicks)S.liveTicks.shift();
  S.pendingShadow=makePrediction();
  if(S.running && S.mode!=='SHADOW') maybeExecute();
  render();
}


function clearFeedHealthTimers(){
  if(S.watchdogTimer){clearInterval(S.watchdogTimer);S.watchdogTimer=null;}
  if(S.pingTimer){clearInterval(S.pingTimer);S.pingTimer=null;}
}
function forcePublicReconnect(reason='Feed stale'){
  S.lastPublicError=reason;
  S.connected=false;
  S.staleReconnects++;
  const old=S.publicWs;
  S.publicWs=null;
  if(old){try{old.onclose=null;old.close();}catch(_){}}
  clearFeedHealthTimers();
  clearTimeout(S.reconnectTimer);
  S.reconnectTimer=setTimeout(connectPublic,500);
  render();
}
function startFeedHealthTimers(ws){
  clearFeedHealthTimers();
  S.pingTimer=setInterval(()=>{
    if(S.publicWs!==ws || ws.readyState!==WebSocket.OPEN)return;
    try{ws.send(JSON.stringify({ping:1,req_id:91999}));}catch(_){ }
  },CFG.pingIntervalMs);
  S.watchdogTimer=setInterval(()=>{
    if(S.publicWs!==ws)return;
    const age=Date.now()-(S.lastTickAt||0);
    if(S.connected && S.lastTickAt && age>CFG.staleFeedMs){
      forcePublicReconnect(`No R_10 tick for ${(age/1000).toFixed(1)}s — reconnecting`);
    }
  },CFG.watchdogIntervalMs);
}

function connectPublic(){
  try{
    if(S.publicWs && (S.publicWs.readyState===WebSocket.OPEN || S.publicWs.readyState===WebSocket.CONNECTING)) return;
    const ws=new WebSocket('wss://api.derivws.com/trading/v1/options/ws/public');
    S.publicWs=ws;
    S.lastPublicError='';
    ws.onopen=()=>{
      S.connected=true;
      S.publicReconnectAttempts=0;
      S.lastPublicMessageAt=Date.now();
      S.lastTickAt=Date.now();
      S.feedReconnects++;
      S.lastPublicError='';
      ws.send(JSON.stringify({ticks:SYMBOL,subscribe:1,req_id:91001}));
      startFeedHealthTimers(ws);
      loadHistory();
      render();
    };
    ws.onmessage=e=>{
      S.lastPublicMessageAt=Date.now();
      let d;try{d=JSON.parse(e.data)}catch{return;}
      if(d.error){
        S.lastPublicError=d.error.message||d.error.code||'Deriv public feed error';
        render();
        return;
      }
      onPublic(d);
    };
    ws.onerror=()=>{
      S.lastPublicError='Public market WebSocket error';
      render();
    };
    ws.onclose=()=>{
      clearFeedHealthTimers();
      S.connected=false;
      if(S.publicWs===ws)S.publicWs=null;
      if(!S.lastPublicError)S.lastPublicError='Public feed disconnected';
      render();
      const delay=Math.min(30000,1500*Math.pow(1.7,S.publicReconnectAttempts++));
      clearTimeout(S.reconnectTimer);
      S.reconnectTimer=setTimeout(connectPublic,delay);
    };
  }catch(e){
    S.connected=false;
    S.lastPublicError=String(e?.message||e||'Public feed connection failed');
    render();
    clearTimeout(S.reconnectTimer);
    S.reconnectTimer=setTimeout(connectPublic,3000);
  }
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
  if(!S.connected || !S.historicalLoaded)return;
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


function gapBucket(g){
  if(g===0)return '0';
  if(g<=2)return '1-2';
  if(g<=5)return '3-5';
  if(g<=10)return '6-10';
  if(g<=20)return '11-20';
  if(g<=40)return '21-40';
  return '41+';
}
function countBucket(v, cut2=2){
  if(v===0)return '0';
  if(v===1)return '1';
  return `${cut2}+`;
}
function tagsFromFeatures(f={}){
  const tags=[];
  if(Number.isInteger(f.prevDigit)) tags.push({key:`prev:${f.prevDigit}`,label:`Previous digit = ${f.prevDigit}`});
  if(f.prevPair!=null) tags.push({key:`pair:${f.prevPair}`,label:`Previous pair = ${f.prevPair}`});
  if(Number.isFinite(f.gapSince9)) tags.push({key:`gap:${gapBucket(f.gapSince9)}`,label:`Gap since 9 = ${gapBucket(f.gapSince9)}`});
  if(Number.isFinite(f.count9_5)) tags.push({key:`c5:${countBucket(f.count9_5)}`,label:`9s in last 5 = ${countBucket(f.count9_5)}`});
  if(Number.isFinite(f.count9_10)) tags.push({key:`c10:${f.count9_10>=3?'3+':String(f.count9_10)}`,label:`9s in last 10 = ${f.count9_10>=3?'3+':f.count9_10}`});
  if(f.prevDigit===9) tags.push({key:'after9',label:'Immediately after 9'});
  if(f.prevPair==='99') tags.push({key:'after99',label:'Immediately after 99'});
  if(Number(f.count9_5)>=2) tags.push({key:'cluster5',label:'2+ nines in last 5'});
  if(Number(f.count9_10)>=3) tags.push({key:'cluster10',label:'3+ nines in last 10'});
  return tags;
}
function historicalFeaturesAt(arr,i){
  const prev=i>0?arr[i-1].digit:null;
  const prev2=i>1?arr[i-2].digit:null;
  let gap=i;
  for(let j=i-1,g=0;j>=0;j--,g++){ if(arr[j].digit===9){gap=g;break;} }
  const c5=arr.slice(Math.max(0,i-5),i).filter(x=>x.digit===9).length;
  const c10=arr.slice(Math.max(0,i-10),i).filter(x=>x.digit===9).length;
  return {prevDigit:prev,prev2Digit:prev2,prevPair:(prev2==null||prev==null)?null:`${prev2}${prev}`,gapSince9:gap,count9_5:c5,count9_10:c10};
}
function summarizeTagged(rows){
  const m=new Map();
  for(const row of rows){
    for(const tag of row.tags){
      let x=m.get(tag.key);if(!x){x={key:tag.key,label:tag.label,n:0,nines:0};m.set(tag.key,x);}
      x.n++; if(row.isNine)x.nines++;
    }
  }
  return [...m.values()].map(x=>({...x,nineRate:x.n?x.nines/x.n:null,winRate:x.n?1-x.nines/x.n:null}));
}
function discoveryPatternStats(){
  const a=S.discoveryTicks;
  const rows=[];
  for(let i=20;i<a.length;i++){
    const f=historicalFeaturesAt(a,i);
    rows.push({tags:tagsFromFeatures(f),isNine:a[i].digit===9});
  }
  return summarizeTagged(rows);
}
function forwardPatternStats(){
  const rows=S.records.filter(r=>r.kind==='SHADOW').map(r=>({tags:tagsFromFeatures(r.features||{}),isNine:r.digit===9}));
  return summarizeTagged(rows);
}
function wilsonUpper(k,n,z=1.96){
  if(!n)return null;
  const p=k/n, z2=z*z, den=1+z2/n;
  const ctr=p+z2/(2*n);
  const rad=z*Math.sqrt((p*(1-p)+z2/(4*n))/n);
  return (ctr+rad)/den;
}

function canonicalTag(tag){
  // Collapse logically equivalent market-state descriptions so one state is not counted as several discoveries.
  if(!tag) return tag;
  if(tag.key==='prev:9' || tag.key==='gap:0' || tag.key==='after9') return {key:'state:after9',label:'Immediately after 9'};
  if(tag.key==='cluster5' || tag.key==='c5:2+') return {key:'c5:2+',label:'9s in last 5 = 2+'};
  return tag;
}
function canonicalizeTags(tags){
  const m=new Map();
  for(const raw of tags||[]){const t=canonicalTag(raw); if(t && !m.has(t.key))m.set(t.key,t);}
  return [...m.values()];
}
function comboKey(tags){return canonicalizeTags(tags).map(t=>t.key).sort().join('&&');}
function comboLabel(tags){return canonicalizeTags(tags).map(t=>t.label).join(' + ');}
function simPnlFromCounts(n,nines){const wins=Math.max(0,(n||0)-(nines||0));return wins*.09-(nines||0);}
function summarizeCombos(rows, maxSize=2){
  const m=new Map();
  for(const row of rows){
    const unique=canonicalizeTags(row.tags);
    for(let i=0;i<unique.length;i++){
      for(let j=i+1;j<unique.length;j++){
        const tags=[unique[i],unique[j]], key=comboKey(tags);
        if(!key || !key.includes('&&'))continue;
        let x=m.get(key);
        if(!x){x={key,label:comboLabel(tags),tagKeys:canonicalizeTags(tags).map(t=>t.key).sort(),n:0,nines:0};m.set(key,x);}
        x.n++; if(row.isNine)x.nines++;
      }
    }
  }
  return [...m.values()].map(x=>({...x,nineRate:x.n?x.nines/x.n:null,winRate:x.n?1-x.nines/x.n:null,simPnl:simPnlFromCounts(x.n,x.nines)}));
}
function historicalPatternRows(){
  const a=S.discoveryTicks, rows=[];
  for(let i=20;i<a.length;i++){
    const f=historicalFeaturesAt(a,i);
    rows.push({tags:tagsFromFeatures(f),isNine:a[i].digit===9});
  }
  return rows;
}
function forwardPatternRows(){
  return S.records.filter(r=>r.kind==='SHADOW').map(r=>({tags:tagsFromFeatures(r.features||{}),isNine:r.digit===9}));
}
function combinationLabSnapshot(){
  const disc=summarizeCombos(historicalPatternRows())
    .filter(x=>x.n>=CFG.comboMinDiscoveryN && x.nineRate<CFG.breakEvenNineRate)
    .sort((a,b)=>a.nineRate-b.nineRate || b.n-a.n)
    .slice(0,CFG.comboMaxCandidates);
  const fwdMap=new Map(summarizeCombos(forwardPatternRows()).map(x=>[x.key,x]));
  let candidates=disc.map(d=>{
    const f0=fwdMap.get(d.key)||{n:0,nines:0,nineRate:null,winRate:null,simPnl:0};
    const f={...f0,simPnl:simPnlFromCounts(f0.n,f0.nines)};
    const upper95=f.n?wilsonUpper(f.nines,f.n):null;
    let status='DISCOVERY_ONLY';
    if(f.n>=CFG.patternMinValidatedForwardN && upper95!=null && upper95<CFG.breakEvenNineRate) status='FORWARD_VALIDATED';
    else if(f.n>=CFG.patternMinPromisingForwardN && f.nineRate!=null && f.nineRate<CFG.breakEvenNineRate) status='PROMISING_FORWARD';
    else if(f.n>=CFG.patternMinPromisingForwardN) status='NOT_CONFIRMED';
    const observationsToPromising=Math.max(0,CFG.patternMinPromisingForwardN-f.n);
    const observationsToValidation=Math.max(0,CFG.patternMinValidatedForwardN-f.n);
    return {...d,discovery:{...d,simPnl:simPnlFromCounts(d.n,d.nines)},forward:f,forwardUpper95:upper95,status,observationsToPromising,observationsToValidation};
  });
  const statusRank={FORWARD_VALIDATED:0,PROMISING_FORWARD:1,DISCOVERY_ONLY:2,NOT_CONFIRMED:3};
  candidates=candidates.sort((a,b)=>
    (statusRank[a.status]-statusRank[b.status]) ||
    ((a.forward.nineRate??1)-(b.forward.nineRate??1)) ||
    (b.forward.n-a.forward.n)
  );
  const cur=makePrediction();
  const currentTagKeys=new Set(canonicalizeTags(cur?tagsFromFeatures(cur.features):[]).map(t=>t.key));
  const activeCandidates=candidates.filter(c=>c.tagKeys.every(k=>currentTagKeys.has(k)));
  const watchlist=candidates
    .filter(c=>c.status==='FORWARD_VALIDATED' || c.status==='PROMISING_FORWARD' || (c.status==='DISCOVERY_ONLY' && c.forward.n>0 && c.forward.nineRate!=null && c.forward.nineRate<CFG.breakEvenNineRate))
    .sort((a,b)=>
      (statusRank[a.status]-statusRank[b.status]) ||
      ((a.forwardUpper95??1)-(b.forwardUpper95??1)) ||
      (b.forward.n-a.forward.n)
    )
    .slice(0,10);
  return {breakEvenNineRate:CFG.breakEvenNineRate,candidates,watchlist,activeCandidates,deduplication:{rules:['prev:9 = gap:0 = immediately after 9','cluster5 = 9s in last 5 = 2+']}};
}

function patternLabSnapshot(){
  const disc=discoveryPatternStats().filter(x=>x.n>=CFG.patternMinDiscoveryN);
  const fwdMap=new Map(forwardPatternStats().map(x=>[x.key,x]));
  const candidates=disc
    .filter(x=>x.nineRate<CFG.breakEvenNineRate)
    .sort((a,b)=>a.nineRate-b.nineRate || b.n-a.n)
    .slice(0,12)
    .map(d=>{
      const f=fwdMap.get(d.key)||{n:0,nines:0,nineRate:null,winRate:null};
      const upper95=f.n?wilsonUpper(f.nines,f.n):null;
      let status='DISCOVERY_ONLY';
      if(f.n>=CFG.patternMinValidatedForwardN && upper95!=null && upper95<CFG.breakEvenNineRate) status='FORWARD_VALIDATED';
      else if(f.n>=CFG.patternMinPromisingForwardN && f.nineRate!=null && f.nineRate<CFG.breakEvenNineRate) status='PROMISING_FORWARD';
      else if(f.n>=CFG.patternMinPromisingForwardN) status='NOT_CONFIRMED';
      return {key:d.key,label:d.label,discovery:d,forward:f,forwardUpper95:upper95,status};
    });
  const current=makePrediction();
  return {breakEvenNineRate:CFG.breakEvenNineRate,candidates,currentTags:current?tagsFromFeatures(current.features):[]};
}
function exportJSON(){
  const payload={schema:'DIGITMATCHSTAR_UNDER9_LAB_V2_6',generatedAt:nowISO(),version:VERSION,researchOnly:false,defaultMode:'SHADOW',currentMode:S.mode,symbol:SYMBOL,config:CFG,methodology:{historicalUsage:'DISCOVERY_ONLY',liveRecords:'FORWARD_ONLY',predictionFrozenBeforeOutcome:true,patternCandidatesSelectedFromHistoricalOnly:true,forwardValidationSeparated:true},executionStats:S.stats,thresholds:Object.fromEntries(CFG.thresholds.map(t=>[String(t),thresholdStats(t)])),patternLab:patternLabSnapshot(),combinationLab:combinationLabSnapshot(),feedHealth:{connected:S.connected,lastTickAt:S.lastTickAt,lastTickEpoch:S.lastTickEpoch,lastPublicMessageAt:S.lastPublicMessageAt,feedReconnects:S.feedReconnects,staleReconnects:S.staleReconnects,lastError:S.lastPublicError||''},records:S.records};
  const b=new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=`under9-lab-${SYMBOL}-${new Date().toISOString().replace(/[:.]/g,'-')}.json`;document.body.appendChild(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove();},1000);
}

async function setMode(m){
  if(!(await ensureAdminAuthorized(true)))return;
  if(m==='REAL') S.running=false;
  S.mode=m;S.authenticated=false;if(S.tradeWs){try{S.tradeWs.close()}catch(_){}}S.tradeWs=null;save();render();
}
async function toggleRun(){if(!(await ensureAdminAuthorized(true)))return;S.running=!S.running;if(S.running&&!S.connected)connectPublic();save();render();if(S.running&&S.mode!=='SHADOW')maybeExecute();}


function ensureStyles(){
  if(document.getElementById('u9v2-style')) return;
  const style=document.createElement('style');
  style.id='u9v2-style';
  style.textContent=`
    #${PANEL_ID}{position:fixed;right:12px;bottom:12px;z-index:2147483644;width:380px;max-width:calc(100vw - 24px);max-height:82vh;overflow:auto;background:linear-gradient(180deg,#08111f 0%,#0b1630 100%);color:#e5eefb;border:1px solid rgba(99,102,241,.28);border-radius:18px;box-shadow:0 18px 46px rgba(0,0,0,.46);font:12px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
    #${PANEL_ID} *{box-sizing:border-box}
    #${PANEL_ID} .u9-head{display:flex;justify-content:space-between;align-items:center;padding:12px 14px;background:linear-gradient(180deg,rgba(255,255,255,.06),rgba(255,255,255,.01));border-bottom:1px solid rgba(255,255,255,.08);cursor:move;position:sticky;top:0;backdrop-filter:blur(10px);z-index:2}
    #${PANEL_ID} .u9-title{font-size:21px;font-weight:900;letter-spacing:.03em;color:#f8fafc}
    #${PANEL_ID} .u9-sub{font-size:11px;color:#93c5fd;margin-top:2px}
    #${PANEL_ID} .u9-min{border:0;border-radius:12px;background:#16233d;color:#fff;width:34px;height:34px;font-size:20px;line-height:1;cursor:pointer;box-shadow:inset 0 0 0 1px rgba(255,255,255,.08)}
    #${PANEL_ID} .u9-body{padding:14px}
    #${PANEL_ID} .u9-status-row{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 12px}
    #${PANEL_ID} .u9-chip{display:inline-flex;align-items:center;gap:7px;padding:7px 10px;border-radius:999px;background:rgba(255,255,255,.05);font-size:11px;font-weight:700;border:1px solid rgba(255,255,255,.08)}
    #${PANEL_ID} .u9-chip .dot{width:9px;height:9px;border-radius:50%}
    #${PANEL_ID} .u9-chip.online .dot{background:#22c55e;box-shadow:0 0 10px rgba(34,197,94,.7)}
    #${PANEL_ID} .u9-chip.offline .dot{background:#ef4444;box-shadow:0 0 10px rgba(239,68,68,.55)}
    #${PANEL_ID} .u9-chip.warn .dot{background:#f59e0b;box-shadow:0 0 10px rgba(245,158,11,.55)}
    #${PANEL_ID} .u9-panel{background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.08);border-radius:14px;padding:11px 12px;margin-bottom:12px}
    #${PANEL_ID} .u9-mode-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px}
    #${PANEL_ID} .u9-mode-btn{border:1px solid rgba(255,255,255,.1);background:#122038;color:#dbeafe;padding:10px 8px;border-radius:12px;font-weight:800;cursor:pointer;transition:.15s ease all}
    #${PANEL_ID} .u9-mode-btn:hover{transform:translateY(-1px)}
    #${PANEL_ID} .u9-mode-btn.active.shadow{background:#17325c;color:#bfdbfe;border-color:#60a5fa}
    #${PANEL_ID} .u9-mode-btn.active.demo{background:#3b2c11;color:#fde68a;border-color:#fbbf24}
    #${PANEL_ID} .u9-mode-btn.active.real{background:#3a1212;color:#fecaca;border-color:#f87171}
    #${PANEL_ID} .u9-rule{font-size:12px;color:#cbd5e1;line-height:1.45}
    #${PANEL_ID} .u9-rule b{color:#fff}
    #${PANEL_ID} .u9-cta{width:100%;border:0;border-radius:14px;padding:12px 14px;font-size:15px;font-weight:900;cursor:pointer;color:#fff;transition:.15s ease transform;box-shadow:0 10px 22px rgba(0,0,0,.18)}
    #${PANEL_ID} .u9-cta:hover{transform:translateY(-1px)}
    #${PANEL_ID} .u9-cta.shadow{background:linear-gradient(180deg,#3b82f6,#1d4ed8)}
    #${PANEL_ID} .u9-cta.demo{background:linear-gradient(180deg,#f59e0b,#d97706)}
    #${PANEL_ID} .u9-cta.real{background:linear-gradient(180deg,#ef4444,#b91c1c)}
    #${PANEL_ID} .u9-cta.stop{background:linear-gradient(180deg,#64748b,#475569)}
    #${PANEL_ID} .u9-metrics{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin:12px 0}
    #${PANEL_ID} .u9-metric{background:rgba(15,23,42,.72);border:1px solid rgba(255,255,255,.07);border-radius:14px;padding:11px}
    #${PANEL_ID} .u9-metric-label{font-size:11px;color:#9fb0cf;margin-bottom:4px}
    #${PANEL_ID} .u9-metric-value{font-size:22px;font-weight:900;color:#fff;letter-spacing:.01em}
    #${PANEL_ID} .u9-metric.small .u9-metric-value{font-size:19px}
    #${PANEL_ID} .u9-table-wrap{margin-top:12px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.08);border-radius:14px;padding:8px 10px 10px}
    #${PANEL_ID} .u9-table-title{font-size:12px;font-weight:900;color:#e2e8f0;margin-bottom:6px}
    #${PANEL_ID} table{width:100%;border-collapse:collapse;font-size:11px}
    #${PANEL_ID} thead th{padding:7px 4px;color:#93c5fd;border-bottom:1px solid rgba(255,255,255,.08)}
    #${PANEL_ID} tbody td{padding:7px 4px;border-bottom:1px solid rgba(255,255,255,.05)}
    #${PANEL_ID} tbody tr:last-child td{border-bottom:0}
    #${PANEL_ID} .good{color:#4ade80;font-weight:800}
    #${PANEL_ID} .bad{color:#f87171;font-weight:800}
    #${PANEL_ID} .mid{color:#fbbf24;font-weight:800}
    #${PANEL_ID} .muted{color:#94a3b8}
    #${PANEL_ID} .u9-note{font-size:11px;color:#9fb0cf;line-height:1.45;margin-top:10px}
    #${PANEL_ID} .u9-export{width:100%;margin-top:12px;padding:11px 14px;border-radius:14px;border:1px solid rgba(255,255,255,.08);background:#122038;color:#fff;font-weight:900;cursor:pointer}
    #${PANEL_ID} .u9-banner{display:flex;align-items:center;justify-content:space-between;gap:10px;background:linear-gradient(90deg,rgba(99,102,241,.16),rgba(16,185,129,.12));border:1px solid rgba(255,255,255,.08);border-radius:14px;padding:11px 12px;margin-bottom:12px}
    #${PANEL_ID} .u9-banner .label{font-size:11px;color:#a5b4fc;font-weight:900;letter-spacing:.05em}
    #${PANEL_ID} .u9-banner .value{font-size:14px;color:#fff;font-weight:900}
    #${PANEL_ID} .u9-pattern-row{display:grid;grid-template-columns:1.6fr .7fr .7fr;gap:6px;align-items:center;padding:8px 4px;border-bottom:1px solid rgba(255,255,255,.05)}
    #${PANEL_ID} .u9-pattern-row:last-child{border-bottom:0}
    #${PANEL_ID} .u9-pattern-name{font-size:11px;color:#e2e8f0;font-weight:700}
    #${PANEL_ID} .u9-badge{display:inline-block;padding:3px 6px;border-radius:999px;font-size:9px;font-weight:900;margin-top:3px}
    #${PANEL_ID} .u9-badge.valid{background:rgba(34,197,94,.16);color:#86efac}
    #${PANEL_ID} .u9-badge.prom{background:rgba(245,158,11,.16);color:#fde68a}
    #${PANEL_ID} .u9-badge.disc{background:rgba(96,165,250,.16);color:#bfdbfe}
    #${PANEL_ID} .u9-badge.no{background:rgba(248,113,113,.16);color:#fecaca}
    #${PANEL_ID} .u9-badge.validated{background:rgba(34,197,94,.16);color:#86efac}
    #${PANEL_ID} .u9-badge.promising{background:rgba(245,158,11,.16);color:#fde68a}
    #${PANEL_ID} .u9-badge.discovery{background:rgba(96,165,250,.16);color:#bfdbfe}
    #${PANEL_ID} .u9-badge.rejected{background:rgba(248,113,113,.16);color:#fecaca}
    #${PANEL_ID} .u9-watch{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center;padding:9px 0;border-bottom:1px solid rgba(255,255,255,.06)}
    #${PANEL_ID} .u9-watch:last-child{border-bottom:0}
    #${PANEL_ID} .u9-watch-name{font-weight:800;color:#f8fafc;line-height:1.25}
    #${PANEL_ID} .u9-watch-meta{font-size:10px;color:#94a3b8;margin-top:3px}
    #${PANEL_ID} .u9-pnl-pos{color:#4ade80;font-weight:900}
    #${PANEL_ID} .u9-pnl-neg{color:#f87171;font-weight:900}
  `;
  document.head.appendChild(style);
}


function makePanel(){
  if(!S.adminAuthorized)return;
  ensureStyles();
  if($(PANEL_ID))return;
  const p=document.createElement('div');p.id=PANEL_ID;
  p.innerHTML=`<div id="u9v2-head" class="u9-head"><div><div class="u9-title">UNDER 9 LAB</div><div class="u9-sub">${VERSION}</div></div><button id="u9v2-min" class="u9-min">−</button></div><div id="u9v2-body" class="u9-body"></div>`;
  document.body.appendChild(p);
  let col=false;
  $('u9v2-min').onclick=()=>{col=!col;$('u9v2-body').style.display=col?'none':'block';$('u9v2-min').textContent=col?'+':'−';};
  let drag=null;
  $('u9v2-head').addEventListener('pointerdown',e=>{if(e.target.closest('button'))return;const r=p.getBoundingClientRect();drag={dx:e.clientX-r.left,dy:e.clientY-r.top};p.style.right='auto';p.style.bottom='auto';e.preventDefault();});
  document.addEventListener('pointermove',e=>{if(!drag)return;p.style.left=Math.max(0,Math.min(innerWidth-p.offsetWidth,e.clientX-drag.dx))+'px';p.style.top=Math.max(0,Math.min(innerHeight-p.offsetHeight,e.clientY-drag.dy))+'px';});
  document.addEventListener('pointerup',()=>drag=null);
}

function statusChip(kind,label){
  return `<div class="u9-chip ${kind}"><span class="dot"></span><span>${label}</span></div>`;
}
function colorValue(v, goodThreshold, badThreshold, inverse=false){
  if(v==null) return 'muted';
  if(!inverse){
    if(v>=goodThreshold) return 'good';
    if(v<=badThreshold) return 'bad';
  } else {
    if(v<=goodThreshold) return 'good';
    if(v>=badThreshold) return 'bad';
  }
  return 'mid';
}
function render(){
  if(!S.adminAuthorized){hidePrivateLab();return;}
  makePanel();const el=$('u9v2-body');if(!el)return;const pred=S.pendingShadow||makePrediction();
  const liveCount=S.liveTicks.length;
  const warm = featureUniverse().length;
  const feedStatus=S.connected?'CONNECTED':'OFFLINE';
  const authStatus=S.mode==='SHADOW' ? 'NOT NEEDED' : (S.authenticated?'READY':'WAITING');
  const histStatus=S.historicalLoaded?`${S.discoveryTicks.length}/${CFG.historyCount}`:`${S.discoveryTicks.length}/${CFG.historyCount}`;
  const modeClass=S.mode.toLowerCase();
  const effectiveActive=S.running && S.connected && S.historicalLoaded;
  const waiting=S.running && !effectiveActive;
  const runLabel=S.running?`STOP ${S.mode}`:`START ${S.mode}`;
  const runBtnClass=S.running?'stop':modeClass;
  const acceptedText=pred? (pred.accept?'YES':'NO') : 'WARMING';
  const acceptedClass=pred? (pred.accept?'good':'bad') : 'mid';
  const nextP9Class=pred? colorValue(pred.p9,0.06,0.082569,true):'mid';
  const under9Class=pred? colorValue(pred.winProb,0.917431,0.88,false):'mid';
  const rows=CFG.thresholds.map(t=>{
    const x=thresholdStats(t);
    const winClass=colorValue(x.winRate,0.917431,0.88,false);
    const nineClass=colorValue(x.nineRate,0.082569,0.12,true);
    const pnlClass=x.simPnl>0?'good':x.simPnl<0?'bad':'muted';
    return `<tr><td align="left">≤ ${(t*100).toFixed(0)}%</td><td align="right">${x.n}</td><td align="right" class="${winClass}">${pct(x.winRate)}</td><td align="right" class="${nineClass}">${pct(x.nineRate)}</td><td align="right" class="${pnlClass}">${money(x.simPnl)}</td></tr>`;
  }).join('');
  const activeTradeSummary=S.activeTrade ? `Contract #${S.activeTrade.contractId} active` : (S.pendingProposal ? 'Waiting for proposal / buy' : (effectiveActive ? 'Watching for qualified signals' : waiting ? 'Waiting for market feed + history' : 'Runner is idle'));
  const patternLab=patternLabSnapshot();
  const comboLab=combinationLabSnapshot();
  const patternRows=patternLab.candidates.slice(0,8).map(c=>{
    const badgeClass=c.status==='FORWARD_VALIDATED'?'valid':c.status==='PROMISING_FORWARD'?'prom':c.status==='NOT_CONFIRMED'?'no':'disc';
    const badgeText=c.status==='FORWARD_VALIDATED'?'VALIDATED':c.status==='PROMISING_FORWARD'?'PROMISING':c.status==='NOT_CONFIRMED'?'NOT CONFIRMED':'DISCOVERY';
    return `<div class="u9-pattern-row"><div><div class="u9-pattern-name">${c.label}</div><span class="u9-badge ${badgeClass}">${badgeText}</span></div><div style="text-align:right"><span class="muted">Hist</span><br><b>${pct(c.discovery.nineRate)}</b><br><span class="muted">n=${c.discovery.n}</span></div><div style="text-align:right"><span class="muted">Forward</span><br><b class="${colorValue(c.forward.nineRate,CFG.breakEvenNineRate,0.12,true)}">${pct(c.forward.nineRate)}</b><br><span class="muted">n=${c.forward.n}</span></div></div>`;
  }).join('');

  const comboRows=comboLab.candidates.slice(0,10).map(c=>{
    const badgeClass=c.status==='FORWARD_VALIDATED'?'validated':c.status==='PROMISING_FORWARD'?'promising':c.status==='NOT_CONFIRMED'?'rejected':'discovery';
    const badgeText=c.status==='FORWARD_VALIDATED'?'VALIDATED':c.status==='PROMISING_FORWARD'?'PROMISING':c.status==='NOT_CONFIRMED'?'NOT CONFIRMED':'DISCOVERY';
    const pnlClass=c.forward.simPnl>0?'u9-pnl-pos':c.forward.simPnl<0?'u9-pnl-neg':'muted';
    return `<div class="u9-pattern-row"><div><div class="u9-pattern-name">${c.label}</div><span class="u9-badge ${badgeClass}">${badgeText}</span></div><div style="text-align:right"><span class="muted">Forward</span><br><b class="${colorValue(c.forward.nineRate,CFG.breakEvenNineRate,0.12,true)}">${pct(c.forward.nineRate)}</b><br><span class="muted">n=${c.forward.n}</span></div><div style="text-align:right"><span class="muted">Sim P&L</span><br><b class="${pnlClass}">${money(c.forward.simPnl)}</b><br><span class="muted">95% up ${pct(c.forwardUpper95)}</span></div></div>`;
  }).join('');

  const watchRows=comboLab.watchlist.map(c=>{
    const need=c.status==='FORWARD_VALIDATED'?'validated':`${c.observationsToValidation} more to n=${CFG.patternMinValidatedForwardN}`;
    const pnlClass=c.forward.simPnl>0?'u9-pnl-pos':c.forward.simPnl<0?'u9-pnl-neg':'muted';
    return `<div class="u9-watch"><div><div class="u9-watch-name">${c.label}</div><div class="u9-watch-meta">${c.status.replaceAll('_',' ')} · ${need} · 95% upper ${pct(c.forwardUpper95)}</div></div><div style="text-align:right"><div class="${pnlClass}">${money(c.forward.simPnl)}</div><div class="u9-watch-meta">9-rate ${pct(c.forward.nineRate)} · n=${c.forward.n}</div></div></div>`;
  }).join('');

  el.innerHTML=`
    <div class="u9-status-row">
      ${statusChip(S.connected?'online':'offline',`Feed ${feedStatus}${S.lastTickAt?` · ${Math.max(0,Math.round((Date.now()-S.lastTickAt)/1000))}s`:''}`)}
      ${statusChip(S.historicalLoaded?'online':'warn',`Historical ${histStatus}`)}
      ${statusChip(S.running?'online':'warn',`Runner ${S.running?'ON':'OFF'}`)}
      ${statusChip((S.mode==='SHADOW'||S.authenticated)?'online':'warn',`${S.mode} auth ${authStatus}`)}
    </div>

    <div class="u9-banner">
      <div>
        <div class="label">CURRENT MODE</div>
        <div class="value">${S.mode} · ${effectiveActive?'ACTIVE':waiting?'WAITING FOR FEED':'STANDBY'}</div>
      </div>
      <div class="muted" style="text-align:right;font-size:11px">
        Warm-up ticks: <b>${Math.min(warm,300)}/300</b><br>
        Live forward ticks: <b>${liveCount}</b>
      </div>
    </div>

    <div class="u9-mode-grid">
      <button id="u9-shadow" class="u9-mode-btn ${S.mode==='SHADOW'?'active shadow':''}">SHADOW</button>
      <button id="u9-demo" class="u9-mode-btn ${S.mode==='DEMO'?'active demo':''}">DEMO</button>
      <button id="u9-real" class="u9-mode-btn ${S.mode==='REAL'?'active real':''}">REAL</button>
    </div>

    ${S.lastPublicError?`<div class="u9-panel" style="border-color:rgba(248,113,113,.45);background:rgba(127,29,29,.18)"><div class="u9-rule"><b style="color:#fca5a5">Feed issue:</b> ${S.lastPublicError}</div></div>`:''}

    <div class="u9-panel">
      <div class="u9-rule"><b>Rule:</b> trade only when <b>P(9) ≤ ${(CFG.threshold*100).toFixed(0)}%</b>. Contract: <b>UNDER 9</b>. Flat stake: <b>$${CFG.stake.toFixed(2)}</b>.</div>
      <div class="u9-note" style="margin-top:8px">Status: ${activeTradeSummary}<br><span class="muted">Feed reconnects: ${S.feedReconnects} · stale recoveries: ${S.staleReconnects}${S.lastPublicError?` · ${S.lastPublicError}`:''}</span></div>
    </div>

    <button id="u9-run" class="u9-cta ${runBtnClass}">${runLabel}</button>

    <div class="u9-metrics">
      <div class="u9-metric">
        <div class="u9-metric-label">Next P(9)</div>
        <div class="u9-metric-value ${nextP9Class}">${pred?pct(pred.p9):'warming'}</div>
      </div>
      <div class="u9-metric">
        <div class="u9-metric-label">Under-9 win prob</div>
        <div class="u9-metric-value ${under9Class}">${pred?pct(pred.winProb):'—'}</div>
      </div>
      <div class="u9-metric small">
        <div class="u9-metric-label">Current signal accepted?</div>
        <div class="u9-metric-value ${acceptedClass}">${acceptedText}</div>
      </div>
      <div class="u9-metric small">
        <div class="u9-metric-label">Executed contracts</div>
        <div class="u9-metric-value">${S.stats.contracts}</div>
      </div>
      <div class="u9-metric small">
        <div class="u9-metric-label">Execution P&L</div>
        <div class="u9-metric-value ${S.stats.pnl>0?'good':S.stats.pnl<0?'bad':'muted'}">${money(S.stats.pnl)}</div>
      </div>
      <div class="u9-metric small">
        <div class="u9-metric-label">Wins / Losses</div>
        <div class="u9-metric-value">${S.stats.wins} / ${S.stats.losses}</div>
      </div>
    </div>

    <div class="u9-table-wrap">
      <div class="u9-table-title">Forward threshold scoreboard</div>
      <table>
        <thead><tr><th align="left">P(9) filter</th><th align="right">N</th><th align="right">Win rate</th><th align="right">9 rate</th><th align="right">Sim P&L</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>

    <div class="u9-table-wrap">
      <div class="u9-table-title">Pattern Lab · historical discovery vs fresh forward proof</div>
      <div class="u9-note" style="margin:0 0 6px">Candidates below are selected from the locked historical discovery sample. They are <b>not</b> allowed to become “validated” until enough fresh forward observations confirm them.</div>
      ${patternRows || '<div class="u9-note">Pattern candidates will appear after the historical discovery sample is available.</div>'}
    </div>

    <div class="u9-table-wrap">
      <div class="u9-table-title">Combination Lab · deduplicated and ranked by forward evidence</div>
      <div class="u9-note" style="margin:0 0 6px">Equivalent states are collapsed so the same underlying condition cannot appear multiple times under different names. Sim P&L assumes +$0.09 per win and -$1.00 per digit-9 loss.</div>
      ${comboRows || '<div class="u9-note">Combination candidates will appear after discovery history is available.</div>'}
    </div>

    <div class="u9-table-wrap">
      <div class="u9-table-title">Forward Watchlist · strongest candidates still alive</div>
      <div class="u9-note" style="margin:0 0 6px">“More to n=200” is only the sample-count requirement. A candidate is validated only if its 95% upper risk bound also remains below the 8.26% break-even 9-rate.</div>
      ${watchRows || '<div class="u9-note">No combination currently qualifies for the watchlist.</div>'}
    </div>

    <div class="u9-panel">
      <div class="u9-table-title">Current market state</div>
      <div class="u9-note" style="margin-top:4px">${patternLab.currentTags.length?patternLab.currentTags.map(x=>x.label).join(' · '):'Waiting for enough ticks'}</div>
    </div>

    <div class="u9-note">Historical 5,000 ticks are used for <b>discovery only</b>. The threshold table and Pattern Lab forward column use <b>future-only observations</b>. Break-even requires the accepted digit-9 rate to stay below <b>8.26%</b> for the assumed <b>$1 stake / $0.09 profit</b>. Pattern candidates are research signals only until they earn a fresh forward sample.</div>
    <button id="u9-export" class="u9-export">Export Under-9 JSON + Ranked Watchlist</button>`;
  $('u9-shadow').onclick=()=>setMode('SHADOW');
  $('u9-demo').onclick=()=>setMode('DEMO');
  $('u9-real').onclick=()=>setMode('REAL');
  $('u9-run').onclick=toggleRun;
  $('u9-export').onclick=exportJSON;
}

window.DMSUnder9Lab={
  version:VERSION,
  getSnapshot:()=>S.adminAuthorized?({version:VERSION,mode:S.mode,running:S.running,stats:S.stats,pending:S.pendingShadow,historicalTicks:S.discoveryTicks.length,liveTicks:S.liveTicks.length,patternLab:patternLabSnapshot(),combinationLab:combinationLabSnapshot(),feedHealth:{connected:S.connected,lastTickAt:S.lastTickAt,lastTickEpoch:S.lastTickEpoch,feedReconnects:S.feedReconnects,staleReconnects:S.staleReconnects,lastError:S.lastPublicError||''},privateAdmin:true}):null,
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

window.addEventListener('focus',()=>{
  if(S.adminAuthorized && (!S.connected || (S.lastTickAt && Date.now()-S.lastTickAt>CFG.staleFeedMs))) forcePublicReconnect('Window resumed — refreshing feed');
});
document.addEventListener('visibilitychange',()=>{
  if(!document.hidden && S.adminAuthorized && (!S.connected || (S.lastTickAt && Date.now()-S.lastTickAt>CFG.staleFeedMs))) forcePublicReconnect('Tab resumed — refreshing feed');
});
bootPrivateLab();
})();
