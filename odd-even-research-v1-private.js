/*
 * DigitMatchStar — Odd / Even Research + Execution Lab v1.0
 * Admin-only. Modes: SHADOW, DEMO, REAL. REAL never auto-resumes after reload.
 * Research objective: discover and forward-test parity states against live proposal economics.
 * Execution: manual ODD / EVEN buttons, or conservative AUTO mode after forward evidence.
 */
(() => {
'use strict';

const VERSION = 'ODDEVEN-LAB-V1.0-FORWARD-EXEC';
const SYMBOL = 'R_10';
const STORE = `oddeven_lab_v1_${SYMBOL}`;
const PANEL_ID = 'oddeven-lab-v1-panel';
const DEFAULT_APP_ID = 1089;
const CFG = {
  symbol: SYMBOL,
  historyCount: 5000,
  featureBuffer: 5000,
  maxRecords: 30000,
  defaultStake: 1,
  assumedWinProfitPerDollar: 0.95,
  assumedBreakEvenWinRate: 1 / 1.95,
  minDiscoveryN: 40,
  maxCandidates: 24,
  minForwardNForAuto: 300,
  autoMinObservedWinRate: 0.53,
  autoMinWilsonLower95: 1 / 1.95,
  minSignalEdgeOverProposalBE: 0.01,
  cooldownMs: 250,
  staleFeedMs: 12000,
  watchdogIntervalMs: 4000,
  pingIntervalMs: 15000,
};

const S = {
  mode: 'SHADOW',
  runner: false,
  autoSide: 'AUTO', // AUTO, ODD, EVEN
  stake: CFG.defaultStake,
  connected: false,
  authenticated: false,
  publicWs: null,
  tradeWs: null,
  pipSize: 3,
  discoveryTicks: [],
  liveTicks: [],
  totalForwardTicks: 0,
  forwardRecords: [],
  executionRecords: [],
  candidates: [],
  candidatesFrozenAt: null,
  historicalLoaded: false,
  pendingSignal: null,
  pendingProposal: null,
  activeTrade: null,
  stats: {contracts:0,wins:0,losses:0,pnl:0},
  adminAuthorized: false,
  adminLastCheckedAt: 0,
  adminCheckInFlight: false,
  lastPublicMessageAt: 0,
  lastTickAt: 0,
  lastTickEpoch: null,
  feedConnectionsOpened: 0,
  staleReconnects: 0,
  lastPublicError: '',
  reconnectTimer: null,
  reconnectAttempts: 0,
  watchdogTimer: null,
  pingTimer: null,
  lastTradeAt: 0,
  wakeLock: null,
  wakeLockRequested: false,
  minimized: false,
  panelPos: null,
};

const $ = id => document.getElementById(id);
const nowISO = () => new Date().toISOString();
const clamp = (x,a,b) => Math.max(a,Math.min(b,x));
const pct = v => v==null || !Number.isFinite(v) ? '—' : `${(100*v).toFixed(2)}%`;
const money = v => `${Number(v||0)<0?'-':'+'}$${Math.abs(Number(v||0)).toFixed(2)}`;
const parity = d => d % 2 ? 'ODD' : 'EVEN';
const opposite = p => p === 'ODD' ? 'EVEN' : 'ODD';
const last = (a,n) => a.slice(Math.max(0,a.length-n));

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
    const token=getToken(), accountId=getAccount();
    if(!token || !accountId){ S.adminAuthorized=false; S.adminLastCheckedAt=now; hidePrivateLab(); return false; }
    const response=await fetch('/api/capture-access',{
      method:'POST',
      headers:{'Content-Type':'application/json','Authorization':`Bearer ${token}`},
      credentials:'same-origin',
      body:JSON.stringify({account_id:accountId})
    });
    if(!response.ok){ S.adminAuthorized=false; S.adminLastCheckedAt=now; hidePrivateLab(); return false; }
    const data=await response.json().catch(()=>({}));
    S.adminAuthorized=!!(data.allowed===true || data.authorized===true || data.captureAllowed===true || data.captureAdmin===true || data.ok===true);
    S.adminLastCheckedAt=now;
    if(!S.adminAuthorized) hidePrivateLab();
    return S.adminAuthorized;
  }catch(_){
    S.adminAuthorized=false; S.adminLastCheckedAt=now; hidePrivateLab(); return false;
  }finally{ S.adminCheckInFlight=false; }
}

function hidePrivateLab(){
  const p=$(PANEL_ID); if(p) p.remove();
  S.runner=false;
  if(S.publicWs){ try{S.publicWs.close();}catch(_){} }
  if(S.tradeWs){ try{S.tradeWs.close();}catch(_){} }
  S.publicWs=null; S.tradeWs=null; S.connected=false; S.authenticated=false;
}

function load(){
  try{
    const x=JSON.parse(localStorage.getItem(STORE)||'{}');
    if(Array.isArray(x.discoveryTicks)) S.discoveryTicks=x.discoveryTicks.slice(-CFG.historyCount);
    if(Array.isArray(x.liveTicks)) S.liveTicks=x.liveTicks.slice(-CFG.featureBuffer);
    if(Array.isArray(x.forwardRecords)) S.forwardRecords=x.forwardRecords.slice(-CFG.maxRecords);
    if(Array.isArray(x.executionRecords)) S.executionRecords=x.executionRecords.slice(-2000);
    if(Array.isArray(x.candidates)) S.candidates=x.candidates;
    if(x.candidatesFrozenAt) S.candidatesFrozenAt=x.candidatesFrozenAt;
    S.totalForwardTicks=Math.max(Number(x.totalForwardTicks||0),S.forwardRecords.length,S.liveTicks.length);
    if(x.stats) S.stats=x.stats;
    if(x.mode) S.mode=x.mode;
    if(x.autoSide) S.autoSide=x.autoSide;
    if(Number.isFinite(Number(x.stake))) S.stake=clamp(Number(x.stake),0.35,1000);
    if(typeof x.runner==='boolean') S.runner=x.runner;
    if(typeof x.wakeLockRequested==='boolean') S.wakeLockRequested=x.wakeLockRequested;
    if(typeof x.minimized==='boolean') S.minimized=x.minimized;
    if(x.panelPos && Number.isFinite(x.panelPos.left) && Number.isFinite(x.panelPos.top)) S.panelPos=x.panelPos;
    S.historicalLoaded=S.discoveryTicks.length>=300;
  }catch(_){ }
  // REAL must always require a fresh user action after reload.
  if(S.mode==='REAL'){ S.mode='SHADOW'; S.runner=false; }
}

