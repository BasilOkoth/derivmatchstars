# DigitMatchStar V2 — FULL FILES TO UPLOAD

These are complete files, not patches.

IMPORTANT: This build restores the full production backend dependencies and appends
the V2 research dependencies. The previous failed deployment had replaced the
production requirements with only numpy/pandas/scikit-learn/joblib.

Upload these files to the same paths in GitHub:

- `app/engine.py`
- `app/main.py`
- `bot.html`
- `requirements.txt`
- `target_attraction_v2.py`
- `tail_risk_shadow_v2.joblib`
- `v2_metrics.json`

After Render redeploys, `/health` should report:

`2.2.4-tae-v2-shadow`

The dashboard should then show:
- V1 P(return <= T10)
- V2 P(STOP10)
- V2 P(return <= T10)
- V2 risk band
- V2 validation gate
- V2 mode = SHADOW ONLY
- V2 model = shallow_hgb

V2 remains research-only and cannot authorize a trade.
