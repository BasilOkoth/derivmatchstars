# DigitMatchStar Media Worker v4.4

This fixes the Render HTTP 500 seen at /compose-live.

Root causes reproduced with the same imageio-ffmpeg 7.0.2 binary:
1. FFmpeg 7 rejects fade duration values written as `.15` and `.18`.
2. The bundled static FFmpeg does not provide the `drawtext` filter.

Fixes:
- Fade durations now use `0.15` and `0.18`.
- All video text/HUD rendering is done with Pillow PNG overlays.
- FFmpeg still handles scaling, crop, overlay, animated progress boxes, concat, H.264 and audio.
- FFmpeg stderr is captured and printed to Render logs on future failures.
- Tested successfully against the actual uploaded DigitMatchStar WebM.

Render:
Root Directory: media-worker
Build: pip install -r requirements.txt
Start: uvicorn app:app --host 0.0.0.0 --port $PORT

Replace media-worker/app.py with this v4.4 file.
main.py may remain as provided.
