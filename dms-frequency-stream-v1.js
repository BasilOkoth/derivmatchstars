/* DigitMatchStar Frequency + V1 Shadow Study v1
   Public Deriv market-data connection, independent of account or trade controls.
   No trading endpoints or authorization tokens are used.
*/
(() => {
  'use strict';
  if (window.DMSFrequencyStudy) return;
  const appId = String(window.DMS_RESEARCH_APP_ID || '1089');
  const MAX = 1000, BACKOFF = 12000;
  const S = {symbol:'R_10', socket:null, subscription:null, prices:[], seen:new Set(),
    last:null, seq:0, pending:null, block:null, rows:[], forecasts:[], rejected:0,
    connected:false, ready:false, generation:0, timer:null, html:null, status:'connecting',
    snapshotMatched:0, snapshotUnavailable:0, gapCount:0, liveTicks:0, lastLiveAt:0, reconnects:0};
  const digit = v => Number.isInteger(+v) && +v>=0 && +v<=9 ? +v : null;
  const symbol = () => String(document.querySelector('#symbol')?.value || 'R_10');
  function key(t){return `${S.symbol}|${t.epoch}|${t.quote}|${t.digit}`;}
  function ensurePanel(){
    if(S.html?.isConnected)return;
    const host=document.createElement('section');host.id='dms-frequency-study';
    host.style='font:13px system-ui;width:100%;margin:14px 0 0;padding:12px;border:1px solid #475569;border-radius:12px;background:#0f172a;color:#f9fafb;box-sizing:border-box;overflow-wrap:anywhere;';
    host.innerHTML='<div style="display:flex;justify-content:space-between;gap:8px;align-items:center"><b>Market stream & frequency research</b><span id="dms-fs-status">CONNECTING</span></div><p style="margin:8px 0;color:#cbd5e1">Independent research feed · read-only · no purchases. Status reports connection/API errors.</p><div id="dms-fs-values">No ticks yet</div><div id="dms-fs-metrics" style="margin-top:8px;color:#cbd5e1"></div><button type="button" id="dms-fs-export" style="padding:8px 12px;margin-top:10px;background:#2563eb;border-radius:8px;color:white">Export shadow CSV</button>';
    const market=document.getElementById('market_status');
    const container=market?.closest('.bg-gray-900.border') || document.querySelector('.lg\\:col-span-1');
    if(container) container.appendChild(host); else document.body.prepend(host);host.querySelector('#dms-fs-export').addEventListener('click',exportCsv);S.html=host;
  }
  function render(){
    ensurePanel();
    const stats=Array.from({length:10},(_,d)=>S.prices.filter(x=>x.digit===d).length);
    const n=S.prices.length;
    if(S.connected&&S.lastLiveAt&&Date.now()-S.lastLiveAt>10000)S.status='stale: no new ticks';
    S.html.querySelector('#dms-fs-status').textContent=`${S.status.toUpperCase()} · ${S.symbol}`;
    S.html.querySelector('#dms-fs-values').textContent=stats.map((c,d)=>`${d}: ${n?(100*c/n).toFixed(1):'—'}%`).join('  |  ');
    S.html.querySelector('#dms-fs-metrics').textContent=`Ticks in window: ${n}/1000 · new live ticks: ${S.liveTicks} · duplicate drops: ${S.rejected} · blocks tested: ${S.forecasts.length} · aligned V1 snapshots: ${S.snapshotMatched} · unavailable V1: ${S.snapshotUnavailable} · observed gaps: ${S.gapCount} · reconnects: ${S.reconnects}`;
  }
  function parseTick(obj){
    if(!obj||obj.epoch==null||obj.quote==null)return null;
    // Preserve trailing zeros when pip_size is known; a numeric quote alone is ambiguous.
    const p=obj.pip_size!==undefined&&obj.pip_size!==null&&Number.isInteger(+obj.pip_size)&&+obj.pip_size>=0&&+obj.pip_size<=12?+obj.pip_size:(S.symbol==='R_10'?3:null);
    const str=p!==null?Number(obj.quote).toFixed(p):String(obj.quote);
    const last=str.match(/\.(\d+)$/);if(!last)return null;
    return {epoch:Number(obj.epoch),quote:str,digit:Number(last[1].slice(-1)),pip_size:p};
  }
  function captureV1(t){
    const ds=window.SERVER_EXECUTION?.state?.digit_score;
    const ct=ds?.canonical_tick;
    // Never treat a ranking from another WebSocket/tick as a synchronized forecast.
    const rank=ds?.ranking?.[0], epoch=Number(ds?.rank_epoch||0);
    if(!ct||epoch!==t.epoch||String(ct.formatted_quote ?? ct.quote ?? '')!==t.quote || !rank) {
      S.snapshotUnavailable++;return null;
    }
    const d=digit(rank.digit);if(d===null){S.snapshotUnavailable++;return null;}
    S.snapshotMatched++;return d;
  }
  function updateShadow(t){
    S.seq++;
    // Evaluate pending forecasts strictly against next received canonical tick.
    if(S.pending){
      const p=S.pending;
      if(S.seq===p.validForSeq) S.rows.push({...p,actualDigit:t.digit,hit:p.target===t.digit,observedTickKey:key(t)});
      S.pending=null;
    }
    if(S.block){
      S.block.elapsed++;
      const hit=S.block.target===t.digit;
      S.forecasts.push({sourceSeq:S.block.sourceSeq,sourceTickKey:S.block.sourceTickKey,
        target:S.block.target,elapsed:S.block.elapsed,observedSeq:S.seq,actualDigit:t.digit,hit});
      if(hit||S.block.elapsed===3)S.block=null;
    }
    const v1=captureV1(t);
    S.prices.push(t);if(S.prices.length>MAX)S.prices.shift();
    // Frequency selection is historical: t enters window BEFORE a forecast for t+1.
    if(S.prices.length>=100){
      const counts=Array(10).fill(0);for(const v of S.prices)counts[v.digit]++;
      const leader=counts.reduce((best,c,d)=>c>counts[best]?d:best,0);
      const currentKey=key(t);
      S.pending={sourceSeq:S.seq,validForSeq:S.seq+1,sourceTickKey:currentKey,target:leader,method:'FREQ1000',sampleSize:S.prices.length,v1Target:v1};
      if(!S.block)S.block={sourceSeq:S.seq,sourceTickKey:currentKey,target:v1===null?leader:v1,
         selection:v1===null?'FREQUENCY_FALLBACK_NO_ALIGNED_V1':'V1_ALIGNED',elapsed:0};
    }
    render();
  }
  function receiveTick(raw,history=false){
    const t=parseTick(raw);if(!t)return;
    const k=key(t);if(S.seen.has(k)){S.rejected++;return;}
    if(!history && S.last && t.epoch < S.last.epoch)return;
    if(!history && S.last && t.epoch-S.last.epoch>3)S.gapCount++;
    S.seen.add(k);if(S.seen.size>3000){S.seen=new Set(Array.from(S.seen).slice(-1500));}
    if(history){S.prices.push(t);if(S.prices.length>MAX)S.prices.shift();}
    else { S.liveTicks++; S.lastLiveAt=Date.now(); updateShadow(t); }
    S.last=t;
  }
  // Public data only. The account-specific trading WebSocket is never touched.
  // Current Deriv public endpoint first; documented legacy endpoint as fallback.
  const ENDPOINTS=[
    'wss://api.derivws.com/trading/v1/options/ws/public',
    `wss://ws.derivws.com/websockets/v3?app_id=${encodeURIComponent(appId)}`
  ];
  let retryTimer=null, startupTimer=null, endpointIndex=0;
  function connect(){
    const gen=++S.generation;
    const chosen=symbol();
    const changed=chosen!==S.symbol;
    S.symbol=chosen;
    S.connected=false;S.ready=false;
    S.status=`connecting ${endpointIndex===0?'public':'legacy'}`;
    clearTimeout(retryTimer);clearTimeout(startupTimer);
    if(S.socket){try{S.socket.close(1000,'research reconnect')}catch(_){}}
    if(changed){S.prices=[];S.seen.clear();S.last=null;S.seq=0;S.pending=null;S.block=null;S.liveTicks=0;S.lastLiveAt=0;}
    const ws=new WebSocket(ENDPOINTS[endpointIndex]);S.socket=ws;
    let gotLive=false, gotHistory=false, gotOpen=false, failure='';
    const send=(payload)=>{if(ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify(payload));};
    function retry(reason){
      if(gen!==S.generation)return;
      clearTimeout(startupTimer);
      failure=reason||failure||'connection failed';
      S.connected=false; S.status=failure; S.reconnects++;render();
      // Swap endpoints on failures; use progressively longer retry to avoid storms.
      endpointIndex=(endpointIndex+1)%ENDPOINTS.length;
      try{if(ws.readyState===WebSocket.OPEN||ws.readyState===WebSocket.CONNECTING)ws.close()}catch(_){}
      clearTimeout(retryTimer);
      retryTimer=setTimeout(()=>{if(gen===S.generation)connect()},Math.min(30000,3000+S.reconnects*1500));
    }
    ws.addEventListener('open',()=>{
      if(gen!==S.generation)return;
      gotOpen=true;S.status=`subscribing ${endpointIndex===0?'public':'legacy'}`;render();
      // Live subscription must not depend on successful history response.
      send({ticks:S.symbol,subscribe:1,req_id:102});
      send({ticks_history:S.symbol,count:MAX,end:'latest',style:'ticks',req_id:101});
      startupTimer=setTimeout(()=>{if(gen===S.generation&&!gotLive)retry('NO LIVE TICKS (15s)')},15000);
    });
    ws.addEventListener('message',ev=>{
      if(gen!==S.generation)return;
      let m;try{m=JSON.parse(ev.data)}catch(_){return}
      if(m.error){
        const detail=String(m.error.code||m.error.message||'unknown');
        const origin=m.req_id===101?'history':m.req_id===102?'subscription':'request';
        // A history failure does not prevent a working live feed.
        if(m.req_id===101){S.status=`history unavailable: ${detail} · waiting for live`;render();return;}
        retry(`API ${origin} ERROR: ${detail}`);return;
      }
      if(m.msg_type==='history'&&m.history&&!gotHistory){
        gotHistory=true;
        const h=m.history, prices=h.prices||[],times=h.times||[];
        // Tick history schema specifies global pip_size (not per-tick pip_sizes).
        const pip=Number.isInteger(Number(m.pip_size))?Number(m.pip_size):null;
        for(let i=0;i<prices.length;i++){
          if(times[i]!=null)receiveTick({epoch:times[i],quote:prices[i],pip_size:pip},true);
        }
        render();
      } else if(m.msg_type==='tick'&&m.tick){
        gotLive=true;clearTimeout(startupTimer);S.ready=true;
        receiveTick(m.tick,false);S.status='STREAMING';S.connected=true;render();
      }
    });
    ws.addEventListener('close',e=>{
      if(gen!==S.generation)return;
      if(retryTimer)return; // retry was already arranged by an API error/timeout
      retry(`CLOSED ${e.code}${e.reason?': '+String(e.reason).slice(0,70):''}${!gotOpen?' (before open)':''}`);
    });
    ws.addEventListener('error',()=>{
      if(gen!==S.generation)return;
      S.status=`WEBSOCKET ERROR (${endpointIndex===0?'public':'legacy'})`;render();
      // 'close' normally follows and reports close code.
    });
    render();
  }
  function exportCsv(){
    const fields=['sourceSeq','validForSeq','sourceTickKey','target','method','sampleSize','v1Target','actualDigit','hit','observedTickKey'];
    const lines=[fields.join(','),...S.rows.map(r=>fields.map(k=>JSON.stringify(r[k]??'')).join(','))];
    const blob=new Blob([lines.join('\n')],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob);
    const a=document.createElement('a');a.href=url;a.download=`dms-frequency-shadow-${S.symbol}-${Date.now()}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  window.DMSFrequencyStudy={state:S,connect,exportCsv,disconnect(){++S.generation;clearTimeout(retryTimer);clearTimeout(startupTimer);S.socket?.close();S.status='stopped';render()}};
  function boot(){
    ensurePanel();
    connect();
    document.getElementById('symbol')?.addEventListener('change',connect);
    setInterval(()=>{
      if(!S.socket||S.socket.readyState===WebSocket.CLOSED) return;
      const age=Date.now()-(S.lastLiveAt||0);
      // Refresh stale research stream only; never act on trade execution socket.
      if(S.socket.readyState===WebSocket.OPEN && S.ready && age>20000){
        S.status='stale: reconnecting'; render(); endpointIndex=(endpointIndex+1)%ENDPOINTS.length; connect();
      }else render();
    },5000);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
