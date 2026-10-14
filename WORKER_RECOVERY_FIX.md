# Worker execution recovery correction

The backend worker can lose its `fast_contracts` in-memory ownership when Render restarts, while persisted session `current_trade` remains >0. The corrected `app/engine.py` reconstructs the previous purchase from `TradeLog`, waits for authoritative settlement, and only then allows continuation with the latest fresh V1 top-ranked digit. The stake is derived from the recorded previous stake instead of repeatedly multiplying the displayed next stake.

For an OPEN previous trade, the worker attempts settlement subscription and refuses another BUY. For missing logs, mismatched contract IDs, or an outstanding BUY_CLAIM, the worker stops advancing pending purchases and records an explicit diagnostic phase. This is intentional protection against duplicate buys.

This fix does not automatically convert REAL mode into unattended purchases. Existing explicit REAL confirmations are unchanged.

## Known limitations

The fix is not verified against live Deriv or Render runtime. If a settlement query fails indefinitely, inspect `WAITING_OFFICIAL_SETTLEMENT_RESTORE` and Deriv account transaction history; do not force a new purchase.

## Files

Complete `app/engine.py` in this full repository ZIP. No patch scripts are required.
