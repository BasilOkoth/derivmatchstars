DigitMatchStar V1.7 — Telegram WIN Preview Restore

Files to upload:
1. bot.html
2. bot-obfuscated.html
3. api/publish-cycle.js

Why Telegram stopped:
The secure OAuth build intentionally stopped storing the raw Deriv token in the
browser, but the old /api/publish-cycle endpoint still required that raw token.
Therefore completed cycles reached the publisher but were skipped with a missing
token condition.

V1.7 fix:
- bot publisher now sends the DigitMatchStar platform JWT.
- /api/publish-cycle verifies that JWT against:
  https://digitmatchstar-api.onrender.com/sessions
- It confirms that account_id belongs to the authenticated DigitMatchStar user.
- TELEGRAM_PUBLISH_ACCOUNT_IDS allow-list remains enforced.
- Telegram remains APPROVAL-FIRST: private preview -> Approve / Reject -> public channel.
- Failed sends are NOT marked as sent, so they can be retried.
- Successful previews are deduplicated by cycle id.
- SAFE-TICK V1.5, fast recovery re-ranking, and deterministic sound are unchanged.

Optional Vercel environment variable:
DMS_API_URL=https://digitmatchstar-api.onrender.com

The code already has this URL as its fallback, so the env variable is optional.

Security:
No raw Deriv access token is reintroduced into the browser.
