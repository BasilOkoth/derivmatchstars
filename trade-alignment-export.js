/*
 * DigitMatchStar Trade Alignment Export V1
 *
 * Extends the existing Trigger Fusion CSV export without changing bot trading.
 * Alignment data is persisted by app/engine.py inside:
 *   record.evidence.alignment.purchase
 *   record.evidence.alignment.fast_decision
 *   record.evidence.alignment.deriv_settlement
 */
(() => {
  'use strict';

  const ALIGNMENT_COLUMNS = [
    'alignment_verdict',
    'purchase_target_digit',
    'purchase_armed_after_epoch',
    'purchase_epoch',
    'purchase_t0_epoch',
    'purchase_t0_digit',
    'purchase_t0_quote',
    'purchase_t0_matches_target',
    'fast_target_digit',
    'fast_decision_epoch',
    'fast_observed_digit',
    'fast_observed_quote',
    'fast_result',
    'fast_matches_target',
    'deriv_target_digit',
    'deriv_settlement_epoch',
    'deriv_exit_tick',
    'deriv_settlement_digit',
    'deriv_result',
    'deriv_matches_target',
    'purchase_to_fast_epoch_delta'
  ];

  function csvEscape(value) {
    if (value === null || value === undefined) return '';
    let text =
      typeof value === 'object'
        ? JSON.stringify(value)
        : String(value);

    if (/[",\n\r]/.test(text)) {
      text = `"${text.replace(/"/g, '""')}"`;
    }
    return text;
  }

  function flattenAlignment(row) {
    const alignment = row?.evidence?.alignment || {};
    const purchase = alignment?.purchase || {};
    const fast = alignment?.fast_decision || {};
    const deriv = alignment?.deriv_settlement || {};

    return {
      alignment_verdict: alignment?.verdict ?? '',
      purchase_target_digit: purchase?.target_digit ?? '',
      purchase_armed_after_epoch: purchase?.armed_after_epoch ?? '',
      purchase_epoch: purchase?.purchase_epoch ?? '',
      purchase_t0_epoch: purchase?.t0_epoch ?? '',
      purchase_t0_digit: purchase?.t0_digit ?? '',
      purchase_t0_quote: purchase?.t0_quote ?? '',
      purchase_t0_matches_target: purchase?.t0_matches_target ?? '',
      fast_target_digit: fast?.target_digit ?? '',
      fast_decision_epoch: fast?.decision_epoch ?? '',
      fast_observed_digit: fast?.observed_digit ?? '',
      fast_observed_quote: fast?.observed_quote ?? '',
      fast_result: fast?.result ?? '',
      fast_matches_target: fast?.digit_matches_target ?? '',
      deriv_target_digit: deriv?.target_digit ?? '',
      deriv_settlement_epoch: deriv?.settlement_epoch ?? '',
      deriv_exit_tick: deriv?.exit_tick ?? '',
      deriv_settlement_digit: deriv?.settlement_digit ?? '',
      deriv_result: deriv?.result ?? '',
      deriv_matches_target: deriv?.digit_matches_target ?? '',
      purchase_to_fast_epoch_delta:
        alignment?.purchase_to_fast_epoch_delta ?? ''
    };
  }

  function install() {
    if (window.__dmsTradeAlignmentExportInstalled) return true;

    const original = window.triggerFusionToCsv;
    if (typeof original !== 'function') return false;

    window.triggerFusionToCsv = function(records) {
      const rows = Array.isArray(records) ? records : [];
      const baseCsv = original(rows);
      const baseLines = String(baseCsv || '').split('\n');

      if (!baseLines.length) return baseCsv;

      const output = [
        `${baseLines[0]},${ALIGNMENT_COLUMNS.join(',')}`
      ];

      for (let i = 1; i < baseLines.length; i++) {
        const row = rows[i - 1] || {};
        const flat = flattenAlignment(row);
        const suffix = ALIGNMENT_COLUMNS
          .map(col => csvEscape(flat[col]))
          .join(',');
        output.push(`${baseLines[i]},${suffix}`);
      }

      return output.join('\n');
    };

    window.getTradeAlignmentEvidence = function(record) {
      return flattenAlignment(record || {});
    };

    window.__dmsTradeAlignmentExportInstalled = true;
    console.info(
      '[DMS Trade Alignment Export V1] CSV now includes purchase T+0, fast decision, Deriv settlement and verdict columns.'
    );
    return true;
  }

  if (install()) return;

  let attempts = 0;
  const timer = setInterval(() => {
    attempts += 1;
    if (install() || attempts >= 100) {
      clearInterval(timer);
      if (attempts >= 100 && !window.__dmsTradeAlignmentExportInstalled) {
        console.warn(
          '[DMS Trade Alignment Export V1] triggerFusionToCsv was not found.'
        );
      }
    }
  }, 100);
})();
