/*
 * DigitMatchStar Research Add-on Loader
 * Tick DNA Validation V2.6 + Entry Tick DNA V2 frozen shadow cohort · V3.4 ACTUAL BOT EVENT WIRE.
 */
(() => {
  'use strict';

  const scripts = [
    '/tail-risk-model-v1.2-combined.js?v=tail-risk-v1-8',
    '/tick-dna-tail-validation-v2.js?v=2.6-hardstop',
    '/entry-tick-dna-v2-shadow.js?v=3.4-actual-bot-event-wire'
  ];

  function alreadyLoaded(src) {
    const requested = new URL(src, location.href);

    return Array.from(document.scripts).some(s => {
      try {
        const existing = new URL(s.src, location.href);

        /*
         * IMPORTANT:
         * Compare both pathname AND search string.
         *
         * The previous loader compared pathname only, so:
         *   entry-tick-dna-v2-shadow.js?v=3.3...
         * and
         *   entry-tick-dna-v2-shadow.js?v=3.4...
         *
         * were treated as the same already-loaded script.
         * That could leave the old cached V3.3 module running.
         */
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
      if (alreadyLoaded(src)) {
        console.info(`[DMS Research Add-on] Already loaded: ${src}`);
        return resolve();
      }

      const el = document.createElement('script');
      el.src = src;
      el.async = false;
      el.dataset.dmsResearchAddon = '1';

      el.onload = () => {
        console.info(`[DMS Research Add-on] Loaded: ${src}`);
        resolve();
      };

      el.onerror = () => {
        reject(new Error(`Failed to load ${src}`));
      };

      document.head.appendChild(el);
    });
  }

  async function start() {
    try {
      for (const src of scripts) {
        await loadScript(src);
      }

      console.info(
        '[DMS Research Add-on] Tick DNA V2.6 + Entry Tick DNA V2 V3.4 actual-bot-event-wire loaded.'
      );
    } catch (err) {
      console.error('[DMS Research Add-on] Startup failed:', err);
      throw err;
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener(
      'DOMContentLoaded',
      () => {
        start().catch(err =>
          console.error('[DMS Research Add-on]', err)
        );
      },
      { once: true }
    );
  } else {
    start().catch(err =>
      console.error('[DMS Research Add-on]', err)
    );
  }
})();
