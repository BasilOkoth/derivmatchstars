DigitMatchStar Telegram Settlement Confirmation Fix v3.1

ROOT CAUSE
The server settlement was available, but bot.html's matchstarPublisher stripped:
- settlementConfirmed
- settlementContractId
- cyclePnlAuthoritative

before sending the payload to /api/publish-cycle.

At the same time, the old cyclePerformance recorder was still independently
publishing WIN cycles without any settlement metadata.

FIX
- settlement metadata is now forwarded end-to-end
- old cycle recorder no longer publishes WINs
- matchstarPublisher refuses any unconfirmed WIN
- /api/publish-cycle holds unconfirmed WIN payloads with HTTP 202
- Telegram no longer prints "Settlement confirmation unavailable"
- only the exact Deriv-settled winning contract can produce a WIN post

FULL FILES INCLUDED
- bot.html
- api/publish-cycle.js
- app/engine.py
- app/main.py
- app/digit_score.py
- app/deriv_ws.py

Upload the complete files to the same repository paths and redeploy.
