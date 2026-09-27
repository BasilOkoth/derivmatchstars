
# DigitMatchStar Premium v6.1 — One-Tap Telegram Approve / Reject

The moderation buttons now use Telegram `callback_data`.

Result:
- Tap ✅ Approve -> video posts directly to MAIN_CHANNEL_CHAT_ID.
- Tap ❌ Reject -> preview is rejected.
- No browser opens.
- No long signed URL appears.
- No second click is needed.

## One required Telegram setup

Telegram must send callback queries to the media worker webhook.

After deploying v6.1, open this once in a browser, replacing BOT_TOKEN:

https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=https://digitmatchstar-media-worker.onrender.com/telegram-webhook

Do NOT paste your token into chat.

You can verify the webhook with:

https://api.telegram.org/bot<BOT_TOKEN>/getWebhookInfo

Expected webhook URL:
https://digitmatchstar-media-worker.onrender.com/telegram-webhook

Existing Render env vars remain:
- TELEGRAM_BOT_TOKEN
- TELEGRAM_ADMIN_CHAT_ID
- MAIN_CHANNEL_CHAT_ID
- MEDIA_WORKER_SECRET
- PUBLIC_BASE_URL=https://digitmatchstar-media-worker.onrender.com
- PUBLIC_WEBSITE_URL=https://www.digitmatchstar.com

Expected health version:
premium-guided-v6.1