function save(){
  try{
    localStorage.setItem(STORE,JSON.stringify({
      discoveryTicks:S.discoveryTicks.slice(-CFG.historyCount),
      liveTicks:S.liveTicks.slice(-CFG.featureBuffer),
      forwardRecords:S.forwardRecords.slice(-CFG.maxRecords),
      executionRecords:S.executionRecords.slice(-2000),
      candidates:S.candidates,
      candidatesFrozenAt:S.candidatesFrozenAt,
      totalForwardTicks:S.totalForwardTicks,
      stats:S.stats, mode:S.mode, autoSide:S.autoSide, stake:S.stake, runner:S.runner,
      wakeLockRequested:S.wakeLockRequested, minimized:S.minimized, panelPos:S.panelPos
    }));
  }catch(_){ }
}

function digitFromQuote(q,pip=S.pipSize){
  const n=Number(q); if(!Number.isFinite(n)) return null;
  const s=n.toFixed(pip), d=Number(s[s.length-1]);
  return Number.isInteger(d)?d:null;
}

function oddRate(arr,n){
  const a=last(arr,n); if(!a.length) return .5;
  return a.filter(x=>x.parity==='ODD').length/a.length;
}
function parityRun(arr){
  if(!arr.length) return {side:null,len:0};
  const side=arr[arr.length-1].parity; let len=0;
  for(let i=arr.length-1;i>=0;i--){ if(arr[i].parity!==side) break; len++; }
  return {side,len};
}
function runBucket(n){ return n>=5?'5+':n>=3?'3-4':n===2?'2':'1'; }

function featureUniverse(){ return [...S.discoveryTicks,...S.liveTicks].slice(-(CFG.historyCount+CFG.featureBuffer)); }

function currentFeatureState(arr=featureUniverse()){
  if(arr.length<20) return null;
  const prev=arr[arr.length-1], prev2=arr.length>=2?arr[arr.length-2]:null;
  const run=parityRun(arr);
  const o5=Math.round(oddRate(arr,5)*5);
  const o10=Math.round(oddRate(arr,10)*10);
  const o20=Math.round(oddRate(arr,20)*20);
  return {
    prevDigit:prev.digit,
    prevParity:prev.parity,
    prevPair:prev2?`${prev2.digit}${prev.digit}`:null,
    prevParityPair:prev2?`${prev2.parity[0]}${prev.parity[0]}`:null,
    runSide:run.side,
    runLen:run.len,
    runBucket:runBucket(run.len),
    odd5:o5, odd10:o10, odd20:o20,
  };
}

function tagsForState(f){
  if(!f) return [];
  const tags=[
    {key:`prevDigit:${f.prevDigit}`,label:`Previous digit = ${f.prevDigit}`},
    {key:`prevParity:${f.prevParity}`,label:`Previous parity = ${f.prevParity}`},
    {key:`run:${f.runSide}:${f.runBucket}`,label:`${f.runSide} run = ${f.runBucket}`},
    {key:`odd5:${f.odd5}`,label:`Odd count in last 5 = ${f.odd5}`},
    {key:`odd10:${f.odd10}`,label:`Odd count in last 10 = ${f.odd10}`},
  ];
  if(f.prevParityPair) tags.push({key:`parityPair:${f.prevParityPair}`,label:`Parity pair = ${f.prevParityPair}`});
  return tags;
}

function buildHistoricalObservations(){
  const a=S.discoveryTicks; const obs=[];
  for(let i=20;i<a.length-1;i++){
    const hist=a.slice(0,i+1);
    const f=currentFeatureState(hist), outcome=a[i+1];
    if(!f||!outcome) continue;
    const tags=tagsForState(f);
    obs.push({tags,outcome:outcome.parity});
  }
  return obs;
}

function freezeCandidatesFromHistory(){
  if(!S.historicalLoaded || S.discoveryTicks.length<300) return;
  if(S.candidates.length) return;
  const obs=buildHistoricalObservations();
  const map=new Map();
  for(const o of obs){
    for(const t of o.tags){
      const x=map.get(t.key)||{key:t.key,label:t.label,n:0,odd:0,even:0};
      x.n++; if(o.outcome==='ODD')x.odd++; else x.even++; map.set(t.key,x);
    }
  }
  const singles=[...map.values()].filter(x=>x.n>=CFG.minDiscoveryN).map(x=>{
    const oddRate=x.odd/x.n, side=oddRate>=.5?'ODD':'EVEN', winRate=Math.max(oddRate,1-oddRate);
    return {...x,type:'single',side,discoveryWinRate:winRate,discoveryEdge:winRate-.5};
  });

  // Pair combinations are frozen from history only. Limit to interpretable combinations.
  const pairMap=new Map();
  for(const o of obs){
    const usable=o.tags.filter(t=>!t.key.startsWith('parityPair:'));
    for(let i=0;i<usable.length;i++) for(let j=i+1;j<usable.length;j++){
      const ks=[usable[i].key,usable[j].key].sort(), key=ks.join('&&');
      const labels=[usable[i],usable[j]].sort((a,b)=>a.key.localeCompare(b.key)).map(x=>x.label);
      const x=pairMap.get(key)||{key,label:labels.join(' + '),tagKeys:ks,n:0,odd:0,even:0};
      x.n++; if(o.outcome==='ODD')x.odd++; else x.even++; pairMap.set(key,x);
    }
  }
  const pairs=[...pairMap.values()].filter(x=>x.n>=CFG.minDiscoveryN).map(x=>{
    const oddRate=x.odd/x.n, side=oddRate>=.5?'ODD':'EVEN', winRate=Math.max(oddRate,1-oddRate);
    return {...x,type:'combo',side,discoveryWinRate:winRate,discoveryEdge:winRate-.5};
  });
  S.candidates=[...singles,...pairs]
    .sort((a,b)=>b.discoveryEdge-a.discoveryEdge || b.n-a.n)
    .slice(0,CFG.maxCandidates)
    .map(x=>({...x,forwardN:0,forwardWins:0,forwardLosses:0}));
  S.candidatesFrozenAt=nowISO();
  save();
}

function candidateMatches(c,tags){
  const set=new Set(tags.map(x=>x.key));
  if(c.type==='single') return set.has(c.key);
  return Array.isArray(c.tagKeys) && c.tagKeys.every(k=>set.has(k));
}

