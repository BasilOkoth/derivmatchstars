/*
 * DigitMatchStars - Deriv Options live connection bridge
 *
 * IMPORTANT:
 * Load this file AFTER the bot's existing inline JavaScript:
 *
 *   <script src="/deriv-live-bridge.js"></script>
 *
 * It replaces the old post-OTP "authorize" step.
 * The OTP WebSocket URL is already authenticated, so the bot can subscribe
 * to balance/ticks immediately after ws.onopen.
 */

(function () {
  'use strict';

  function authMethod() {
    return localStorage.getItem('auth_method') || 'oauth2_pkce';
  }

  // Replace the existing helper so OAuth does not send an app_id unnecessarily.
  window.getAuthenticatedDerivWebSocketUrl = async function () {
    const token = window.getStoredDerivToken
      ? window.getStoredDerivToken()
      : (localStorage.getItem('active_token') || localStorage.getItem('derivToken'));

    const accountId = window.getStoredDerivAccount
      ? window.getStoredDerivAccount()
      : (localStorage.getItem('active_account') || localStorage.getItem('derivAccount'));

    if (!token) throw new Error('No Deriv access token found. Please login again.');
    if (!accountId) throw new Error('No Deriv Options account ID found. Please login again.');

    const payload = {
      token,
      account_id: accountId,
      auth_method: authMethod()
    };

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

  // Replace the bot's legacy/partial connection logic.
  window.connectWebSocket = async function () {
    if (window.ws) {
      try { window.ws.close(); } catch (_) {}
      window.ws = null;
    }

    window.isConnecting = true;
    if (typeof window.updateConnectionStatus === 'function') {
      window.updateConnectionStatus();
    }

    if (typeof window.log === 'function') {
      window.log('🔗 Requesting Deriv Options OTP WebSocket...', 'SYSTEM');
    }

    let wsUrl;
    try {
      wsUrl = await window.getAuthenticatedDerivWebSocketUrl();
    } catch (error) {
      window.isConnecting = false;
      if (typeof window.updateConnectionStatus === 'function') {
        window.updateConnectionStatus();
      }
      if (typeof window.log === 'function') {
        window.log(`❌ ${error.message}`, 'ERROR');
      }
      if (typeof window.updateTradeStatus === 'function') {
        window.updateTradeStatus(
          'ERROR',
          error.message,
          'Reconnect from the homepage',
          'loss'
        );
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

      // IMPORTANT:
      // Do NOT send {authorize: token}. The OTP URL is already authenticated.
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

        // Existing bot handler understands tick/history/proposal/buy/balance.
        if (data.msg_type === 'tick' && typeof window.handleTick === 'function') {
          window.handleTick(data.tick);
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

      if (typeof window.updateConnectionStatus === 'function') {
        window.updateConnectionStatus();
      }

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


  // ------------------------------------------------------------
  // IMPORTANT: connect independently of the START BOT button.
  //
  // The original bot blocks START while AI confidence is 0%.
  // But confidence cannot increase until the engine receives its
  // warm-up history. That created a deadlock:
  //
  //   START blocked -> no WebSocket -> no history -> 0% forever.
  //
  // Connect as soon as the authenticated bot page is ready. This
  // only opens the market data/account connection; it does NOT
  // start automated trading.
  // ------------------------------------------------------------
  async function autoConnectForWarmup() {
    const authenticated =
      localStorage.getItem('bot_authenticated') === 'true' &&
      !!(localStorage.getItem('active_token') || localStorage.getItem('derivToken')) &&
      !!(localStorage.getItem('active_account') || localStorage.getItem('derivAccount'));

    if (!authenticated) {
      console.warn('Deriv bridge: OAuth session/account not available; skipping auto-connect.');
      return;
    }

    // Do not create a second socket if one is already connected/connecting.
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

  // Wait until the original bot script has finished initializing.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      setTimeout(autoConnectForWarmup, 400);
    });
  } else {
    setTimeout(autoConnectForWarmup, 400);
  }

  console.log('✅ Deriv live connection bridge v2 loaded (auto-connect warm-up enabled)');
})();
