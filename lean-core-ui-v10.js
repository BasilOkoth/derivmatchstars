/*
 * DigitMatchStar Lean Core UI V10
 *
 * Keeps operational controls and useful evidence only.
 */
(() => {
  'use strict';

  const obsoleteIds = [
    'edge-market-scanner',
    'safe-tick-v1-panel',
    'tail-risk-panel',
    'tail-precursor-panel',
    'post-stop-depth-panel',
    'digit-dna-panel',
    'digit-feature-panel',
    'randomness-auditor-panel',
    'next-tick-edge-panel',
    'serverContinuousResearchBtn',
    's20Button'
  ];

  function hide(id) {
    const el = document.getElementById(id);
    if (!el) return;

    el.style.setProperty(
      'display',
      'none',
      'important'
    );

    el.dataset.dmsLeanHidden = '1';
  }

  function clean() {
    obsoleteIds.forEach(hide);

    // Continuous research belonged to the experimentation phase.
    const server = window.SERVER_EXECUTION;

    if (server) {
      server.continuousResearch = false;
      server.continuousRestartPending = false;

      if (server.continuousRestartTimer) {
        clearTimeout(server.continuousRestartTimer);
        server.continuousRestartTimer = null;
      }
    }

    try {
      sessionStorage.setItem(
        'dms_server_continuous_research',
        '0'
      );

      localStorage.setItem(
        'dms_server_continuous_research',
        '0'
      );
    } catch (_) {}

    // Keep Cycle Performance because this is the useful recorder.
    const recorder = document.getElementById(
      'cycle-performance-panel'
    );

    if (recorder) {
      const title = recorder.querySelector(
        '.font-bold'
      );

      if (
        title &&
        !String(title.textContent || '').includes('RECORDER')
      ) {
        title.textContent =
          '📝 CYCLE RECORDER / PERFORMANCE';
      }
    }

    // Make the live rank panel visually prominent.
    const score = document.getElementById(
      'recycle-runtime-panel'
    );

    if (score) {
      score.style.borderWidth = '2px';
    }
  }

  function start() {
    clean();

    const observer = new MutationObserver(clean);

    observer.observe(
      document.body,
      {
        childList: true,
        subtree: true
      }
    );

    window.addEventListener(
      'beforeunload',
      () => observer.disconnect(),
      { once: true }
    );
  }

  if (document.readyState === 'loading') {
    document.addEventListener(
      'DOMContentLoaded',
      start,
      { once: true }
    );
  } else {
    start();
  }
})();
