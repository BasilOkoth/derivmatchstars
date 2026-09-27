# DigitMatchStar Video Fix v4.2

This fixes the live-video path without changing trading logic.

## Fixes included

1. Safe observer now understands the real production V17 structure:
   `cyclePerformance.historyBySymbol`.
2. It reads the same account/token storage keys used by DigitMatchStar.
3. It remains read-only and never patches `startCycle`, `completeCycle`,
   WebSocket handlers, purchase functions, stake progression, or risk logic.
4. `media-worker/main.py` adds CORS for:
   - https://www.digitmatchstar.com
   - https://digitmatchstar.com

## Production page

The production bot is `bot-obfuscated.html`.

Load the safe observer immediately before `</body>`:

    <script src="/screen-recorder-safe-v4-2.js"></script>

Do not load old v3/v4 recorder scripts at the same time.

## Render

Keep:
- Root Directory: media-worker
- Build: pip install -r requirements.txt

CHANGE the Start Command to:

    uvicorn main:app --host 0.0.0.0 --port $PORT

`main.py` imports the existing `app.py` compositor and adds CORS around it.

## Vercel variables

Required:
- MEDIA_WORKER_URL
- MEDIA_WORKER_SECRET
- TELEGRAM_PUBLISH_ACCOUNT_IDS

`TELEGRAM_PUBLISH_ACCOUNT_IDS` must contain the actual Deriv account ID being used.

## Render variables

Required:
- MEDIA_WORKER_SECRET
- TELEGRAM_BOT_TOKEN
- TELEGRAM_ADMIN_CHAT_ID

The MEDIA_WORKER_SECRET must be exactly the same in Vercel and Render.

## Test sequence

Use desktop Chrome or Edge.

1. Open production bot.
2. Confirm the SAFE LIVE CAPTURE panel appears.
3. Click Enable live capture.
4. Choose the DigitMatchStar tab.
5. Confirm status says Ready.
6. Start a cycle.
7. Status should change to RECORDING.
8. After cycle completion, raw preview appears.
9. Then upload status appears.
10. Final premium MP4 should arrive in private Telegram.

If raw preview appears but Telegram does not:
- recorder works
- investigate ticket/Render/Telegram only.

If the panel does not appear:
- the production HTML is not loading `screen-recorder-safe-v4-2.js`.
