# DigitMatchStar Telegram + TikTok-ready Publisher

## Files
- `bot-obfuscated.html` — your current bot with automatic cycle publishing added.
- `api/publish-cycle.js` — Vercel endpoint that verifies the Deriv account and publishes official results.
- `media-worker/` — optional Render service that creates 1080x1920 MP4 result videos.

## Vercel environment variables
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID=@digitmatchstar
- TELEGRAM_PUBLISH_ACCOUNT_IDS=<your authorized Deriv account IDs, comma separated>
- DIGITMATCHSTAR_URL=https://www.digitmatchstar.com
- MEDIA_WORKER_URL=<Render worker URL>  (optional for video)
- MEDIA_WORKER_SECRET=<long random secret>  (optional for video)

## Render media-worker environment variables
- MEDIA_WORKER_SECRET=<same as Vercel>
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID=@digitmatchstar
- TELEGRAM_ADMIN_CHAT_ID=<your private Telegram chat id> (optional)

## What it does
Every finalized WIN or STOPPED cycle is sent to `/api/publish-cycle`.
The server verifies the account with Deriv and determines DEMO or REAL itself.
Only account IDs in TELEGRAM_PUBLISH_ACCOUNT_IDS can publish to the official channel.

If the media worker is configured, it:
1. creates a branded 9:16 result MP4 and posts it to the Telegram channel;
2. optionally creates a clean TikTok-ready 9:16 MP4 and sends it privately to you on Telegram.

If the media worker is unavailable, a professional text result is posted instead.

Direct TikTok posting is intentionally not enabled in this package yet. The official TikTok Content Posting API requires an approved app, approved `video.publish` scope, creator authorization and audit for public visibility. The generated TikTok-ready MP4 can be uploaded manually immediately.
