# DigitMatchStar Media Worker v4.6 Low-Memory

Designed for Render instances with a 512 MB RAM limit.

Key changes
- Keeps 1080x1920 output.
- H.264 uses veryfast preset, CRF 21, 1 thread, ref=1, bframes=0.
- Concat stage uses stream copy instead of a second full H.264 re-encode.
- Soundtrack uses compact int16 storage instead of Python float objects.
- Soundtrack writes WAV in chunks.
- Major FFmpeg stages are still sequential and logged.
- Final video audio mix copies the already-encoded video stream.
- Same CORS, ticket, Telegram, progress rail, focus replay and bot-tab audio behavior.

Render
Root Directory: media-worker
Build: pip install -r requirements.txt
Start: uvicorn app:app --host 0.0.0.0 --port $PORT
