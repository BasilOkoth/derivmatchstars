"""
DigitMatchStar application package.

Important:
- Runtime trading/scoring logic lives in app.engine.
- Deriv WebSocket behavior lives in app.deriv_ws.
- Do not monkey-patch MultiUserEngine or DerivWS here.

Older recovery/timeline/score-gate monkey patches were removed because they
overrode the current direct-buy engine at import time and caused signature
mismatches and stale feed recovery errors.
"""
