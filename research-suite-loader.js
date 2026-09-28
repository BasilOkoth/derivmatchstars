/*
 * DigitMatchStar Research Add-on Loader
 *
 * The main bot already contains TailGuard Autopilot Research v2.6.
 * DO NOT load tailguard-research-v2-autopilot.js here or a duplicate
 * TailGuard research panel will appear.
 *
 * This loader adds only the private Tail Risk Model.
 */
(() => {
  'use strict';

  const scripts = [
    '/tail-risk-model-v1.2-combined.js'
  ];

  function alreadyLoaded(src) {
    return Array.from(document.scripts).some(s => {
      try {
        return new URL(s.src, location.href).pathname === new URL(src, location.href).pathname;
      } catch (_) {
        return false;
      }
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
    console.info('[DMS Research Add-on] Tail Risk Model loaded. Embedded TailGuard Autopilot retained.');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      start().catch(err => console.error('[DMS Research Add-on]', err));
    }, { once: true });
  } else {
    start().catch(err => console.error('[DMS Research Add-on]', err));
  }
})();
