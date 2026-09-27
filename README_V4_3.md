# DigitMatchStar Premium Video v4.3

This release fixes the problems observed in the actual raw capture.

## What was wrong

- The v4.2 capture panel was visible inside the recorded bot screen.
- It was too large and fixed in one place.
- Recording began only around the cycle, so setup/configuration was not intentionally captured.
- `audio:false` meant the WebM contained no tab audio.
- The premium upload failed with `Failed to fetch`, consistent with the browser being unable to reach the Render cross-origin endpoint.
- CORS existed only in `main.py`, so Render could bypass it if the Start Command was still `uvicorn app:app`.

## v4.3 fixes

### Browser recorder
- Small 218px control.
- Drag it anywhere before capture.
- After clicking Enable, it requests THIS TAB + TAB AUDIO.
- If no audio track is granted, it refuses to make a silent recording and tells you to enable Share tab audio.
- Recording starts immediately after permission, so configuration/settings before the cycle are included.
- The entire control panel is hidden BEFORE MediaRecorder starts. It is therefore not in the footage.
- The bot's trading functions are never patched or replaced.
- When the observed cycle ends, the recorder leaves about 1.8 seconds of result screen/sound before stopping.

### Render worker
- CORS is now directly inside `media-worker/app.py`.
- Therefore BOTH of these Render start commands work:
  - `uvicorn app:app --host 0.0.0.0 --port $PORT`
  - `uvicorn main:app --host 0.0.0.0 --port $PORT`
- The worker detects whether the raw WebM contains an audio track.
- If audio exists, actual bot/tab audio is mixed into the premium final video alongside subtle premium sound design.
- `/health` now reports v4.3, CORS and whether Telegram configuration is present (without exposing secrets).

## Files to upload

Repository root:
- `bot-obfuscated.html`
- `screen-recorder-safe-v4-3.js`

Render worker:
- `media-worker/app.py`
- `media-worker/main.py`
- `media-worker/requirements.txt`

## Render settings

Root Directory:
`media-worker`

Build:
`pip install -r requirements.txt`

Start:
`uvicorn app:app --host 0.0.0.0 --port $PORT`

Environment:
- MEDIA_WORKER_SECRET
- TELEGRAM_BOT_TOKEN
- TELEGRAM_ADMIN_CHAT_ID

## Vercel environment
- MEDIA_WORKER_URL = your exact HTTPS Render service base URL
- MEDIA_WORKER_SECRET = EXACT same value as Render
- TELEGRAM_PUBLISH_ACCOUNT_IDS = the Deriv account ID(s) allowed to publish

Redeploy Vercel after any environment variable change.

## Test

1. Open DigitMatchStar on desktop Chrome/Edge.
2. You should see a small PREMIUM CAPTURE box.
3. Drag it if desired.
4. Click `Enable + record setup`.
5. In Chrome choose the DigitMatchStar **tab**, not window/screen.
6. Turn on **Share tab audio**.
7. Click Share.
8. The control disappears completely from the captured page.
9. Adjust your bot settings. Those actions are now being recorded.
10. Start the bot.
11. Let one cycle finish.
12. The recorder stops after the final result is visible/heard.
13. The control reappears while the premium video uploads.
14. Final 1080x1920 MP4 should arrive in your private Telegram.

## Health test

Open:

`https://YOUR-RENDER-SERVICE.onrender.com/health`

Expected shape:

```json
{
  "ok": true,
  "version": "ultra-premium-live-v4.3",
  "cors": true,
  "telegramConfigured": true
}
```

If `telegramConfigured` is false, fix Render's Telegram environment variables.