function wilsonLower95(wins,n){
  if(!n) return 0;
  const z=1.959963984540054, p=wins/n, z2=z*z;
  return (p+z2/(2*n)-z*Math.sqrt((p*(1-p)+z2/(4*n))/n))/(1+z2/n);
}
function wilsonUpper95(wins,n){
  if(!n) return 1;
  const z=1.959963984540054, p=wins/n, z2=z*z;
  return (p+z2/(2*n)+z*Math.sqrt((p*(1-p)+z2/(4*n))/n))/(1+z2/n);
}

function candidateForwardStats(c){
  const n=c.forwardN||0,w=c.forwardWins||0,wr=n?w/n:null;
  return {n,wins:w,losses:c.forwardLosses||0,winRate:wr,lower95:n?wilsonLower95(w,n):null,upper95:n?wilsonUpper95(w,n):null};
}

function updateCandidatesForOutcome(tags,outcome){
  for(const c of S.candidates){
    if(!candidateMatches(c,tags)) continue;
    c.forwardN=(c.forwardN||0)+1;
    if(outcome===c.side)c.forwardWins=(c.forwardWins||0)+1; else c.forwardLosses=(c.forwardLosses||0)+1;
  }
}

function currentSignal(){
  const f=currentFeatureState(), tags=tagsForState(f);
  if(!f) return null;
  const matches=S.candidates.filter(c=>candidateMatches(c,tags)).map(c=>({c,s:candidateForwardStats(c)}));
  if(!matches.length) return {features:f,tags,side:null,probability:null,candidate:null,status:'NO_FROZEN_MATCH'};

  // Execution never changes a candidate's frozen side. Prefer forward-supported states; otherwise discovery leader for shadow display only.
  matches.sort((a,b)=>{
    const aReady=a.s.n>=CFG.minForwardNForAuto?1:0,bReady=b.s.n>=CFG.minForwardNForAuto?1:0;
    if(aReady!==bReady)return bReady-aReady;
    const al=a.s.lower95??0, bl=b.s.lower95??0;
    if(al!==bl)return bl-al;
    return b.c.discoveryEdge-a.c.discoveryEdge;
  });
  const best=matches[0], probability=best.s.n?best.s.winRate:best.c.discoveryWinRate;
  const autoReady=best.s.n>=CFG.minForwardNForAuto && best.s.winRate>=CFG.autoMinObservedWinRate && best.s.lower95>=CFG.autoMinWilsonLower95;
  return {features:f,tags,side:best.c.side,probability,candidate:best.c,forward:best.s,status:autoReady?'AUTO_READY':'RESEARCH_ONLY'};
}

function scoreForwardOutcome(digit,epoch,quote){
  const p=S.pendingSignal; if(!p) return;
  const outcome=parity(digit);
  updateCandidatesForOutcome(p.tags,outcome);
  S.forwardRecords.push({
    kind:'FORWARD',predictedAt:p.predictedAt,outcomeAt:nowISO(),epoch:Number(epoch),quote:Number(quote),digit,outcome,
    selectedSide:p.side,win:p.side?outcome===p.side:null,candidateKey:p.candidate?.key||null,candidateLabel:p.candidate?.label||null,
    candidateStatus:p.status,features:p.features,tags:p.tags.map(x=>x.key)
  });
  if(S.forwardRecords.length>CFG.maxRecords)S.forwardRecords.splice(0,S.forwardRecords.length-CFG.maxRecords);
  S.pendingSignal=null; save();
}

async function loadHistory(){
  if(S.historicalLoaded || !S.publicWs || S.publicWs.readyState!==WebSocket.OPEN) return;
  S.publicWs.send(JSON.stringify({ticks_history:SYMBOL,end:'latest',count:CFG.historyCount,style:'ticks',adjust_start_time:1,req_id:95001}));
}

function onPublic(d){
  if(d.msg_type==='history' && d.history){
    const prices=d.history.prices||[], times=d.history.times||[], out=[];
    for(let i=0;i<prices.length;i++){
      const dig=digitFromQuote(prices[i]);
      if(dig!=null)out.push({digit:dig,parity:parity(dig),quote:Number(prices[i]),epoch:Number(times[i]||0),source:'HISTORICAL_DISCOVERY'});
    }
    S.discoveryTicks=out.slice(-CFG.historyCount); S.historicalLoaded=true;
    freezeCandidatesFromHistory(); save(); render(); return;
  }
  if(d.msg_type!=='tick'||!d.tick) return;
  S.lastTickAt=Date.now(); S.lastTickEpoch=Number(d.tick.epoch||0);
  if(Number.isFinite(Number(d.tick.pip_size)))S.pipSize=Number(d.tick.pip_size);
  const dig=digitFromQuote(d.tick.quote,S.pipSize); if(dig==null)return;
  S.totalForwardTicks++;
  scoreForwardOutcome(dig,d.tick.epoch,d.tick.quote);
  S.liveTicks.push({digit:dig,parity:parity(dig),quote:Number(d.tick.quote),epoch:Number(d.tick.epoch),source:'LIVE_FORWARD'});
  if(S.liveTicks.length>CFG.featureBuffer)S.liveTicks.shift();
  const sig=currentSignal();
  S.pendingSignal=sig?{...sig,predictedAt:nowISO()}:null;
  if(S.runner && S.mode!=='SHADOW') maybeAutoExecute();
  save(); render();
}

function clearFeedTimers(){
  if(S.watchdogTimer){clearInterval(S.watchdogTimer);S.watchdogTimer=null;}
  if(S.pingTimer){clearInterval(S.pingTimer);S.pingTimer=null;}
}
function forcePublicReconnect(reason='Feed stale'){
  S.lastPublicError=reason; S.connected=false; S.staleReconnects++;
  const old=S.publicWs; S.publicWs=null;
  if(old){try{old.onclose=null;old.close();}catch(_){}}
  clearFeedTimers(); clearTimeout(S.reconnectTimer);
  S.reconnectTimer=setTimeout(connectPublic,500); render();
}
function startFeedTimers(ws){
  clearFeedTimers();
  S.pingTimer=setInterval(()=>{ if(S.publicWs===ws && ws.readyState===WebSocket.OPEN){try{ws.send(JSON.stringify({ping:1,req_id:95002}));}catch(_){}} },CFG.pingIntervalMs);
  S.watchdogTimer=setInterval(()=>{
    if(S.publicWs!==ws)return;
    const age=Date.now()-(S.lastTickAt||0);
    if(S.connected && S.lastTickAt && age>CFG.staleFeedMs) forcePublicReconnect(`No ${SYMBOL} tick for ${(age/1000).toFixed(1)}s — reconnecting`);
  },CFG.watchdogIntervalMs);
}

