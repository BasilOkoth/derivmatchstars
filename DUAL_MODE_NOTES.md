# DigitMatchStar top-ranked digit in DEMO and REAL

DEMO continues the top-ranked V1 selection without a score-9 threshold, using the existing automated demo engine.

REAL already supports explicit individual trade approvals through `/real-manual/sessions/{sid}/quote` and `/real-manual/sessions/{sid}/confirm`. The REAL quote endpoint now selects the **current server-side V1 rank #1** automatically when `digit` is omitted (e.g. `{"stake": 1.00}`). If a `digit` is supplied it must match the current V1 #1. It rejects stale ticks and unsynchronized rankings. It retains the one-time confirmation token, stake cap, durable DB buy claim, and no-retry behavior for uncertain purchases.

REAL trading is **not** unattended automation: each purchase still needs confirmation. The bot's normal START action is DEMO-oriented. No automatic REAL loss-recovery sequence is enabled. Avoid REAL trading before testing end-to-end, including backend quote+confirm and UI compatibility.

Trade outcomes and prediction accuracy are not guaranteed; score rank is not a validated probability.
