// Vercel Serverless Function: /api/deriv-accounts
// Returns Deriv Options accounts for an OAuth2 or PAT bearer token.

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return res.status(405).json({ error: 'method_not_allowed' });
  }

  try {
    const { token, auth_method, app_id } = req.body || {};

    if (!token) {
      return res.status(400).json({ error: 'Missing Deriv access token' });
    }

    const headers = {
      'Authorization': `Bearer ${token}`
    };

    // Deriv-App-ID is required for PAT authentication, not OAuth2.
    if (String(auth_method || '').toLowerCase() === 'pat') {
      const finalAppId = process.env.DERIV_APP_ID || app_id;
      if (!finalAppId) {
        return res.status(400).json({
          error: 'PAT authentication requires DERIV_APP_ID'
        });
      }
      headers['Deriv-App-ID'] = finalAppId;
    }

    const response = await fetch(
      'https://api.derivws.com/trading/v1/options/accounts',
      { method: 'GET', headers }
    );

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      const message =
        data?.errors?.[0]?.message ||
        data?.error?.message ||
        data?.message ||
        `Failed to load Deriv Options accounts. HTTP ${response.status}`;

      return res.status(response.status).json({
        error: message,
        details: data
      });
    }

    const accounts = Array.isArray(data?.data)
      ? data.data
      : (data?.data ? [data.data] : []);

    return res.status(200).json({
      accounts,
      meta: data?.meta || null
    });
  } catch (error) {
    return res.status(500).json({
      error: error.message || 'Server error'
    });
  }
};
