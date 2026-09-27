
# DigitMatchStar v6.1.1 — Capture Button Fix

Root cause:
The previous v6.0/v6.1 recorder still rendered the "Prepare + record" button, but the `enableCapture()` and `startSessionRecorder()` functions had been accidentally removed.

Fixed:
- restored `enableCapture()`
- restored `startSessionRecorder()`
- retained actual Trade-1 target locking
- retained trade-gated target-vs-last-digit comparison
- retained final P/L synchronization
- retained WebM integrity checks
- retained one-tap Telegram Approve / Reject callback buttons
- JavaScript syntax validated with `node --check`
- Python worker syntax validated

Upload/replace:
- bot-obfuscated.html
- screen-recorder-safe-v5-2.js
- media-worker/app.py

The media worker remains v6.1 for callback moderation.
