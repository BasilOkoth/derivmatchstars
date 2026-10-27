# DigitMatchStar

The selected Deriv account mode (DEMO or REAL) now runs through the same server-side execution engine. Start Bot begins the session; the worker applies the shared V1 rank and margin gate, stake progression, trade-count limit, duplicate-buy claim, next-tick decision, and settlement reconciliation. Stop Bot halts new purchases.

REAL purchases use the account selected for the session. There is no separate REAL-buy confirmation control or independent per-trade stake cap. Set `ALLOW_REAL_MODE=true` in the deployed service, then set the base stake, multiplier, and maximum trades before starting. The server enforces the selected trade-count limit; the dashboard's dollar-exposure estimate is browser-side only and does not cap server purchases.

## Validation and deployment

- Run `python -m compileall -q app`.
- Run `python -c "import app.main; print('Import successful')"`.
- Test the complete flow with a DEMO account first. This workspace has not been connected to the live Deriv service, so no real-account request or deployment has been verified.
- Keep one backend worker/process while validating; the shared PostgreSQL buy claim is required to prevent duplicate purchases across overlapping workers.
- The existing database still needs its current `pending_trade_json` schema column.