function connectPublic(){
  try{
    if(S.publicWs && [WebSocket.OPEN,WebSocket.CONNECTING].includes(S.publicWs.readyState))return;
    const ws=new WebSocket('wss://api.derivws.com/trading/v1/options/ws/public'); S.publicWs=ws; S.lastPublicError='';
    ws.onopen=()=>{
      S.connected=true;S.reconnectAttempts=0;S.feedConnectionsOpened++;S.lastPublicMessageAt=Date.now();S.lastTickAt=Date.now();S.lastPublicError='';
      ws.send(JSON.stringify({ticks:SYMBOL,subscribe:1,req_id:95003})); startFeedTimers(ws); loadHistory(); render();
    };
    ws.onmessage=e=>{S.lastPublicMessageAt=Date.now();let d;try{d=JSON.parse(e.data)}catch{return;}if(d.error){S.lastPublicError=d.error.message||d.error.code||'Deriv public feed error';render();return;}onPublic(d);};
    ws.onerror=()=>{S.lastPublicError='Public market WebSocket error';render();};
    ws.onclose=()=>{clearFeedTimers();S.connected=false;if(S.publicWs===ws)S.publicWs=null;if(!S.lastPublicError)S.lastPublicError='Public feed disconnected';render();const delay=Math.min(30000,1500*Math.pow(1.7,S.reconnectAttempts++));clearTimeout(S.reconnectTimer);S.reconnectTimer=setTimeout(connectPublic,delay);};
  }catch(e){S.connected=false;S.lastPublicError=String(e?.message||e||'Public feed connection failed');render();clearTimeout(S.reconnectTimer);S.reconnectTimer=setTimeout(connectPublic,3000);}
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
  if(S.tradeWs && S.tradeWs.readyState===WebSocket.OPEN)return S.tradeWs;
  const url=await getAuthenticatedWsUrl();
  return await new Promise((resolve,reject)=>{
    const ws=new WebSocket(url);S.tradeWs=ws; const timer=setTimeout(()=>reject(new Error('Trading socket timeout')),10000);
    ws.onopen=()=>{clearTimeout(timer);S.authenticated=true;ws.send(JSON.stringify({balance:1,subscribe:1,req_id:96001}));resolve(ws);render();};
    ws.onmessage=e=>{let d;try{d=JSON.parse(e.data)}catch{return;}onTradeMessage(d);};
    ws.onerror=()=>{};ws.onclose=()=>{S.authenticated=false;S.tradeWs=null;render();};
  });
}

function executionError(msg){
  S.executionRecords.push({kind:'EXECUTION_ERROR',at:nowISO(),mode:S.mode,message:String(msg)});
  S.executionRecords=S.executionRecords.slice(-2000);save();render();
}
function onTradeMessage(d){
  if(d.error){const msg=d.error.message||d.error.code||'Deriv error';S.pendingProposal=null;S.activeTrade=null;executionError(msg);return;}
  if(d.msg_type==='proposal' && S.pendingProposal && d.proposal?.id){
    const pp=S.pendingProposal;pp.ask=Number(d.proposal.ask_price);pp.payout=Number(d.proposal.payout);pp.proposalId=d.proposal.id;
    pp.proposalProfit=pp.payout-pp.ask;pp.breakEvenProbability=pp.payout>0?pp.ask/pp.payout:null;
    if(pp.source==='AUTO'){
      if(pp.predictedProbability==null || pp.breakEvenProbability==null || pp.predictedProbability < pp.breakEvenProbability + CFG.minSignalEdgeOverProposalBE){
        S.executionRecords.push({kind:'AUTO_SKIP',at:nowISO(),mode:S.mode,side:pp.side,predictedProbability:pp.predictedProbability,proposalBreakEven:pp.breakEvenProbability,reason:'Predicted edge did not clear live proposal break-even + safety margin'});
        S.pendingProposal=null;save();render();return;
      }
    }
    S.tradeWs.send(JSON.stringify({buy:d.proposal.id,price:pp.ask,req_id:96003}));return;
  }
  if(d.msg_type==='buy' && d.buy?.contract_id && S.pendingProposal){
    const pp=S.pendingProposal;S.pendingProposal=null;
    S.activeTrade={...pp,contractId:Number(d.buy.contract_id),boughtAt:nowISO(),buyPrice:Number(d.buy.buy_price||pp.ask)};
    S.tradeWs.send(JSON.stringify({proposal_open_contract:1,contract_id:S.activeTrade.contractId,subscribe:1,req_id:96004}));render();return;
  }
  if(d.msg_type==='proposal_open_contract' && S.activeTrade){
    const c=d.proposal_open_contract;if(Number(c.contract_id)!==Number(S.activeTrade.contractId))return;
    if(c.is_sold){
      const t=S.activeTrade;S.activeTrade=null;const profit=Number(c.profit||0),win=profit>0;
      S.stats.contracts++;if(win)S.stats.wins++;else S.stats.losses++;S.stats.pnl+=profit;
      S.executionRecords.push({kind:'EXECUTION',mode:S.mode,source:t.source,side:t.side,requestedAt:t.requestedAt,boughtAt:t.boughtAt,settledAt:nowISO(),stake:t.ask??S.stake,payout:t.payout,proposalProfit:t.proposalProfit,breakEvenProbability:t.breakEvenProbability,predictedProbability:t.predictedProbability??null,candidateKey:t.candidateKey??null,contractId:t.contractId,result:win?'WIN':'LOSS',profit,exitTick:c.exit_tick??null});
      S.executionRecords=S.executionRecords.slice(-2000);save();render();
    }
  }
}

