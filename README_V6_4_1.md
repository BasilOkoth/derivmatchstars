
# DigitMatchStar Premium v6.4.1 — Automatic Telegram Webhook Repair

Root cause addressed:
Telegram callback buttons do nothing unless Telegram has an active webhook
pointing to the Render media worker.

v6.4.1:
- automatically calls Telegram setWebhook on worker startup
- retries webhook registration on startup
- checks getWebhookInfo
- `/health` now reports:
  - telegramWebhookConfigured
  - telegramWebhookUrl
  - telegramWebhookPendingUpdates
  - telegramWebhookLastError
- logs every webhook delivery
- keeps one-tap Approve / Reject callback buttons
- keeps compatibility with older callback formats
- keeps all v6.3 video UI behavior

After deploying, open:
https://digitmatchstar-media-worker.onrender.com/health

The important field must be:
"telegramWebhookConfigured": true

Expected version:
premium-guided-v6.4.1
