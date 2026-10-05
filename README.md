# DigitMatchStar Server Execution Engine V1

Purpose: move the trading state machine out of `bot.html` so the session can survive
dashboard refreshes, browser throttling, and dashboard closure.

## Modes

### DEMO
- Can execute continuously on the server.
- Dashboard may be closed.
- Server reconciles any open contract after reconnect/restart.

### REAL
- Uses the same persistent server-side state machine.
- Requires `ALLOW_REAL_MODE=true`.
- Each individual purchase must be explicitly confirmed through `POST /real/confirm`.
- Closing the dashboard does NOT cancel an already purchased contract.
- No automatic real-money re-buy occurs after a settlement without the next explicit confirmation.

This design intentionally prevents unattended real-money execution while still making
the session state, contract reconciliation, and monitoring server-resident.

## Environment variables

- `DERIV_APP_ID`
- `DERIV_DEMO_TOKEN`
- `DERIV_REAL_TOKEN`
- `ALLOW_REAL_MODE=false` by default
- `DATABASE_URL`

Use Postgres for persistent production state. SQLite is fine for local testing.

## Core API

- `GET /state`
- `POST /configure`
- `POST /candidate`
- `POST /start`
- `POST /pause`
- `POST /stop`
- `POST /real/confirm`

Example configure DEMO:

```json
{
  "account_mode":"DEMO",
  "symbol":"R_10",
  "base_stake":1.0,
  "multiplier":1.15,
  "max_trades":10
}
```

Example configure REAL:

```json
{
  "account_mode":"REAL",
  "symbol":"R_10",
  "base_stake":1.0,
  "multiplier":1.15,
  "max_trades":10
}
```

## Important

Do not run the old browser purchase engine at the same time as this server engine.
Once server execution is enabled, `bot.html` should become controls + visualization only,
otherwise duplicate purchases are possible.