async function requestTrade(side,source='MANUAL',sig=null){
  side=String(side||'').toUpperCase();if(!['ODD','EVEN'].includes(side))return;
  if(!(await ensureAdminAuthorized(true)))return;
  if(S.mode==='SHADOW'){executionError('Select DEMO or REAL before executing a trade.');return;}
  if(S.activeTrade||S.pendingProposal){executionError('A contract or proposal is already active.');return;}
  if(!S.connected||!S.historicalLoaded){executionError('Market feed/history is not ready.');return;}
  if(Date.now()-S.lastTradeAt<CFG.cooldownMs)return;
  S.lastTradeAt=Date.now();
  try{
    const ws=await ensureTradeWs();
    const predictedProbability=sig?.probability??null;
    S.pendingProposal={side,source,requestedAt:nowISO(),predictedProbability,candidateKey:sig?.candidate?.key||null,candidateLabel:sig?.candidate?.label||null};
    ws.send(JSON.stringify({proposal:1,amount:S.stake,basis:'stake',contract_type:side==='ODD'?'DIGITODD':'DIGITEVEN',currency:'USD',duration:1,duration_unit:'t',underlying_symbol:SYMBOL,req_id:96002}));
    render();
  }catch(e){S.pendingProposal=null;executionError(e?.message||String(e));}
}

async function maybeAutoExecute(){
  if(!S.runner || S.mode==='SHADOW' || S.activeTrade || S.pendingProposal)return;
  const sig=currentSignal();if(!sig?.side)return;
  if(S.autoSide==='ODD' && sig.side!=='ODD')return;
  if(S.autoSide==='EVEN' && sig.side!=='EVEN')return;
  if(sig.status!=='AUTO_READY')return;
  await requestTrade(sig.side,'AUTO',sig);
}

async function setMode(mode){
  if(!['SHADOW','DEMO','REAL'].includes(mode))return;
  if(!(await ensureAdminAuthorized(true)))return;
  if(S.activeTrade||S.pendingProposal)return;
  S.mode=mode;S.runner=false;
  if(S.tradeWs){try{S.tradeWs.close();}catch(_){}S.tradeWs=null;S.authenticated=false;}
  save();render();
}
function setAutoSide(side){if(['AUTO','ODD','EVEN'].includes(side)){S.autoSide=side;save();render();}}
async function toggleRunner(){
  if(!(await ensureAdminAuthorized(true)))return;
  if(S.mode==='SHADOW'){S.runner=!S.runner;save();render();return;}
  if(!S.runner){
    try{await ensureTradeWs();S.runner=true;save();render();maybeAutoExecute();}catch(e){executionError(e?.message||String(e));}
  }else{S.runner=false;save();render();}
}

async function requestWakeLock(){
  S.wakeLockRequested=true;save();
  if(!('wakeLock' in navigator)){render();return false;}
  try{S.wakeLock=await navigator.wakeLock.request('screen');S.wakeLock.addEventListener('release',()=>{S.wakeLock=null;render();});render();return true;}catch(_){S.wakeLock=null;render();return false;}
}
async function releaseWakeLock(){S.wakeLockRequested=false;save();if(S.wakeLock){try{await S.wakeLock.release();}catch(_){}S.wakeLock=null;}render();}
async function toggleWakeLock(){if(S.wakeLockRequested)await releaseWakeLock();else await requestWakeLock();}

function rankedCandidates(){
  return S.candidates.map(c=>({...c,forward:candidateForwardStats(c)})).sort((a,b)=>{
    const ar=a.forward.n>=CFG.minForwardNForAuto?1:0,br=b.forward.n>=CFG.minForwardNForAuto?1:0;if(ar!==br)return br-ar;
    const al=a.forward.lower95??0,bl=b.forward.lower95??0;if(al!==bl)return bl-al;
    return (b.forward.winRate??0)-(a.forward.winRate??0);
  });
}
function snapshot(){
  const sig=currentSignal();
  return {
    schema:'DIGITMATCHSTAR_ODDEVEN_LAB_V1',generatedAt:nowISO(),version:VERSION,symbol:SYMBOL,currentMode:S.mode,runner:S.runner,autoSide:S.autoSide,stake:S.stake,
    economics:{assumedWinProfitPerDollar:CFG.assumedWinProfitPerDollar,assumedBreakEvenWinRate:CFG.assumedBreakEvenWinRate,liveProposalEconomicsUsedForExecution:true},
    methodology:{historicalUsage:'DISCOVERY_ONLY',candidateDefinitionsFrozenFromHistorical:true,candidatesFrozenAt:S.candidatesFrozenAt,liveRecords:'FORWARD_ONLY',predictionFrozenBeforeOutcome:true,realNeverAutoResumes:true,oneActiveContractMax:true},
    collection:{totalForwardTicks:S.totalForwardTicks,retainedFeatureTicks:S.liveTicks.length,featureBufferLimit:CFG.featureBuffer,forwardRecordCount:S.forwardRecords.length,wakeLockRequested:S.wakeLockRequested,wakeLockActive:!!S.wakeLock},
    feedHealth:{connected:S.connected,lastTickAt:S.lastTickAt,lastTickEpoch:S.lastTickEpoch,connectionsOpened:S.feedConnectionsOpened,staleReconnects:S.staleReconnects,lastError:S.lastPublicError||''},
    executionStats:S.stats,currentSignal:sig,candidates:rankedCandidates(),forwardRecords:S.forwardRecords,executionRecords:S.executionRecords
  };
}
function exportJSON(){
  if(!S.adminAuthorized)return;
  const blob=new Blob([JSON.stringify(snapshot(),null,2)],{type:'application/json'}),a=document.createElement('a');
  a.href=URL.createObjectURL(blob);a.download=`odd-even-lab-${SYMBOL}-${new Date().toISOString().replaceAll(':','-')}.json`;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),1000);
}

