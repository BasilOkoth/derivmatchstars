# Canonical V1 rank-to-execution handoff

The worker now reads the latest canonical server V1 #1 before every foreground DEMO proposal and checks the rank freshness (15 seconds). Fast-loss recovery takes the latest server V1 #1 rather than a cached next target, and rechecks it after proposal preparation, requoting if it changed. Existing purchase claims, open-contract settlement checks and REAL confirmation boundaries remain.

When no recent rank exists, `WAITING_FRESH_EXECUTION_RANK` or `WAITING_FRESH_RECOVERY_RANK` is displayed instead of purchasing on stale data.

This does NOT override `PIPELINE_ACTIVE` or skip authoritative settlement. It must be tested in DEMO; syntax validation is not an execution test.
