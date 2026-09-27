
# DigitMatchStar Premium v5.6 — Capture Integrity Fix

Render showed:
`EBML header parsing failed`

That means the uploaded browser recording was not a valid WebM before FFmpeg started.

Fixes:
- explicit MediaRecorder `requestData()` flush before stop
- short wait before recorder stop
- browser-side WebM EBML header validation
- invalid captures are blocked before upload
- worker-side WebM header validation before FFmpeg
- worker logs capture size, filename, and content type
- v5.5 large trading screen and Telegram Approve/Reject buttons retained
- final CTA remains the last slide

Expected health version:
premium-guided-v5.6
