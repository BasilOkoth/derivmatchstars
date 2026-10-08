/*
 * DigitMatchStar Canonical Tick ↔ Rank Synchronizer v1.0
 * Research/display only. Never places, changes, confirms, or stops a trade.
 *
 * Goal:
 *   canonical tick E -> V1 ranking(E) -> shadow(E) -> NEXT target(E)
 * and make the shared epoch visible in the UI.
 */
(() => {
  'use strict';

  const state = {
    latestBrowserTick: null,
    syncToken: 0,
    inFlight: false,
    pendingEpoch: 0,
    retryTimer: null,
    lastAlignedEpoch: 0,
    lastLatencyMs: null
  };

  const RETRY_DELAYS = [0, 45, 110, 220];

  function asInt(value) {
    const n = Number(value);
    return Number.isInteger(n) ? n : 0;
  }

  function fmtEpoch(value) {
    const n = asInt(value);
    return n > 0 ? String(n) : '—';
  }

  function ensurePanel() {
    const host = document.getElementById('recycle-runtime-panel');
    if (!host) return null;
    let el = document.getElementById('dms-tick-rank-sync-panel');
    if (el) return el;

    el = document.createElement('div');
    el.id = 'dms-tick-rank-sync-panel';
    el.className = 'mt-2 rounded-lg border border-sky-500/30 bg-slate-900/70 p-2 text-[10px]';
    el.innerHTML = `
      <div class="flex items-center justify-between gap-2 mb-1.5">
        <div class="font-black uppercase tracking-wide text-sky-300">Canonical Tick ↔ Rank Sync</div>
        <div id="dms-sync-badge" class="font-black text-amber-300">WAITING</div>
      </div>
      <div class="grid grid-cols-2 md:grid-cols-5 gap-1">
        <div class="rounded bg-slate-950/80 p-1.5">
          <div class="text-gray-400">Browser tick</div>
          <b id="dms-sync-browser">—</b>
          <div id="dms-sync-browser-epoch" class="text-gray-500">e: —</div>
        </div>
        <div class="rounded bg-slate-950/80 p-1.5">
          <div class="text-gray-400">Server tick</div>
          <b id="dms-sync-server">—</b>
          <div id="dms-sync-server-epoch" class="text-gray-500">e: —</div>
        </div>
        <div class="rounded bg-slate-950/80 p-1.5">
          <div class="text-gray-400">V1 #1</div>
          <b id="dms-sync-rank">—</b>
          <div id="dms-sync-rank-epoch" class="text-gray-500">e: —</div>
        </div>
        <div class="rounded bg-slate-950/80 p-1.5">
          <div class="text-gray-400">Shadow pick</div>
          <b id="dms-sync-shadow">—</b>
          <div id="dms-sync-shadow-epoch" class="text-gray-500">e: —</div>
        </div>
        <div class="rounded bg-slate-950/80 p-1.5">
          <div class="text-gray-400">NEXT target</div>
          <b id="dms-sync-target">—</b>
          <div id="dms-sync-target-epoch" class="text-gray-500">e: —</div>
        </div>
      </div>
      <div id="dms-sync-note" class="mt-1.5 text-gray-400">
        Waiting for canonical server epoch metadata…
      </div>`;

    const note = host.querySelector('#digit-score-note');
    if (note) host.insertBefore(el, note);
    else host.appendChild(el);
    return el;
  }

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function currentServerState() {
    return window.SERVER_EXECUTION?.state || null;
  }

  function render() {
    if (!ensurePanel()) return false;

    const browser = state.latestBrowserTick;
    const st = currentServerState();
    const score = st?.digit_score || {};
    const serverTick = score?.canonical_tick || {};
    const shadow = score?.shadow || {};

    const browserEpoch = asInt(browser?.epoch);
    const serverEpoch = asInt(serverTick?.epoch);
    const rankEpoch = asInt(score?.rank_epoch);
    const shadowEpoch = asInt(score?.shadow_epoch ?? shadow?.rank_epoch);
    const targetEpoch = asInt(score?.target_epoch);

    const rankDigit = Number(score?.selected_digit);
    const shadowDigit = Number(shadow?.selected_digit);
    const nextDigit = Number(st?.live_next_target ?? score?.selected_digit);

    setText('dms-sync-browser', browser ? `digit ${browser.digit}` : '—');
    setText('dms-sync-browser-epoch', `e: ${fmtEpoch(browserEpoch)}`);
    setText('dms-sync-server', serverEpoch ? `digit ${serverTick?.digit ?? '—'}` : '—');
    setText('dms-sync-server-epoch', `e: ${fmtEpoch(serverEpoch)}`);
    setText('dms-sync-rank', Number.isInteger(rankDigit) ? `digit ${rankDigit}` : '—');
    setText('dms-sync-rank-epoch', `e: ${fmtEpoch(rankEpoch)}`);
    setText('dms-sync-shadow', Number.isInteger(shadowDigit) ? `digit ${shadowDigit}` : '—');
    setText('dms-sync-shadow-epoch', `e: ${fmtEpoch(shadowEpoch)}`);
    setText('dms-sync-target', Number.isInteger(nextDigit) ? `digit ${nextDigit}` : '—');
    setText('dms-sync-target-epoch', `e: ${fmtEpoch(targetEpoch)}`);

    const sameServerEpoch = serverEpoch > 0 &&
      serverEpoch === rankEpoch &&
      serverEpoch === shadowEpoch &&
      serverEpoch === targetEpoch;
    const browserCaughtUp = !browserEpoch || browserEpoch === serverEpoch;
    const aligned = sameServerEpoch && browserCaughtUp;

    const badge = document.getElementById('dms-sync-badge');
    if (badge) {
      if (aligned) {
        badge.textContent = 'EXACT SAME EPOCH ✓';
        badge.className = 'font-black text-emerald-300';
      } else if (browserEpoch && serverEpoch && serverEpoch < browserEpoch) {
        badge.textContent = 'SERVER CATCHING UP';
        badge.className = 'font-black text-amber-300';
      } else if (serverEpoch && rankEpoch && serverEpoch !== rankEpoch) {
        badge.textContent = 'RANK EPOCH MISMATCH';
        badge.className = 'font-black text-rose-300';
      } else {
        badge.textContent = 'WAITING';
        badge.className = 'font-black text-amber-300';
      }
    }

    if (aligned && serverEpoch !== state.lastAlignedEpoch) {
      state.lastAlignedEpoch = serverEpoch;
      if (browser?.receivedAt) {
        state.lastLatencyMs = Math.max(0, Date.now() - Number(browser.receivedAt));
      }
    }

    setText(
      'dms-sync-note',
      aligned
        ? `Tick, V1, shadow and NEXT target are aligned on epoch ${serverEpoch}` +
          (Number.isFinite(state.lastLatencyMs) ? ` · UI sync ${state.lastLatencyMs} ms` : '')
        : `Open contract target stays frozen; only NEXT target follows the newest canonical rank.`
    );

    return aligned;
  }

  async function pollOnceForEpoch(expectedEpoch, token) {
    if (token !== state.syncToken) return false;
    const poll = window.pollServerExecutionState;
    if (typeof poll !== 'function') {
      render();
      return false;
    }

    try {
      await poll();
    } catch (_) {
      // Existing server poller owns connectivity/error presentation.
    }

    if (token !== state.syncToken) return false;
    const aligned = render();
    const score = currentServerState()?.digit_score || {};
    const rankEpoch = asInt(score.rank_epoch);
    return aligned || (expectedEpoch > 0 && rankEpoch >= expectedEpoch);
  }

  function scheduleImmediateSync(tick) {
    state.latestBrowserTick = {
      epoch: asInt(tick?.epoch),
      digit: asInt(tick?.digit),
      quote: tick?.quote,
      receivedAt: Number(tick?.receivedAt || Date.now())
    };
    render();

    const server = window.SERVER_EXECUTION;
    if (!server?.enabled || !server?.apiUrl) return;

    const token = ++state.syncToken;
    const expectedEpoch = state.latestBrowserTick.epoch;

    if (state.retryTimer) {
      clearTimeout(state.retryTimer);
      state.retryTimer = null;
    }

    const attempt = async (index) => {
      if (token !== state.syncToken) return;
      if (state.inFlight) {
        state.retryTimer = setTimeout(() => attempt(index), 20);
        return;
      }

      state.inFlight = true;
      let caughtUp = false;
      try {
        caughtUp = await pollOnceForEpoch(expectedEpoch, token);
      } finally {
        state.inFlight = false;
      }

      if (!caughtUp && token === state.syncToken && index + 1 < RETRY_DELAYS.length) {
        state.retryTimer = setTimeout(
          () => attempt(index + 1),
          RETRY_DELAYS[index + 1]
        );
      }
    };

    attempt(0);
  }

  window.addEventListener('digitmatchstar:tick', (event) => {
    const tick = event?.detail;
    if (!tick?.canonical || !asInt(tick?.epoch)) return;
    scheduleImmediateSync(tick);
  });

  // Keep the sync strip alive across dynamic panel creation/re-rendering.
  setInterval(render, 500);

  window.DMSTickRankSync = {
    version: '1.0',
    state,
    render,
    syncNow: () => {
      if (state.latestBrowserTick) scheduleImmediateSync(state.latestBrowserTick);
    }
  };

  console.info('[DMS Tick-Rank Sync] v1.0 active · display/research only · no trade actions');
})();
