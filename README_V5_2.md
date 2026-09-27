
# DigitMatchStar Premium Guided Video v5.2

This version improves:
- clearer / closer screen presentation
- larger screen template area
- slightly stronger raw capture settings (0.94 zoom, 12 Mbps, 2560x1440 ideal)
- sharper rendered output (CRF 18 + unsharp filter)
- approve / reject moderation links
- CTA outro with safer, non-promissory TikTok-style wording
- risk-aware phrasing to reduce moderation risk

## Files
- `bot-obfuscated.html`
- `screen-recorder-safe-v5-2.js`
- `media-worker/app.py`
- `media-worker/main.py`
- `media-worker/requirements.txt`

## Important env vars
Existing:
- `MEDIA_WORKER_SECRET`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ADMIN_CHAT_ID`

New / recommended:
- `PUBLIC_BASE_URL=https://digitmatchstar-media-worker.onrender.com`
- `MAIN_CHANNEL_CHAT_ID=<telegram channel or chat id for approved videos>`
- `CTA_LINE_1=Follow for more guided trading content`
- `CTA_LINE_2=Watch, learn, then demo first`
- `CTA_LINE_3=Educational content only · Trade responsibly`

## Approval flow
1. Worker sends the preview to the admin chat.
2. Worker sends two moderation links:
   - approve
   - reject
3. Approve posts the video to `MAIN_CHANNEL_CHAT_ID`.
4. Reject marks it rejected and it is not posted.

## Render
Root Directory: `media-worker`
Build: `pip install -r requirements.txt`
Start: `uvicorn app:app --host 0.0.0.0 --port $PORT`

## TikTok safety note
No one can guarantee TikTok will never take a video down. This version reduces risk by:
- avoiding earnings guarantees,
- using educational / risk-aware CTA,
- keeping claims non-promissory,
- including a trading-risk disclaimer.
