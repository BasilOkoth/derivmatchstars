/*
 * DigitMatchStar Research Add-on Loader
 * Tick DNA Validation V2.1 · Frozen Tail Score V1.
 */
(() => {
  'use strict';

  const scripts = [
    '/tail-risk-model-v1.2-combined.js',
    '/tick-dna-tail-validation-v2.js?v=2.1'
  ];

  function alreadyLoaded(src) {
    const target = new URL(src, location.href).pathname;
    return Array.from(document.scripts).some(s => {
      try { return new URL(s.src, location.href).pathname === target; }
      catch (_) { return false; }
    });
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      if (alreadyLoaded(src)) return resolve();
      const el = document.createElement('script');
      el.src = src;
      el.async = false;
      el.dataset.dmsResearchAddon = '1';
      el.onload = resolve;
      el.onerror = () => reject(new Error(`Failed to load ${src}`));
      document.head.appendChild(el);
    });
  }

  async function start() {
    for (const src of scripts) await loadScript(src);
    console.info('[DMS Research Add-on] Tick DNA Validation V2.1 loaded.');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      start().catch(err => console.error('[DMS Research Add-on]', err));
    }, { once: true });
  } else {
    start().catch(err => console.error('[DMS Research Add-on]', err));
  }
})();
