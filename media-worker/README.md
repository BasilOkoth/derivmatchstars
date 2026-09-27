# DigitMatchStar Media Worker v4.5

This release is specifically for the Render FFmpeg build.

Confirmed fixes:
- no FFmpeg `drawtext` filter anywhere
- fade durations use `0.15` and `0.18`
- FFmpeg errors are printed to Render logs with a stage name
- trade progress animation remains via `drawbox`
- focus replay remains
- bot-tab audio + premium audio mixing remains
- premium 1080x1920 output remains

Replace `media-worker/app.py` with this file and redeploy Render.

Health endpoint should report:
`ultra-premium-live-v4.5`
