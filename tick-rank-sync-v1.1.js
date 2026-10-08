/*
 * DigitMatchStar Canonical Tick ↔ Rank Synchronizer v1.1
 * Research/display only. Never places, changes, confirms, or stops a trade.
 *
 * Requires backend provenance fields injected by app/__init__.py:
 *   digit_score.canonical_tick
 *   digit_score.rank_epoch
 *   digit_score.shadow_epoch
 *   digit_score.target_epoch
 */
(() => {
  'use strict';

  if (window.DMSTickRankSyncV11) return;

  const state = {
    browserTick: null,
    token: 0,
    timer: null,
    lastAlignedEpoch: 0,
    lastLatencyMs: null
  };

  const RETRIES_MS = [0, 35, 80, 150, 260, 420];

  const asInt = (v) => {
    const n = Number(v);
    return Number.isInteger(n) ? n : 0;
  };

  const epochText = (v) => {
    const n = asInt(v);
    return n > 0 ? `e: ${n}` : 'e: —';
  };

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function ensurePanel() {
    const host = document.getElementById('recycle-runtime-panel');
    if (!host) return null;

    let panel = document.getElementById('dms-tick-rank-sync-panel');
    if (panel) return panel;

    panel = document.createElement('div');
    panel.id = 'dms-tick-rank-sync-panel';
    panel.className = 'mt-2 rounded-lg border border-sky-500/30 bg-slate-900/70 p-2 text-[10px]';

    panel.innerHTML = `
      <div class="flex items-center justify-between gap-2 mb-2">
        <div class="font-black uppercase tracking-wider text-sky-300">
          Canonical Tick ↔ Rank Sync
        </div>
        <div id="dms-sync-badge" class="font-black text-amber-300">WAITING</div>
      </div>

      <div class="grid grid-cols-2 md:grid-cols-5 gap-1">
        <div class="rounded bg-slate-950/70 p-1.5">
          <div class="text-slate-400">Browser tick</div>
          <b id="dms-sync-browser">—</b>
          <div id="dms-sync-browser-epoch" class="text-slate-400">e: —</div>
        </div>

        <div class="rounded bg-slate-950/70 p-1.5">
          <div class="text-slate-400">Server tick</div>
          <b id="dms-sync-server">—</b>
          <div id="dms-sync-server-epoch" class="text-slate-400">e: —</div>
        </div>

        <div class="rounded bg-slate-950/70 p-1.5">
          <div class="text-slate-400">V1 #1</div>
          <b id="dms-sync-rank">—</b>
          <div id="dms-sync-rank-epoch" class="text-slate-400">e: —</div>
        </div>

        <div class="rounded bg-slate-950/70 p-1.5">
          <div class="text-slate-400">Shadow pick</div>
          <b id="dms-sync-shadow">—</b>
          <div id="dms-sync-shadow-epoch" class="text-slate-400">e: —</div>
        </div>

        <div class="rounded bg-slate-950/70 p-1.5">
          <div class="text-slate-400">NEXT target</div>
          <b id="dms-sync-target">—</b>
          <div id="dms-sync-target-epoch" class="text-slate-400">e: —</div>
        </div>
      </div>

      <div id="dms-sync-note" class="mt-1.5 text-slate-400">
        Waiting for canonical server provenance.
      </div>
    `;

    const note = document.getElementById('digit-score-note');
    if (note?.parentNode === host) {
      host.insertBefore(panel, note);
    } else {
      host.appendChild(panel);
    }

    return panel;
  }

  function serverState() {
    return window.SERVER_EXECUTION?.state || null;
  }

  function render() {
    if (!ensurePanel()) return false;

    const browser = state.browserTick || {};
    const st = serverState();
    const score = st?.digit_score || {};
    const shadow = score?.shadow || {};
    const serverTick = score?.canonical_tick || {};

    const browserEpoch = asInt(browser.epoch);
    const serverEpoch = asInt(serverTick.epoch);
    const rankEpoch = asInt(score.rank_epoch);
    const shadowEpoch = asInt(score.shadow_epoch ?? shadow.rank_epoch);
    const targetEpoch = asInt(score.target_epoch);

    const browserDigit = Number(browser.digit);
    const serverDigit = Number(serverTick.digit);
    const rankDigit = Number(score.selected_digit);
    const shadowDigit = Number(shadow.selected_digit);
    const nextDigit = Number(st?.live_next_target ?? score.target_digit ?? score.selected_digit);

    setText('dms-sync-browser',
      Number.isInteger(browserDigit) ? `digit ${browserDigit}` : '—');
    setText('dms-sync-browser-epoch', epochText(browserEpoch));

    setText('dms-sync-server',
      Number.isInteger(serverDigit) ? `digit ${serverDigit}` : '—');
    setText('dms-sync-server-epoch', epochText(serverEpoch));

    setText('dms-sync-rank',
      Number.isInteger(rankDigit) ? `digit ${rankDigit}` : '—');
    setText('dms-sync-rank-epoch', epochText(rankEpoch));

    setText('dms-sync-shadow',
      Number.isInteger(shadowDigit) ? `digit ${shadowDigit}` : '—');
    setText('dms-sync-shadow-epoch', epochText(shadowEpoch));

    setText('dms-sync-target',
      Number.isInteger(nextDigit) ? `digit ${nextDigit}` : '—');
    setText('dms-sync-target-epoch', epochText(targetEpoch));

    const serverInternalAligned =
      serverEpoch > 0 &&
      serverEpoch === rankEpoch &&
      serverEpoch === shadowEpoch &&
      serverEpoch === targetEpoch;

    const browserAligned =
      browserEpoch > 0 &&
      browserEpoch === serverEpoch;

    const aligned = serverInternalAligned && browserAligned;

    const badge = document.getElementById('dms-sync-badge');

    if (badge) {
      if (aligned) {
        badge.textContent = 'EXACT SAME EPOCH ✓';
        badge.className = 'font-black text-emerald-300';
      } else if (!serverEpoch) {
        badge.textContent = 'WAITING FOR SERVER';
        badge.className = 'font-black text-amber-300';
      } else if (browserEpoch && serverEpoch < browserEpoch) {
        badge.textContent = 'SERVER CATCHING UP';
        badge.className = 'font-black text-amber-300';
      } else if (serverEpoch !== rankEpoch) {
        badge.textContent = 'RANK EPOCH MISMATCH';
        badge.className = 'font-black text-rose-300';
      } else if (serverEpoch !== shadowEpoch) {
        badge.textContent = 'SHADOW EPOCH MISMATCH';
        badge.className = 'font-black text-rose-300';
      } else if (serverEpoch !== targetEpoch) {
        badge.textContent = 'TARGET EPOCH MISMATCH';
        badge.className = 'font-black text-rose-300';
      } else if (browserEpoch !== serverEpoch) {
        badge.textContent = 'BROWSER/SERVER DIFFER';
        badge.className = 'font-black text-amber-300';
      } else {
        badge.textContent = 'WAITING';
        badge.className = 'font-black text-amber-300';
      }
    }

    if (aligned && serverEpoch !== state.lastAlignedEpoch) {
      state.lastAlignedEpoch = serverEpoch;
      if (browser.receivedAt) {
        state.lastLatencyMs = Math.max(
          0,
          Date.now() - Number(browser.receivedAt)
        );
      }
    }

    setText(
      'dms-sync-note',
      aligned
        ? `Tick, V1, shadow and NEXT target all belong to epoch ${serverEpoch}` +
          (Number.isFinite(state.lastLatencyMs)
            ? ` · catch-up ${state.lastLatencyMs} ms`
            : '')
        : 'Open contract target stays frozen; only NEXT target follows the newest canonical rank.'
    );

    return aligned;
  }

  async function pollForEpoch(expectedEpoch, token, attemptIndex = 0) {
    if (token !== state.token) return;

    const poll = window.pollServerExecutionState;
    if (typeof poll === 'function') {
      try {
        await poll();
      } catch (_) {}
    }

    if (token !== state.token) return;

    const aligned = render();
    const score = serverState()?.digit_score || {};
    const serverEpoch = asInt(score?.canonical_tick?.epoch);

    if (aligned) return;

    // If the server has already caught up or moved beyond the browser epoch,
    // stop the burst; normal 250 ms polling remains as a fallback.
    if (expectedEpoch > 0 && serverEpoch >= expectedEpoch) return;

    const next = attemptIndex + 1;
    if (next >= RETRIES_MS.length) return;

    clearTimeout(state.timer);
    state.timer = setTimeout(
      () => pollForEpoch(expectedEpoch, token, next),
      RETRIES_MS[next]
    );
  }

  function onCanonicalTick(event) {
    const tick = event?.detail || {};
    const epoch = asInt(tick.epoch);
    if (!epoch) return;

    state.browserTick = {
      epoch,
      digit: Number(tick.digit),
      quote: tick.quote,
      receivedAt: Number(tick.receivedAt || Date.now())
    };

    render();

    if (!window.SERVER_EXECUTION?.enabled) return;

    const token = ++state.token;
    clearTimeout(state.timer);

    state.timer = setTimeout(
      () => pollForEpoch(epoch, token, 0),
      RETRIES_MS[0]
    );
  }

  window.addEventListener('digitmatchstar:tick', onCanonicalTick);

  // Keep the panel current when ordinary server polling updates state.
  setInterval(render, 250);

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', render, { once: true });
  } else {
    render();
  }

  window.DMSTickRankSyncV11 = {
    state,
    render
  };
})();