function makePanel(){
  if($(PANEL_ID))return;
  const el=document.createElement('section');el.id=PANEL_ID;
  el.innerHTML=`<div class="oe-head" id="oe-drag"><div><div class="oe-kicker">PRIVATE RESEARCH + EXECUTION</div><div class="oe-title">ODD / EVEN LAB</div><div class="oe-ver">${VERSION}</div></div><div class="oe-head-actions"><button id="oe-min" title="Minimize">−</button><button id="oe-close" title="Hide">×</button></div></div><div id="oe-body" class="oe-body"></div>`;
  document.body.appendChild(el);
  const css=document.createElement('style');css.id='oe-style';css.textContent=`
    #${PANEL_ID}{position:fixed;right:18px;top:92px;width:390px;max-width:calc(100vw - 20px);z-index:2147483000;background:linear-gradient(180deg,#07182f 0%,#0b1f3b 48%,#091629 100%);border:1px solid rgba(125,211,252,.28);border-radius:18px;box-shadow:0 24px 80px rgba(0,0,0,.48),0 0 0 1px rgba(255,255,255,.03) inset;color:#eaf5ff;font:12px/1.35 Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;overflow:hidden;backdrop-filter:blur(16px)}
    #${PANEL_ID} *{box-sizing:border-box} #${PANEL_ID}.oe-mini{width:260px} #${PANEL_ID}.oe-mini .oe-body{display:none}
    #${PANEL_ID} .oe-head{display:flex;align-items:center;justify-content:space-between;padding:13px 14px 12px;cursor:move;background:linear-gradient(135deg,rgba(56,189,248,.14),rgba(99,102,241,.10));border-bottom:1px solid rgba(255,255,255,.08);user-select:none}
    #${PANEL_ID} .oe-kicker{font-size:9px;letter-spacing:.18em;color:#7dd3fc;font-weight:900} #${PANEL_ID} .oe-title{font-size:17px;font-weight:950;letter-spacing:.03em;margin-top:1px} #${PANEL_ID} .oe-ver{font-size:9px;color:#93a9c2;margin-top:1px}
    #${PANEL_ID} .oe-head-actions{display:flex;gap:7px} #${PANEL_ID} .oe-head-actions button{width:30px;height:30px;border-radius:10px;border:1px solid rgba(255,255,255,.12);background:#0d2949;color:#dff4ff;font-size:18px;font-weight:900;cursor:pointer}
    #${PANEL_ID} .oe-body{max-height:min(76vh,760px);overflow:auto;padding:12px} #${PANEL_ID} .oe-body::-webkit-scrollbar{width:8px} #${PANEL_ID} .oe-body::-webkit-scrollbar-thumb{background:#214768;border-radius:99px}
    #${PANEL_ID} .chips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px} #${PANEL_ID} .chip{padding:5px 8px;border-radius:999px;border:1px solid rgba(255,255,255,.09);font-weight:800;font-size:10px;background:#102744;color:#b8cee3} #${PANEL_ID} .chip.on{background:#0b3a2a;color:#bbf7d0;border-color:rgba(34,197,94,.42)} #${PANEL_ID} .chip.warn{background:#3b2b0e;color:#fde68a;border-color:rgba(245,158,11,.38)} #${PANEL_ID} .chip.bad{background:#40151c;color:#fecaca;border-color:rgba(248,113,113,.38)}
    #${PANEL_ID} .hero{display:grid;grid-template-columns:1fr auto;gap:8px;align-items:center;padding:11px 12px;background:linear-gradient(135deg,rgba(14,165,233,.12),rgba(79,70,229,.10));border:1px solid rgba(125,211,252,.16);border-radius:14px;margin-bottom:10px} #${PANEL_ID} .hero b{font-size:15px} #${PANEL_ID} .muted{color:#8fa8c0}
    #${PANEL_ID} .modes,#${PANEL_ID} .sides{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-bottom:9px} #${PANEL_ID} button.oe-btn{border:1px solid rgba(255,255,255,.12);background:#0e2948;color:#d7eafa;padding:9px 8px;border-radius:11px;font-weight:900;cursor:pointer} #${PANEL_ID} button.oe-btn:hover{filter:brightness(1.12)} #${PANEL_ID} button.oe-btn.active{outline:2px solid rgba(56,189,248,.35);background:#123c62} #${PANEL_ID} button.demo.active{background:#153e2d;color:#bbf7d0} #${PANEL_ID} button.real.active{background:#54231f;color:#fecaca}
    #${PANEL_ID} .wake{width:100%;margin-bottom:9px;background:#102a46;color:#dbeafe;border:1px solid rgba(255,255,255,.11);border-radius:11px;padding:8px;font-weight:850;cursor:pointer} #${PANEL_ID} .wake.on{background:#123b2a;color:#bbf7d0;border-color:rgba(34,197,94,.45)}
    #${PANEL_ID} .panel{background:rgba(8,24,43,.78);border:1px solid rgba(255,255,255,.08);border-radius:14px;padding:10px;margin-bottom:10px} #${PANEL_ID} .panel-title{font-size:10px;color:#89a7c4;text-transform:uppercase;letter-spacing:.12em;font-weight:900;margin-bottom:7px}
    #${PANEL_ID} .signal{display:grid;grid-template-columns:1fr 1fr;gap:8px} #${PANEL_ID} .metric{background:#0d2845;border:1px solid rgba(255,255,255,.07);border-radius:12px;padding:9px} #${PANEL_ID} .metric span{display:block;color:#8fa8c0;font-size:9px;text-transform:uppercase;letter-spacing:.08em} #${PANEL_ID} .metric b{display:block;font-size:16px;margin-top:2px} #${PANEL_ID} .good{color:#86efac} #${PANEL_ID} .bad{color:#fca5a5} #${PANEL_ID} .accent{color:#7dd3fc} #${PANEL_ID} .amber{color:#fde68a}
    #${PANEL_ID} .stake-row{display:grid;grid-template-columns:1fr 108px;gap:8px;align-items:end} #${PANEL_ID} input{width:100%;border:1px solid rgba(255,255,255,.14);border-radius:10px;background:#081b31;color:#fff;padding:9px 10px;font-weight:800;outline:none} #${PANEL_ID} label{display:block;color:#93abc2;font-size:9px;font-weight:850;letter-spacing:.08em;text-transform:uppercase;margin-bottom:4px}
    #${PANEL_ID} .runner{width:100%;border:0;border-radius:12px;padding:11px 10px;font-weight:950;cursor:pointer;background:linear-gradient(135deg,#0284c7,#4f46e5);color:white;margin-bottom:9px;box-shadow:0 10px 28px rgba(2,132,199,.18)} #${PANEL_ID} .runner.stop{background:linear-gradient(135deg,#9f1239,#b91c1c)}
    #${PANEL_ID} .trade-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px} #${PANEL_ID} .trade-now{padding:12px;border-radius:13px;border:1px solid rgba(255,255,255,.12);font-weight:950;cursor:pointer;color:#fff} #${PANEL_ID} .odd{background:linear-gradient(135deg,#7c3aed,#4f46e5)} #${PANEL_ID} .even{background:linear-gradient(135deg,#0891b2,#0e7490)} #${PANEL_ID} .trade-now:disabled{opacity:.45;cursor:not-allowed}
    #${PANEL_ID} .cand{display:grid;grid-template-columns:1fr auto;gap:8px;padding:8px 0;border-bottom:1px solid rgba(255,255,255,.06)} #${PANEL_ID} .cand:last-child{border-bottom:0} #${PANEL_ID} .cand-name{font-weight:850;color:#dceeff} #${PANEL_ID} .tag{display:inline-block;margin-top:3px;padding:2px 6px;border-radius:999px;background:#173451;color:#9fc2de;font-size:9px;font-weight:800} #${PANEL_ID} .tag.ready{background:#123c2a;color:#bbf7d0} #${PANEL_ID} .tag.no{background:#3c1c25;color:#fecaca}
    #${PANEL_ID} .footer-actions{display:grid;grid-template-columns:1fr 1fr;gap:8px} #${PANEL_ID} .footer-actions button{padding:9px;border-radius:11px;border:1px solid rgba(255,255,255,.1);background:#0d2845;color:#dceeff;font-weight:900;cursor:pointer}
    @media(max-width:520px){#${PANEL_ID}{right:8px;top:70px;width:calc(100vw - 16px)}}
  `;document.head.appendChild(css);

  const min=$('oe-min'), close=$('oe-close');
  min.onclick=()=>{S.minimized=!S.minimized;el.classList.toggle('oe-mini',S.minimized);min.textContent=S.minimized?'+':'−';save();};
  close.onclick=()=>{el.style.display='none';};
  if(S.minimized){el.classList.add('oe-mini');min.textContent='+';}
  if(S.panelPos){el.style.left=`${S.panelPos.left}px`;el.style.top=`${S.panelPos.top}px`;el.style.right='auto';}
  makeDraggable(el,$('oe-drag'));
}

