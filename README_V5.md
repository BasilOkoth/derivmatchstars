# DigitMatchStar Premium Guided Video v5.0

Files
- `bot-obfuscated.html` — exact V18 timing-fixed production bot, only the recorder loader is changed to `/screen-recorder-safe-v5.js`.
- `screen-recorder-safe-v5.js` — read-only recorder + event collector.
- `media-worker/app.py` — new 1080x1920 guided compositor.
- `media-worker/main.py`
- `media-worker/requirements.txt`

## Recorder behavior
The recorder:
- does not replace or wrap trading functions;
- visually zooms the page to 88% and scrolls to the execution-mode/trading controls before recording;
- records the full browser tab with tab audio;
- hides its own control panel before MediaRecorder starts;
- observes DOM/window state only;
- sends a `captureEvents` timeline with target digit, trade count, stake, P/L, current digit and bot-status changes.

## Guided video behavior
The worker:
- preserves the complete raw browser viewport — no aggressive crop;
- places it inside a uniform browser-style screen template;
- shows guided states below the screen;
- animates trade progress;
- shows live P/L, current stake and trade count from captured event snapshots;
- includes a short focus replay;
- keeps the real tab audio;
- sends the finished video privately to Telegram.

## Render
Root Directory: `media-worker`
Build Command: `pip install -r requirements.txt`
Start Command: `uvicorn app:app --host 0.0.0.0 --port $PORT`

Recommended for this v5 1080p compositor: 2 GB RAM Render plan.

Expected health response:
`"version": "premium-guided-v5.0"`
