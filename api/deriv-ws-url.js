export default async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({
      error: "Method not allowed"
    });
  }

  try {
    const { token, account_id, app_id } = req.body || {};

    if (!token) {
      return res.status(400).json({
        error: "Missing Deriv access token"
      });
    }

    if (!account_id) {
      return res.status(400).json({
        error: "Missing Deriv account_id"
      });
    }

    const derivAppId = process.env.DERIV_APP_ID || app_id;

    if (!derivAppId) {
      return res.status(400).json({
        error: "Missing Deriv app ID. Set DERIV_APP_ID in Vercel or send app_id from the bot."
      });
    }

    const endpoint = `https://api.derivws.com/trading/v1/options/accounts/${encodeURIComponent(account_id)}/otp`;

    const response = await fetch(endpoint, {
      method: "POST",
      headers: {
        "Deriv-App-ID": derivAppId,
        "Authorization": `Bearer ${token}`
      }
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
        `Failed to get WebSocket OTP URL. HTTP ${response.status}`;

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
      error: error.message || "Server error"
    });
  }
}
