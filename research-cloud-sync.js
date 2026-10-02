/* DigitMatchStar generic cross-device research sync. */
(() => {
  'use strict';
  const DB_NAME='DigitMatchStarTickDNA', DB_VERSION=1, DB_STORE='validation';
  const DATASETS = [
    'tick-dna-tail-validation-v22-uncensored',
    'entry-tick-dna-v2-shadow-r10',
    'candidate-tick-dna-v3-aligned-r10'
  ];
  let lastStatus='starting';

  function emit(status){ lastStatus=status; try{window.dispatchEvent(new CustomEvent('dms:research-cloud-status',{detail:{status}}));}catch(_){} }
  function token(){return localStorage.getItem('active_token')||localStorage.getItem('derivToken')||localStorage.getItem('derivTokenDemo')||'';}
  function account(){return localStorage.getItem('active_account')||localStorage.getItem('derivAccount')||localStorage.getItem('derivDemoAccount')||'';}
  function symbol(){return document.getElementById('symbol')?.value||window.tickFormat?.symbol||'R_10';}
  function deviceId(){let x=localStorage.getItem('dms_research_device_id');if(!x){x=`dev-${Date.now()}-${Math.random().toString(36).slice(2,10)}`;localStorage.setItem('dms_research_device_id',x);}return x;}

  function openDB(){return new Promise((resolve,reject)=>{const r=indexedDB.open(DB_NAME,DB_VERSION);r.onupgradeneeded=()=>{if(!r.result.objectStoreNames.contains(DB_STORE))r.result.createObjectStore(DB_STORE);};r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}
  async function get(key){const db=await openDB();try{return await new Promise((resolve,reject)=>{const tx=db.transaction(DB_STORE,'readonly');const r=tx.objectStore(DB_STORE).get(key);r.onsuccess=()=>resolve(r.result||null);r.onerror=()=>reject(r.error);});}finally{db.close();}}
  async function put(key,val){const db=await openDB();try{await new Promise((resolve,reject)=>{const tx=db.transaction(DB_STORE,'readwrite');tx.objectStore(DB_STORE).put(val,key);tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);});}finally{db.close();}}
  function progress(s){
    if(!s||typeof s!=='object')return 0;
    if(Array.isArray(s.candidates)) return s.candidates.filter(x=>x?.finalized).length*100000 + s.candidates.length;
    if(Array.isArray(s.cycles)) return s.cycles.filter(x=>x?.finalized||x?.outcome).length*100000 + s.cycles.length;
    return Number(s?.progress?.totalForwardTicks||0);
  }
  async function api(action,dataset,state){
    const t=token(), a=account(); if(!t||!a) throw new Error('not authenticated');
    const r=await fetch('/api/research-cloud-state',{method:'POST',headers:{'Content-Type':'application/json','Authorization':`Bearer ${t}`},body:JSON.stringify({action,dataset,state,account_id:a,symbol:symbol(),device_id:deviceId()})});
    const j=await r.json().catch(()=>({}));
    if(!r.ok) { const e=new Error(j.error||`HTTP ${r.status}`); e.remote=j.state; throw e; }
    return j;
  }
  async function syncKey(key){
    emit(`syncing ${key}`);
    const local=await get(key);
    let remote=null;
    try { remote=(await api('load',key,null)).state||null; } catch(e){ if(String(e.message).includes('not authenticated')){emit('local only · sign in required');return local;} throw e; }
    if(!local && remote){await put(key,remote);emit(`cloud restored · ${key}`);return remote;}
    if(local && !remote){const out=(await api('save',key,local)).state;await put(key,out);emit(`cloud saved · ${key}`);return out;}
    if(local && remote){
      if(progress(remote)>progress(local)){await put(key,remote);emit(`cloud newer · restored ${key}`);return remote;}
      if(progress(local)>progress(remote)){try{const out=(await api('save',key,local)).state;await put(key,out);emit(`cloud updated · ${key}`);return out;}catch(e){if(e.remote){await put(key,e.remote);emit(`cloud conflict · remote kept ${key}`);return e.remote;}throw e;}}
      emit(`cloud synced · ${key}`);return local;
    }
    emit(`cloud ready · ${key}`); return null;
  }
  async function syncAll(){for(const k of DATASETS){try{await syncKey(k);}catch(e){console.warn('[DMS cloud]',k,e);emit(`cloud error · ${e.message}`);}}}
  window.DMSResearchCloud=Object.freeze({syncKey,syncAll,status:()=>lastStatus,datasets:()=>[...DATASETS]});
  const boot=()=>{syncAll().catch(()=>{});setInterval(()=>syncAll().catch(()=>{}),30000);};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
