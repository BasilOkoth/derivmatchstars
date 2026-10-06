DigitMatchStar server fetch fix

ROOT CAUSE FOUND
The new full app/engine.py removed the old Target Attraction API methods, but the
repository still had the old app/main.py calling:
- engine.target_attraction_status(...)
- engine.export_target_attraction(...)
- engine.set_target_digit(...)

That makes the frontend/backend pair incompatible and can break the /sessions
flow used by START BOT.

This package contains a FULL replacement app/main.py, not a patch.

It also:
- exposes digit_score in /sessions
- exposes recycle_after=3
- removes execution dependency on TAE methods
- keeps the old /sessions/{sid}/tae/export URL as a harmless compatibility endpoint
- allows both https://digitmatchstar.com and https://www.digitmatchstar.com in CORS
- validates Max Trades >= 1
- defaults Max Trades to 15

UPLOAD
Replace:
    app/main.py

Then redeploy/restart the Render API.

CHECK
Open:
    https://digitmatchstar-api.onrender.com/health

Expected:
    "ok": true
    version: "3.0.0-digit-score-recycle3"

Then refresh DigitMatchStar and START BOT again.