function makeDraggable(panel,handle){
  let drag=null;
  handle.addEventListener('pointerdown',e=>{
    if(e.target.closest('button'))return;
    const r=panel.getBoundingClientRect();drag={dx:e.clientX-r.left,dy:e.clientY-r.top};handle.setPointerCapture(e.pointerId);e.preventDefault();
  });
  handle.addEventListener('pointermove',e=>{
    if(!drag)return;const maxL=Math.max(0,window.innerWidth-panel.offsetWidth),maxT=Math.max(0,window.innerHeight-50);const left=clamp(e.clientX-drag.dx,0,maxL),top=clamp(e.clientY-drag.dy,0,maxT);panel.style.left=`${left}px`;panel.style.top=`${top}px`;panel.style.right='auto';S.panelPos={left,top};
  });
  const end=()=>{if(drag){drag=null;save();}};handle.addEventListener('pointerup',end);handle.addEventListener('pointercancel',end);
}

function chip(kind,text){return `<span class="chip ${kind}">${text}</span>`;}
function render(){
  const panel=$(PANEL_ID), body=$('oe-body');if(!panel||!body)return;
  const sig=currentSignal(), cand=rankedCandidates();
  const feedKind=S.connected?'on':'bad',histKind=S.historicalLoaded?'on':'warn',runnerKind=S.runner?'on':'warn',authKind=(S.mode==='SHADOW'||S.authenticated)?'on':'warn';
  const currentCandidate=sig?.candidate,fs=currentCandidate?candidateForwardStats(currentCandidate):null;
  const autoReady=sig?.status==='AUTO_READY';
  const runLabel=S.runner?`STOP ${S.mode} AUTO`:`START ${S.mode} AUTO`;
  const disabledTrade=(S.mode==='SHADOW'||!!S.activeTrade||!!S.pendingProposal)?'disabled':'';
  const topRows=cand.slice(0,8).map(c=>{
    const s=c.forward,ready=s.n>=CFG.minForwardNForAuto&&s.winRate>=CFG.autoMinObservedWinRate&&s.lower95>=CFG.autoMinWilsonLower95;
    return `<div class="cand"><div><div class="cand-name">${c.side} · ${c.label}</div><span class="tag ${ready?'ready':s.n>=CFG.minForwardNForAuto?'no':''}">${ready?'AUTO READY':s.n>=CFG.minForwardNForAuto?'NOT PROVEN':`FORWARD n=${s.n}`}</span></div><div style="text-align:right"><b class="${s.winRate!=null&&s.winRate>=CFG.assumedBreakEvenWinRate?'good':'bad'}">${pct(s.winRate)}</b><div class="muted" style="font-size:10px">95% low ${pct(s.lower95)}</div></div></div>`;
  }).join('');
  const busy=S.activeTrade?`Contract #${S.activeTrade.contractId} active`:S.pendingProposal?'Waiting for proposal / buy':'Ready';

  body.innerHTML=`
    <div class="chips">${chip(feedKind,`Feed ${S.connected?'ONLINE':'OFFLINE'}`)}${chip(histKind,`History ${S.historicalLoaded?'READY':'LOADING'}`)}${chip(runnerKind,`Auto ${S.runner?'ON':'OFF'}`)}${chip(authKind,`${S.mode} ${S.mode==='SHADOW'?'NO TRADE':S.authenticated?'AUTH OK':'AUTH NEEDED'}`)}</div>
    <div class="hero"><div><div class="muted">FORWARD COLLECTOR</div><b>${S.totalForwardTicks.toLocaleString()} ticks</b></div><div style="text-align:right"><div class="muted">Rolling buffer</div><b>${S.liveTicks.length.toLocaleString()}/${CFG.featureBuffer}</b></div></div>
    <div class="modes"><button id="oe-shadow" class="oe-btn ${S.mode==='SHADOW'?'active':''}">SHADOW</button><button id="oe-demo" class="oe-btn demo ${S.mode==='DEMO'?'active':''}">DEMO</button><button id="oe-real" class="oe-btn real ${S.mode==='REAL'?'active':''}">REAL</button></div>
    <button id="oe-wake" class="wake ${S.wakeLockRequested?'on':''}">${S.wakeLockRequested?(S.wakeLock?'KEEP AWAKE: ON':'KEEP AWAKE: REQUESTED'):'KEEP SCREEN AWAKE: OFF'}</button>
    <div class="panel"><div class="panel-title">Trade setup</div><div class="stake-row"><div><label>Stake per trade (USD)</label><input id="oe-stake" type="number" min="0.35" step="0.01" value="${S.stake.toFixed(2)}"></div><div><label>Live state</label><div style="font-weight:900;padding:9px 0">${busy}</div></div></div></div>
    <div class="panel"><div class="panel-title">Current frozen signal</div><div class="signal"><div class="metric"><span>Suggested side</span><b class="accent">${sig?.side||'—'}</b></div><div class="metric"><span>Forward win rate</span><b class="${fs?.winRate!=null&&fs.winRate>=CFG.assumedBreakEvenWinRate?'good':'amber'}">${pct(fs?.winRate)}</b></div><div class="metric"><span>Forward support</span><b>${fs?.n??0}</b></div><div class="metric"><span>95% lower bound</span><b class="${fs?.lower95!=null&&fs.lower95>=CFG.assumedBreakEvenWinRate?'good':'amber'}">${pct(fs?.lower95)}</b></div></div><div class="muted" style="margin-top:8px">${currentCandidate?currentCandidate.label:'No frozen candidate matches the current state.'}<br>Break-even ≈ ${pct(CFG.assumedBreakEvenWinRate)}. AUTO requires n≥${CFG.minForwardNForAuto}, observed ≥${pct(CFG.autoMinObservedWinRate)}, and 95% lower bound above break-even.</div></div>
    <div class="panel"><div class="panel-title">Auto side filter</div><div class="sides"><button id="oe-auto" class="oe-btn ${S.autoSide==='AUTO'?'active':''}">BEST SIGNAL</button><button id="oe-auto-odd" class="oe-btn ${S.autoSide==='ODD'?'active':''}">ODD ONLY</button><button id="oe-auto-even" class="oe-btn ${S.autoSide==='EVEN'?'active':''}">EVEN ONLY</button></div><button id="oe-run" class="runner ${S.runner?'stop':''}">${runLabel}</button><div class="muted">AUTO uses only frozen historical candidate definitions and requires forward evidence. It also checks the actual Deriv proposal break-even before buying.</div></div>
    <div class="panel"><div class="panel-title">Manual one-tick trade</div><div class="trade-grid"><button id="oe-trade-odd" class="trade-now odd" ${disabledTrade}>TRADE ODD NOW</button><button id="oe-trade-even" class="trade-now even" ${disabledTrade}>TRADE EVEN NOW</button></div><div class="muted" style="margin-top:8px">Manual buttons execute one contract at your current stake in DEMO or REAL. One active contract maximum. No per-trade confirmation after you select REAL.</div></div>
    <div class="panel"><div class="panel-title">Execution</div><div class="signal"><div class="metric"><span>Contracts</span><b>${S.stats.contracts}</b></div><div class="metric"><span>Wins / losses</span><b>${S.stats.wins} / ${S.stats.losses}</b></div><div class="metric"><span>P&L</span><b class="${S.stats.pnl>0?'good':S.stats.pnl<0?'bad':''}">${money(S.stats.pnl)}</b></div><div class="metric"><span>Signal status</span><b class="${autoReady?'good':'amber'}">${sig?.status||'WARMING'}</b></div></div></div>
    ${S.lastPublicError?`<div class="panel" style="border-color:rgba(248,113,113,.45)"><b class="bad">Feed issue:</b> ${S.lastPublicError}</div>`:''}
    <div class="panel"><div class="panel-title">Ranked frozen candidates</div>${topRows||'<div class="muted">Candidates appear after historical discovery loads.</div>'}</div>
    <div class="panel"><div class="panel-title">Research rule</div><div class="muted">Historical 5,000 ticks discover candidate states once. Future ticks score those frozen states. ODD/EVEN assumed economics are +$0.95 per $1 win and -$1 per loss only for research display; actual DEMO/REAL execution uses the live Deriv proposal economics.</div></div>
    <div class="footer-actions"><button id="oe-export">EXPORT JSON</button><button id="oe-reset-exec">RESET EXEC STATS</button></div>`;

  $('oe-shadow').onclick=()=>setMode('SHADOW');$('oe-demo').onclick=()=>setMode('DEMO');$('oe-real').onclick=()=>setMode('REAL');
  $('oe-wake').onclick=toggleWakeLock;$('oe-auto').onclick=()=>setAutoSide('AUTO');$('oe-auto-odd').onclick=()=>setAutoSide('ODD');$('oe-auto-even').onclick=()=>setAutoSide('EVEN');$('oe-run').onclick=toggleRunner;
  $('oe-trade-odd').onclick=()=>requestTrade('ODD','MANUAL',currentSignal());$('oe-trade-even').onclick=()=>requestTrade('EVEN','MANUAL',currentSignal());
  $('oe-stake').onchange=e=>{const v=Number(e.target.value);if(Number.isFinite(v)&&v>=.35){S.stake=clamp(v,.35,1000);save();render();}else render();};
  $('oe-export').onclick=exportJSON;$('oe-reset-exec').onclick=()=>{S.stats={contracts:0,wins:0,losses:0,pnl:0};S.executionRecords=[];save();render();};
}

