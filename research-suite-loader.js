/*
 * DigitMatchStar Core Loader V10
 *
 * Lean operational build:
 * - recorder/export
 * - canonical tick ↔ rank sync
 * - contract timeline
 * - score >= 9 gate
 * - passive rank-session bootstrap
 * - lean UI cleanup
 *
 * Experimental research add-ons are intentionally not loaded.
 */
(() => {
  'use strict';

  const scripts = [
    '/trade-alignment-export.js?v=core-v10',
    '/tick-rank-sync-v1.1.js?v=core-v10',
    '/contract-timeline-ui.js?v=core-v10',
    '/target-score-threshold-ui.js?v=10.0',
    '/rank-session-bootstrap-v10.js?v=10.0',
    '/lean-core-ui-v10.js?v=10.0'
  ];

  function alreadyLoaded(src) {
    const requested = new URL(src, location.href);

    return Array.from(document.scripts).some(script => {
      try {
        const existing = new URL(script.src, location.href);

        return (
          existing.pathname === requested.pathname &&
          existing.search === requested.search
        );
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
      el.dataset.dmsCoreAddon = '1';
      el.onload = resolve;
      el.onerror = () => reject(
        new Error(`Failed to load ${src}`)
      );

      document.head.appendChild(el);
    });
  }

  async function start() {
    for (const src of scripts) {
      await loadScript(src);
    }

    console.info(
      '[DigitMatchStar Core V10] Lean core + live DigitScore loaded.'
    );
  }

  const run = () => start().catch(
    error => console.error(
      '[DigitMatchStar Core V10]',
      error
    )
  );

  if (document.readyState === 'loading') {
    document.addEventListener(
      'DOMContentLoaded',
      run,
      { once: true }
    );
  } else {
    run();
  }
})();
