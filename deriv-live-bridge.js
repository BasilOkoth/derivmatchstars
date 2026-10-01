/*
 * DigitMatchStars - Deriv Options live connection bridge
 * v3: emits a full-fidelity research tick event for Tick DNA experiments.
 *
 * Load AFTER the bot's existing inline JavaScript:
 *   <script src="/deriv-live-bridge.js"></script>
 */
(function () {
  'use strict';

  function authMethod() {
    return localStorage.getItem('auth_method') || 'oauth2_pkce';
  }

  function emitResearchTick(tick) {
    try {
      if (!tick || tick.quote == null) return;
      const detail = {
        symbol: tick.symbol || document.getElementById('symbol')?.value || 'UNKNOWN',
        quote: Number(tick.quote),
        epoch: Number(tick.epoch) || Math.floor(Date.now() / 1000),
        pip_size: Number.isFinite(Number(tick.pip_size)) ? Number(tick.pip_size) : null,
        id: tick.id || null,
        receivedAt: Date.now()
      };
      window.dispatchEvent(new CustomEvent('digitmatchstar:tick', { detail }));
    } catch (_) {}
  }

  window.getAuthenticatedDerivWebSocketUrl = async function () {
    const token = window.getStoredDerivToken
      ? window.getStoredDerivToken()
      : (localStorage.getItem('active_token') || localStorage.getItem('derivToken'));

    const accountId = window.getStoredDerivAccount
      ? window.getStoredDerivAccount()
      : (localStorage.getItem('active_account') || localStorage.getItem('derivAccount'));

    if (!token) throw new Error('No Deriv access token found. Please login again.');
    if (!accountId) throw new Error('No Deriv Options account ID found. Please login again.');

    const payload = { token, account_id: accountId, auth_method: authMethod() };

    if (authMethod().toLowerCase() === 'pat') {
      payload.app_id =
        localStorage.getItem('deriv_app_id') ||
        localStorage.getItem('deriv_client_id') ||
        '';
    }

    const response = await fetch('/api/deriv-ws-url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok || !data.websocket_url) {
      throw new Error(data.error || 'Failed to get authenticated Deriv WebSocket URL');
    }

    return data.websocket_url;
  };

  window.connectWebSocket = async function () {
    if (window.ws) {
      try { window.ws.close(); } catch (_) {}
      window.ws = null;
    }

    window.isConnecting = true;
    if (typeof window.updateConnectionStatus === 'function') window.updateConnectionStatus();

    if (typeof window.log === 'function') {
      window.log('🔗 Requesting Deriv Options OTP WebSocket...', 'SYSTEM');
    }

    let wsUrl;
    try {
      wsUrl = await window.getAuthenticatedDerivWebSocketUrl();
    } catch (error) {
      window.isConnecting = false;
      if (typeof window.updateConnectionStatus === 'function') window.updateConnectionStatus();
      if (typeof window.log === 'function') window.log(`❌ ${error.message}`, 'ERROR');
      if (typeof window.updateTradeStatus === 'function') {
        window.updateTradeStatus('ERROR', error.message, 'Reconnect from the homepage', 'loss');
      }
      return;
    }

    window.ws = new WebSocket(wsUrl);

    window.ws.onopen = function () {
      window.isConnecting = false;

      if (typeof window.resetReconnectionAttempts === 'function') {
        window.resetReconnectionAttempts();
      }
      if (typeof window.log === 'function') {
        window.log('✅ Authenticated Deriv Options WebSocket connected', 'SYSTEM');
      }
      if (typeof window.updateConnectionStatus === 'function') {
        window.updateConnectionStatus();
      }

      const symbolEl = document.getElementById('symbol');
      const symbol = symbolEl ? symbolEl.value : 'R_100';

      if (typeof window.subscribeToTicks === 'function') {
        window.subscribeToTicks(symbol);
      } else if (typeof window.sendRequest === 'function') {
        window.sendRequest({
          ticks: symbol,
          subscribe: 1,
          req_id: typeof window.getNextReqId === 'function' ? window.getNextReqId() : 1
        });
      }

      if (typeof window.subscribeToBalance === 'function') {
        window.subscribeToBalance();
      } else if (typeof window.sendRequest === 'function') {
        window.sendRequest({
          balance: 1,
          subscribe: 1,
          req_id: typeof window.getNextReqId === 'function' ? window.getNextReqId() : 2
        });
      }

      if (window.digitIntelligenceEngine?.enabled &&
          typeof window.requestWarmupTicks === 'function') {
        setTimeout(() => window.requestWarmupTicks(), 500);
      }
    };

    window.ws.onmessage = function (event) {
      try {
        const data = JSON.parse(event.data);

        if (data.msg_type === 'tick') {
          // NEW: expose the complete tick to shadow research BEFORE bot processing.
          emitResearchTick(data.tick);

          if (typeof window.handleTick === 'function') {
            window.handleTick(data.tick);
          }
          return;
        }

        if (typeof window.handleAPIResponse === 'function') {
          window.handleAPIResponse(data);
        }
      } catch (error) {
        console.error('Deriv WebSocket message error:', error);
        if (typeof window.log === 'function') {
          window.log('❌ Error parsing Deriv WebSocket message', 'ERROR');
        }
      }
    };

    window.ws.onclose = function () {
      window.isConnecting = false;
      if (typeof window.updateConnectionStatus === 'function') window.updateConnectionStatus();

      if (typeof window.log === 'function') {
        window.log('🔌 Deriv WebSocket disconnected', 'SYSTEM');
      }

      if (window.isBotRunning &&
          window.networkRecoveryEnabled &&
          typeof window.attemptNetworkRecovery === 'function') {
        window.attemptNetworkRecovery();
      }
    };

    window.ws.onerror = function (error) {
      console.error('Deriv WebSocket error:', error);
      if (typeof window.log === 'function') {
        window.log('❌ Deriv WebSocket connection error', 'ERROR');
      }
      if (typeof window.updateTradeStatus === 'function') {
        window.updateTradeStatus(
          'ERROR',
          'WebSocket connection failed',
          'Check OAuth account and API routes',
          'loss'
        );
      }
    };
  };

  async function autoConnectForWarmup() {
    const authenticated =
      localStorage.getItem('bot_authenticated') === 'true' &&
      !!(localStorage.getItem('active_token') || localStorage.getItem('derivToken')) &&
      !!(localStorage.getItem('active_account') || localStorage.getItem('derivAccount'));

    if (!authenticated) {
      console.warn('Deriv bridge: OAuth session/account not available; skipping auto-connect.');
      return;
    }

    if (window.ws &&
        (window.ws.readyState === WebSocket.OPEN ||
         window.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    if (typeof window.log === 'function') {
      window.log('🔐 OAuth session found - connecting market data for AI warm-up...', 'SYSTEM');
    }

    try {
      await window.connectWebSocket();
    } catch (error) {
      console.error('Automatic Deriv warm-up connection failed:', error);
      if (typeof window.log === 'function') {
        window.log(`❌ Automatic connection failed: ${error.message}`, 'ERROR');
      }
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      setTimeout(autoConnectForWarmup, 400);
    });
  } else {
    setTimeout(autoConnectForWarmup, 400);
  }

  console.log('✅ Deriv live connection bridge v3 loaded (Tick DNA event enabled)');
})();