window.DMSOddEvenLab={
  version:VERSION,
  getSnapshot:()=>S.adminAuthorized?snapshot():null,
  exportReport:()=>{if(S.adminAuthorized)exportJSON();},
  setMode,
  setAutoSide,
  startAuto:async()=>{if(!S.runner)await toggleRunner();},
  stopAuto:()=>{S.runner=false;save();render();},
  tradeOdd:()=>requestTrade('ODD','MANUAL',currentSignal()),
  tradeEven:()=>requestTrade('EVEN','MANUAL',currentSignal()),
  requestWakeLock,releaseWakeLock
};

async function boot(){
  load();const ok=await ensureAdminAuthorized(true);if(!ok)return;
  makePanel();render();connectPublic();
  if(S.wakeLockRequested&&!document.hidden)requestWakeLock();
  setInterval(async()=>{const ok=await ensureAdminAuthorized(true);if(!ok)hidePrivateLab();},60000);
}
window.addEventListener('focus',()=>{if(S.adminAuthorized&&(!S.connected||(S.lastTickAt&&Date.now()-S.lastTickAt>CFG.staleFeedMs)))forcePublicReconnect('Window resumed — refreshing feed');});
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&S.wakeLockRequested&&!S.wakeLock)requestWakeLock();if(!document.hidden&&S.adminAuthorized&&(!S.connected||(S.lastTickAt&&Date.now()-S.lastTickAt>CFG.staleFeedMs)))forcePublicReconnect('Tab resumed — refreshing feed');});
boot();
})();
