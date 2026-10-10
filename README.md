# DigitMatchStar Render startup repair + manually confirmed REAL orders

**This is an overlay for the current GitHub repository, not a replacement of all existing project files.** Its `tools/apply_patch.py` produces full updated versions of `app/__init__.py` and `app/main.py` using the versions already in your Git checkout, preserving your newer V5–V8 patches. Do not upload the ZIP over the entire repository without applying the script.

## Install (local Git clone)
1. Copy `app/real_manual.py` and `tools/apply_patch.py` into your existing checked-out repository.
2. From the project root run `python tools/apply_patch.py`.
3. Run `python -m compileall -q app` then `python -c "import app.main; print('Import successful')"` in the existing project virtual environment with its dependencies and configuration.
4. Inspect the `git diff` and commit only `app/__init__.py`, `app/main.py`, `app/real_manual.py`. Do not commit the `.bak` backups.
5. Add Render environment variable `REAL_MANUAL_MAX_STAKE_USD=1.00` (default $1 maximum per confirmation). Keep one backend worker/process while testing; PostgreSQL row locks are required for safe concurrency.

## New authenticated endpoints
- `POST /real-manual/sessions/{sid}/quote` with `{ "digit": 5, "stake": 0.35 }` returns the fresh proposal, price, and a 30-second one-time confirmation token.
- `POST /real-manual/sessions/{sid}/confirm` with `{ "confirmation_token": "...", "confirm": true }` submits exactly one REAL order after persisting a claim.
- `GET /real-manual/sessions/{sid}/order` returns stored status plus Deriv contract status for a purchased order.

**Trading behavior**: no unattended REAL cycles, no automated REAL recovery, no automatic resubmission. This module uses Deriv's single-buy request only after explicit confirmation. If the result is uncertain, it blocks subsequent orders instead of retrying. All original DEMO behavior remains in its original engine.

## Important limitations
- No browser controls were added. The new routes can be tested through FastAPI's `/docs` with valid authentication.
- Do not use this for production funds until verified on the actual deployed code against a REAL account. We have not tested the connected Deriv API or deployed service.
- The module deliberately prevents the next REAL quote while a purchased or uncertain order remains recorded. Manual reconciliation is required to resume; an order reset endpoint is **not** provided.
- Ensure your deployed PostgreSQL schema supports `pending_trade_json`; read/verify account ownership, `account_mode`, `_request_proposal_payload`, and `_currency_for` against your actual checkout.
