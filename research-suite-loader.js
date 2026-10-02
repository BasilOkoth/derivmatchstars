/*
 * DigitMatchStar Research Add-on Loader
 * Tick DNA Validation V2.6 + cross-device sync + Candidate Tick DNA V3.7 exact alignment.
 */
(() => {
  'use strict';
  const scripts = [
    '/research-cloud-sync.js?v=3.7-cross-device',
    '/tail-risk-model-v1.2-combined.js?v=tail-risk-v1-8',
    '/tick-dna-tail-validation-v2.js?v=2.6-hardstop',
    '/candidate-tick-dna-v3-shadow.js?v=3.7-exact-aligned-cloud'
  ];
  function alreadyLoaded(src){const requested=new URL(src,location.href);return Array.from(document.scripts).some(s=>{try{const existing=new URL(s.src,location.href);return existing.pathname===requested.pathname&&existing.search===requested.search;}catch(_){return false;}});}
  function loadScript(src){return new Promise((resolve,reject)=>{if(alreadyLoaded(src))return resolve();const el=document.createElement('script');el.src=src;el.async=false;el.dataset.dmsResearchAddon='1';el.onload=resolve;el.onerror=()=>reject(new Error(`Failed to load ${src}`));document.head.appendChild(el);});}
  async function start(){for(const src of scripts)await loadScript(src);console.info('[DMS Research Add-on] Candidate Tick DNA V3.7 exact-aligned + cross-device research sync loaded.');}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>start().catch(err=>console.error('[DMS Research Add-on]',err)),{once:true});else start().catch(err=>console.error('[DMS Research Add-on]',err));
})();
