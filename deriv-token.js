// Vercel Serverless Function: /api/deriv-token
// Exchanges Deriv OAuth2 PKCE authorization code for an access token.
// Deriv requires this exchange to happen server-side, not inside the browser.

module.exports = async function handler(req, res) {
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return res.status(405).json({ error: 'method_not_allowed' });
  }

  try {
    const { code, code_verifier, redirect_uri, client_id } = req.body || {};

    const finalClientId = process.env.DERIV_CLIENT_ID || client_id;
    const clientSecret = process.env.DERIV_CLIENT_SECRET || '';

    if (!code || !code_verifier || !redirect_uri || !finalClientId) {
      return res.status(400).json({
        error: 'missing_required_fields',
        error_description: 'code, code_verifier, redirect_uri and client_id are required.'
      });
    }

    const body = new URLSearchParams({
      grant_type: 'authorization_code',
      client_id: finalClientId,
      code,
      code_verifier,
      redirect_uri
    });

    // Only include client_secret if Deriv issued one for your app and you set it in Vercel env vars.
    if (clientSecret) {
      body.set('client_secret', clientSecret);
    }

    const tokenResponse = await fetch('https://auth.deriv.com/oauth2/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString()
    });

    const text = await tokenResponse.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch (_) {
      data = { raw_response: text };
    }

    if (!tokenResponse.ok) {
      return res.status(tokenResponse.status).json({
        error: data.error || 'token_exchange_failed',
        error_description: data.error_description || data.message || text
      });
    }

    return res.status(200).json(data);
  } catch (error) {
    return res.status(500).json({
      error: 'server_error',
      error_description: error.message
    });
  }
};
