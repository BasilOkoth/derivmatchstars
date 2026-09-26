# DigitMatchStar — Approval-First Telegram Publishing

This version does NOT publish completed cycles directly to the public channel.

Flow:
1. A cycle completes in DigitMatchStar.
2. `/api/publish-cycle.js` verifies the Deriv account and creates the result message.
3. The result is sent privately to `TELEGRAM_ADMIN_CHAT_ID`.
4. The private preview contains:
   - ✅ APPROVE & PUBLISH
   - ❌ REJECT
5. Only when an authorized approver taps APPROVE does `/api/telegram-approval.js` copy the message to `TELEGRAM_CHAT_ID`.
6. REJECT publishes nothing.

## Vercel environment variables

Keep:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID=-1003120805853`
- `TELEGRAM_PUBLISH_ACCOUNT_IDS=...`
- `DIGITMATCHSTAR_URL=https://www.digitmatchstar.com`

Add:
- `TELEGRAM_ADMIN_CHAT_ID=<your private Telegram chat ID>`
- `TELEGRAM_APPROVER_USER_IDS=<your Telegram numeric user ID>`
- `TELEGRAM_WEBHOOK_SECRET=<a long random secret you create>`

`TELEGRAM_APPROVER_USER_IDS` may contain several numeric user IDs separated by commas.

Do not put any bot token or webhook secret in browser code or GitHub.

## Set the Telegram webhook

After deployment, set the bot webhook to:

`https://www.digitmatchstar.com/api/telegram-approval`

For stronger protection, configure the webhook with the same secret stored in `TELEGRAM_WEBHOOK_SECRET`.

Example pattern (replace placeholders locally; do not paste your bot token into public code):

`https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=https%3A%2F%2Fwww.digitmatchstar.com%2Fapi%2Ftelegram-approval&secret_token=<YOUR_WEBHOOK_SECRET>`

Telegram will send button callbacks to the Vercel approval endpoint.

## Important

The approver must first open a private chat with the bot and press Start, otherwise the bot cannot send private approval previews.

This package uses text approval previews. The previous media worker is intentionally not called before approval, so a video cannot accidentally bypass owner review.
