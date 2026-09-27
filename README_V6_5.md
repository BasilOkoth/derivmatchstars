
# DigitMatchStar Premium v6.5

## Admin-only Premium Capture

The recorder is now owner/admin-only.

The browser first calls:
`/api/capture-access`

That endpoint:
- verifies the active Deriv bearer token
- verifies the selected Deriv account
- checks the existing `TELEGRAM_PUBLISH_ACCOUNT_IDS` allow-list

Unauthorized users:
- do not see the Premium Capture panel
- cannot enable recording through the exposed JS helper
- cannot obtain a valid live-capture upload ticket

The capture ticket also carries:
- `kind: "capture"`
- `captureAdmin: true`

The Render worker rejects any upload ticket that does not contain the signed admin claim.

## One-tap Telegram moderation

Buttons are attached directly to the VIDEO preview:

`✅ Share`  `❌ Reject`

Callback values now exactly match the existing site webhook:
- `dms:approve`
- `dms:reject`

Expected Telegram webhook:
`https://www.digitmatchstar.com/api/telegram-approval`

When Share is tapped:
- the exact preview video is copied to the public channel
- no browser opens
- no long code appears
- no second click

When Reject is tapped:
- nothing is published
- the buttons are removed

The Render worker no longer overrides the Telegram webhook.

## Deploy

Main DigitMatchStar / Vercel:
- `screen-recorder-safe-v5-2.js`
- `api/capture-access.js`
- `api/live-capture-ticket.js`
- `api/telegram-approval.js`
- `bot-obfuscated.html` is included for a complete package

Render media worker:
- `media-worker/app.py`

No `.env` file was read, changed, or included.

Expected worker health:
`premium-guided-v6.5`
