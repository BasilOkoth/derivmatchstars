/*
 * DigitMatchStar Rank Session Bootstrap V10
 *
 * Creates/reuses an IDLE server session after OAuth so DigitScore can receive
 * its passive tick feed before START BOT is pressed. This does not start a
 * trading cycle and does not submit any purchase.
 */
(() => {
  'use strict';

  let inFlight = false;
  let timer = null;

  function mode() {
    return String(
      sessionStorage.getItem('selectedAccountMode') ||
      localStorage.getItem('selectedAccountMode') ||
      'DEMO'
    ).toUpperCase();
  }

  function config() {
    return {
      symbol:
        document.getElementById('symbol')?.value ||
        'R_10',
      base_stake: Number(
        document.getElementById('baseStake')?.value ||
        1
      ),
      multiplier: Number(
        document.getElementById('multiplier')?.value ||
        1.15
      ),
      max_trades: Number(
        document.getElementById('maxTrades')?.value ||
        20
      )
    };
  }

  async function ensureRankSession() {
    if (inFlight) return;

    const server = window.SERVER_EXECUTION;

    if (
      !server?.enabled ||
      !server.apiUrl ||
      typeof window.serverExecRequest !== 'function'
    ) {
      return;
    }

    if (!(
      sessionStorage.getItem('dms_platform_jwt') ||
      localStorage.getItem('dms_platform_jwt')
    )) {
      return;
    }

    inFlight = true;

    try {
      const wanted = mode();

      const auth = await window.serverExecRequest(
        '/auth/platform/me'
      );

      const account = (auth?.accounts || []).find(
        row =>
          String(
            row?.account_type || ''
          ).toUpperCase() === wanted
      );

      if (!account) return;

      const sessions = await window.serverExecRequest(
        '/sessions'
      );

      let row = (sessions || []).find(
        item =>
          String(item?.account_id || '') ===
          String(account.account_id)
      );

      if (!row) {
        const cfg = config();

        row = await window.serverExecRequest(
          '/sessions',
          {
            method: 'POST',
            body: {
              account_id: account.account_id,
              symbol: cfg.symbol,
              base_stake: cfg.base_stake,
              multiplier: cfg.multiplier,
              max_trades: cfg.max_trades
            }
          }
        );
      }

      if (row?.id) {
        server.sessionId = Number(row.id);

        sessionStorage.setItem(
          'dms_server_session_id',
          String(server.sessionId)
        );

        try {
          localStorage.setItem(
            'dms_server_session_id',
            String(server.sessionId)
          );
        } catch (_) {}

        if (
          typeof window.pollServerExecutionState ===
          'function'
        ) {
          await window.pollServerExecutionState();
        }
      }

    } catch (error) {
      console.warn(
        '[Rank Session Bootstrap V10]',
        error
      );

    } finally {
      inFlight = false;
    }
  }

  function start() {
    ensureRankSession();

    timer = setInterval(
      ensureRankSession,
      3000
    );

    window.addEventListener(
      'beforeunload',
      () => clearInterval(timer),
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
