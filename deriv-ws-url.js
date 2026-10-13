// Vercel Serverless Function: /api/deriv-ws-url
// Gets a short-lived authenticated Deriv Options WebSocket URL via the OTP endpoint.

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return res.status(405).json({ error: 'method_not_allowed' });
  }

  try {
    const { token, account_id, auth_method, app_id } = req.body || {};

    if (!token) {
      return res.status(400).json({ error: 'Missing Deriv access token' });
    }

    if (!account_id) {
      return res.status(400).json({ error: 'Missing Deriv account_id' });
    }

    const headers = {
      'Authorization': `Bearer ${token}`
    };

    // Only PAT authentication needs Deriv-App-ID.
    if (String(auth_method || '').toLowerCase() === 'pat') {
      const finalAppId = process.env.DERIV_APP_ID || app_id;
      if (!finalAppId) {
        return res.status(400).json({
          error: 'PAT authentication requires DERIV_APP_ID'
        });
      }
      headers['Deriv-App-ID'] = finalAppId;
    }

    const endpoint =
      `https://api.derivws.com/trading/v1/options/accounts/${encodeURIComponent(account_id)}/otp`;

    const response = await fetch(endpoint, {
      method: 'POST',
      headers
    });

    const data = await response.json().catch(() => ({}));

    const websocketUrl =
      data?.data?.url ||
      data?.data?.websocket_url ||
      data?.url ||
      data?.websocket_url;

    if (!response.ok || !websocketUrl) {
      const errorMessage =
        data?.errors?.[0]?.message ||
        data?.error?.message ||
        data?.message ||
        `Failed to get authenticated WebSocket URL. HTTP ${response.status}`;

      return res.status(response.status || 500).json({
        error: errorMessage,
        details: data
      });
    }

    return res.status(200).json({
      websocket_url: websocketUrl
    });
  } catch (error) {
    return res.status(500).json({
      error: error.message || 'Server error'
    });
  }
};
