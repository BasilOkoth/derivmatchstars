# DigitMatchStar V2 live shadow integration

The current GitHub connector can read your repository but returned HTTP 403 on write, so this bundle applies the integration against the current checkout without replacing the existing bot architecture.

## Apply

From the repository root:

```bash
python apply_v2_shadow_integration.py
```

Then commit and push:

- `app/engine.py`
- `app/main.py`
- `bot.html`

The repository already contains the V2 model assets. They are also included here for completeness:

- `target_attraction_v2.py`
- `tail_risk_shadow_v2.joblib`
- `v2_metrics.json`

## What changes

After Render redeploys, `/health` should show `2.2.4-tae-v2-shadow`.

The TAE panel will show:
- V1 P(return <= T10)
- V2 P(STOP10)
- V2 risk band
- V2 validation gate
- V2 mode = SHADOW ONLY

V2 does not modify V1 entry, martingale recovery, stake sizing, or execution.
