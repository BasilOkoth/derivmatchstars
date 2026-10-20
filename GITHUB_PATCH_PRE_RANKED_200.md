# Pre-ranked V1 + 200-tick shadow patch

## What changed
- Stored history and Deriv history bootstrap now retain/request **200** quotes.
- Live V1 rank uses the **last 100** digits to preserve the existing production model.
- A separate `shadow_200` snapshot scores all 200 digits for research only. It **never controls BUY**.
- Main rank selection, recovery, trade evidence fallback, and the final BUY claim now read the **latest completed rank snapshot** rather than re-running scoring.
- Setting minimum margin to `0` disables score separation waiting (while keeping rank readiness and other transaction safety gates).
- Live digit extraction now uses cached `pip_size` precision if a callback omits it.
- Existing official settlement result / exit-digit reconciliation remains intact.

## Execution timing
The tick handler still builds a new ranking once as each tick is ingested. That *completed* ranking is cached for subsequent BUY decisions. Later BUY stages do not recompute it. This eliminates duplicate computations, but **is not a dedicated concurrent ranking worker or guaranteed every-tick order placement**. The exchange settlement tick is normally later than the tick that triggers the BUY.

## Operational safety
- Use a demo account first. Do not enable live funds solely based on these tests.
- Real execution is limited by outstanding contract state, API/network latency and rate limits.
- A previous cached target is not proof of a winning probability above 10%; a longer buffer does not eliminate losing streaks.
- Existing fast local win/loss still can disagree with official settlement. The engine already detects and flags such mismatches; further work would be needed to require authoritative settlement before *every* recovery.
- Existing WebSocket callback scheduling has not been redesigned in this patch; tick processing ordering and performance should be tested under load.
- Shadow 200 output currently exists in backend ranking snapshots and is not guaranteed to appear in existing frontend panels.

## Deploy
Upload the contents of this ZIP to the same GitHub repository, replacing matching project files. Read the diff before deploying. Keep environment variables, credentials and production databases unchanged. The tests included here check source invariants only; they are not end-to-end Deriv integration tests.

Run:
`python -m unittest discover -s tests -v`
`python -m compileall -q app`
