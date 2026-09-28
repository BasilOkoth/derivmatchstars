/*
 * DigitMatchStar Research Suite Loader
 * Loads the research modules in the required order.
 *
 * Existing repo dependency:
 *   /tailguard-research-v2-autopilot.js
 *
 * New files:
 *   /tail-risk-model-v1.2-combined.js
 *   /combined-tailguard-tailrisk-export.js
 */
(() => {
  'use strict';

  const scripts = [
    '/tailguard-research-v2-autopilot.js',
    '/tail-risk-model-v1.2-combined.js',
    '/combined-tailguard-tailrisk-export.js'
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
      if (alreadyLoaded(src)) {
        resolve();
        return;
      }

      const el = document.createElement('script');
      el.src = src;
      el.async = false;
      el.dataset.dmsResearchSuite = '1';
      el.onload = () => resolve();
      el.onerror = () => reject(new Error(`Failed to load ${src}`));
      document.head.appendChild(el);
    });
  }

  async function start() {
    for (const src of scripts) {
      await loadScript(src);
    }
    console.info('[DMS Research Suite] TailGuard + Tail Risk + Combined Export loaded.');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      start().catch(err => console.error('[DMS Research Suite]', err));
    }, { once: true });
  } else {
    start().catch(err => console.error('[DMS Research Suite]', err));
  }
})();
