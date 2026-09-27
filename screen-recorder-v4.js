/*
 * DigitMatchStar Ultra Premium Live Capture v4
 * Records the actual bot screen and automatically uploads the clip
 * for ultra-premium 9:16 composition.
 */
(() => {
  'use strict';

  const state = {
    displayStream: null,
    recorder: null,
    chunks: [],
    activeCycle: null,
    lastBlob: null,
    lastUrl: null,
    patched: false,
    uploading: false
  };

  function supportedMime(){
    return [
      'video/webm;codecs=vp9',
      'video/webm;codecs=vp8',
      'video/webm'
    ].find(x => window.MediaRecorder?.isTypeSupported?.(x)) || '';
  }

  function getAccountId(){
    const mode=(localStorage.getItem('selectedAccountMode')||'DEMO').toUpperCase();
    return localStorage.getItem('active_account') ||
      localStorage.getItem('derivAccount') ||
      localStorage.getItem(mode==='REAL' ? 'derivRealAccount' : 'derivDemoAccount') || '';
  }

  function getToken(){
    if(typeof window.getStoredDerivToken === 'function'){
      try{ return window.getStoredDerivToken() || ''; }catch(_){}
    }
    return localStorage.getItem('deriv_token') ||
      localStorage.getItem('derivToken') ||
      localStorage.getItem('authToken') || '';
  }

  function ensurePanel(){
    if(document.getElementById('dms-ultra-live-capture')) return;
    const el=document.createElement('div');
    el.id='dms-ultra-live-capture';
    el.style.cssText=[
      'position:fixed','right:18px','bottom:18px','z-index:999999',
      'width:330px','padding:14px','border-radius:18px',
      'background:rgba(4,12,9,.97)','border:1px solid rgba(74,222,128,.42)',
      'box-shadow:0 18px 60px rgba(0,0,0,.55)','font-family:Inter,Arial,sans-serif',
      'color:#f7faf8'
    ].join(';');

    el.innerHTML=`
      <div style="display:flex;align-items:center;gap:8px;font-weight:900;color:#4ade80;font-size:14px">
        <span>🎥</span><span>ULTRA-PREMIUM LIVE CAPTURE</span>
      </div>
      <div id="dms-v4-status" style="font-size:12px;color:#9db1a6;margin:7px 0 10px">
        Off · enable once, then each cycle is captured automatically
      </div>
      <button id="dms-v4-enable" style="width:100%;padding:10px;border:0;border-radius:11px;background:#16a34a;color:#fff;font-weight:900;cursor:pointer">
        Enable live capture
      </button>
      <div id="dms-v4-rec" style="display:none;margin-top:8px;color:#86efac;font-size:12px;font-weight:800">● RECORDING ACTUAL BOT SCREEN</div>
      <div id="dms-v4-upload" style="display:none;margin-top:8px;color:#67e8f9;font-size:12px;font-weight:800">↑ BUILDING ULTRA-PREMIUM TIKTOK VIDEO…</div>
      <video id="dms-v4-preview" controls playsinline style="display:none;width:100%;margin-top:10px;border-radius:11px;background:#000"></video>
      <a id="dms-v4-download" style="display:none;margin-top:8px;padding:8px 10px;border-radius:9px;background:#1f2937;color:#fff;text-align:center;text-decoration:none;font-size:12px;font-weight:800">
        Download raw live clip
      </a>
      <div style="font-size:10px;line-height:1.4;color:#738078;margin-top:9px">
        Choose the DigitMatchStar tab when Chrome/Edge asks what to share. Keep only what you want publicly visible on that tab.
      </div>
    `;
    document.body.appendChild(el);
    document.getElementById('dms-v4-enable').addEventListener('click', enableCapture);
  }

  function setStatus(text, color='#9db1a6'){
    const el=document.getElementById('dms-v4-status');
    if(el){ el.textContent=text; el.style.color=color; }
  }

  async function enableCapture(){
    if(!navigator.mediaDevices?.getDisplayMedia){
      alert('Use a current Chrome or Edge browser for live tab recording.');
      return;
    }
    try{
      const stream=await navigator.mediaDevices.getDisplayMedia({
        video:{frameRate:{ideal:30,max:30}},
        audio:false,
        preferCurrentTab:true,
        selfBrowserSurface:'include',
        surfaceSwitching:'include'
      });
      state.displayStream=stream;
      stream.getVideoTracks()[0]?.addEventListener('ended',()=>{
        state.displayStream=null;
        setStatus('Capture permission ended · enable again', '#fca5a5');
      });
      setStatus('Ready · next cycle will be captured', '#86efac');
      document.getElementById('dms-v4-enable').textContent='Capture enabled ✓';
    }catch(err){
      console.warn(err);
      setStatus('Capture not enabled', '#fca5a5');
    }
  }

  function startSegment(cycle){
    if(!state.displayStream || state.recorder?.state === 'recording') return;
    const mime=supportedMime();
    const opts={videoBitsPerSecond:7_500_000};
    if(mime) opts.mimeType=mime;

    state.chunks=[];
    state.activeCycle=JSON.parse(JSON.stringify(cycle || {}));

    try{
      state.recorder=new MediaRecorder(state.displayStream, opts);
      state.recorder.ondataavailable = e => {
        if(e.data && e.data.size) state.chunks.push(e.data);
      };
      state.recorder.onstop = async () => {
        const blob=new Blob(state.chunks, {type: state.recorder?.mimeType || 'video/webm'});
        state.lastBlob=blob;
        if(state.lastUrl) URL.revokeObjectURL(state.lastUrl);
        state.lastUrl=URL.createObjectURL(blob);

        const v=document.getElementById('dms-v4-preview');
        const a=document.getElementById('dms-v4-download');
        const rec=document.getElementById('dms-v4-rec');
        if(v){ v.src=state.lastUrl; v.style.display='block'; }
        if(a){
          a.href=state.lastUrl;
          a.download=`digitmatchstar-live-${String(state.activeCycle?.id||Date.now()).replace(/[^a-z0-9_-]/gi,'-')}.webm`;
          a.style.display='block';
        }
        if(rec) rec.style.display='none';
        setStatus(`Raw live clip ready · ${(blob.size/1024/1024).toFixed(1)} MB`, '#86efac');

        const finalCycle = window.__dmsLastCompletedCycle || state.activeCycle || {};
        try{
          await uploadForCompose(blob, finalCycle);
        }catch(err){
          console.warn('Upload for premium composition failed:', err);
          setStatus('Raw clip saved · premium upload failed', '#fca5a5');
        }
      };

      state.recorder.start(500);
      const rec=document.getElementById('dms-v4-rec');
      if(rec) rec.style.display='block';
      setStatus(`Recording cycle ${state.activeCycle?.id || ''}`, '#4ade80');
    }catch(err){
      console.warn(err);
      setStatus('Recorder start failed', '#fca5a5');
    }
  }

  function stopSegment(){
    if(state.recorder?.state === 'recording'){
      try{ state.recorder.stop(); }catch(_){}
    }
  }

  async function uploadForCompose(blob, cycle){
    if(state.uploading) return;
    const token=getToken();
    const accountId=getAccountId();
    if(!token || !accountId || !cycle?.id){
      throw new Error('Missing token/account/cycle id');
    }

    state.uploading=true;
    const uploadEl=document.getElementById('dms-v4-upload');
    if(uploadEl) uploadEl.style.display='block';
    setStatus('Authorizing ultra-premium upload…', '#67e8f9');

    try{
      const tr=await fetch('/api/live-capture-ticket', {
        method:'POST',
        headers:{
          'Content-Type':'application/json',
          'Authorization':`Bearer ${token}`
        },
        body:JSON.stringify({
          account_id: accountId,
          cycle_id: cycle.id,
          theme: 'ultra-premium'
        })
      });

      const td=await tr.json().catch(()=>({}));
      if(!tr.ok) throw new Error(td?.error || `Ticket HTTP ${tr.status}`);

      setStatus('Uploading live capture for ultra-premium composition…', '#67e8f9');

      const fd=new FormData();
      fd.append('video', blob, `dms-live-${cycle.id}.webm`);
      fd.append('ticket', td.ticket);
      fd.append('cycle', JSON.stringify(cycle));
      fd.append('website', 'https://www.digitmatchstar.com');

      const ur=await fetch(td.uploadUrl, {method:'POST', body:fd});
      const ud=await ur.json().catch(()=>({}));
      if(!ur.ok) throw new Error(ud?.detail || ud?.error || `Upload HTTP ${ur.status}`);

      setStatus('Ultra-premium video sent privately to Telegram ✓', '#86efac');
      window.__dmsLastUltraPremiumResult = ud;
    } finally {
      state.uploading=false;
      if(uploadEl) uploadEl.style.display='none';
    }
  }

  function patchCyclePerformance(){
    const cp=window.cyclePerformance;
    if(!cp || state.patched) return false;

    const originalStart=cp.startCycle?.bind(cp);
    const originalComplete=cp.completeCycle?.bind(cp);
    if(typeof originalStart !== 'function' || typeof originalComplete !== 'function') return false;

    cp.startCycle=function(...args){
      const result=originalStart(...args);
      setTimeout(() => {
        try{ startSegment(cp.current); }catch(_){}
      }, 120);
      return result;
    };

    cp.completeCycle=function(...args){
      const completed=originalComplete(...args);
      window.__dmsLastCompletedCycle = completed ? JSON.parse(JSON.stringify(completed)) : null;
      setTimeout(stopSegment, 1900);
      return completed;
    };

    state.patched=true;
    console.log('🎥 DigitMatchStar Ultra Premium Live Capture v4 attached.');
    return true;
  }

  function boot(){
    ensurePanel();
    if(!patchCyclePerformance()){
      const timer=setInterval(() => {
        if(patchCyclePerformance()) clearInterval(timer);
      }, 500);
      setTimeout(() => clearInterval(timer), 30000);
    }
  }

  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, {once:true});
  else boot();

  window.dmsUltraPremiumRecorder = {
    enable: enableCapture,
    start: startSegment,
    stop: stopSegment,
    state
  };
})();
