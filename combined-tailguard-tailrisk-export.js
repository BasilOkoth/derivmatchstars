/*
 * DigitMatchStar Combined Research Export v1.0
 *
 * Purpose:
 * - Keep the EXISTING TailGuard "Export research" button.
 * - Prevent the original TailGuard-only download.
 * - Download ONE combined JSON containing TailGuard + Tail Risk Model.
 *
 * This module does not trade and does not modify trading logic.
 * Load AFTER TailGuard and tail-risk-model-v1.2-combined.js.
 */
(() => {
  'use strict';

  const VERSION = 'COMBINED-RESEARCH-EXPORT-1.0';

  function safeClone(v) {
    try { return JSON.parse(JSON.stringify(v)); } catch (_) { return null; }
  }

  function globalBinding(name) {
    try {
      return (0, eval)(`typeof ${name} !== 'undefined' ? ${name} : null`);
    } catch (_) {
      return null;
    }
  }

  function getCyclePerformance() {
    return globalBinding('cyclePerformance') || window.cyclePerformance || null;
  }

  function getPostStopTracker() {
    return globalBinding('postStopDepthTracker') || window.postStopDepthTracker || null;
  }

  function currentSymbol() {
    const cp = getCyclePerformance();
    return (
      cp?.stats?.symbol ||
      document.getElementById('symbol')?.value ||
      window.tickFormat?.symbol ||
      'symbol'
    );
  }

  function getTailGuardSnapshot() {
    const tg = window.DMSTailGuardResearch;
    if (!tg) return null;

    return {
      version: tg.version || null,
      researchOnly: tg.researchOnly === true,
      config: safeClone(tg.config || null),
      summary: typeof tg.getSummary === 'function' ? safeClone(tg.getSummary()) : null,
      records: typeof tg.getRecords === 'function' ? safeClone(tg.getRecords()) : []
    };
  }

  function getTailRiskSnapshot() {
    const model = window.DMSTailRiskModel;
    if (!model || typeof model.getResearchSnapshot !== 'function') {
      return {
        available: false,
        reason: 'Tail Risk Model snapshot API not available'
      };
    }

    try {
      return {
        available: true,
        ...safeClone(model.getResearchSnapshot())
      };
    } catch (err) {
      return {
        available: false,
        reason: String(err?.message || err || 'Unknown Tail Risk snapshot error')
      };
    }
  }

  function buildCombinedPayload() {
    const cp = getCyclePerformance();
    const tracker = getPostStopTracker();

    return {
      schema: 'DIGITMATCHSTAR_COMBINED_RESEARCH_REPORT_V1',
      generatedAt: new Date().toISOString(),
      exportModuleVersion: VERSION,
      symbol: currentSymbol(),
      researchOnly: true,
      liveTradingModified: false,

      source: {
        cyclePerformanceStats: safeClone(cp?.stats || null),
        postStopDepthTrackerSummary: safeClone(
          tracker?.summary || tracker?.stats || null
        )
      },

      tailGuard: getTailGuardSnapshot(),
      tailRiskModel: getTailRiskSnapshot()
    };
  }

  function downloadCombinedReport() {
    const payload = buildCombinedPayload();
    const blob = new Blob(
      [JSON.stringify(payload, null, 2)],
      { type: 'application/json' }
    );

    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download =
      `tailguard-combined-research-${payload.symbol || 'symbol'}-` +
      `${new Date().toISOString().replace(/[:.]/g, '-')}.json`;

    document.body.appendChild(a);
    a.click();

    setTimeout(() => {
      try { URL.revokeObjectURL(a.href); } catch (_) {}
      a.remove();
    }, 500);

    return payload;
  }

  /*
   * Capture phase is deliberate:
   * TailGuard's original click listener is attached directly to #tg-export.
   * We intercept first, stop the TailGuard-only export, then download one
   * combined report.
   */
  document.addEventListener('click', event => {
    const btn = event.target?.closest?.('#tg-export');
    if (!btn) return;

    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();

    downloadCombinedReport();
  }, true);

  window.DMSCombinedResearchExport = Object.freeze({
    version: VERSION,
    build: buildCombinedPayload,
    download: downloadCombinedReport
  });
})();
