# DigitMatchStar: server V1 rank → DEMO purchase handoff

Replace `app/engine.py` in the existing repository with `app/engine.py` from this archive. This patch is based on the `engine_recovery_updated.py` supplied earlier in the conversation, NOT the older GitHub main file. Do not overwrite other backend files with older versions.

Changes:
- Previous-contract reconciliation retains the existing official Deriv settlement checks.
- Every new foreground DEMO proposal reads the latest canonical server-side V1 #1 digit, rather than the stale session candidate.
- Prevents proposals when no server tick has arrived for 15 seconds.
- Revalidates the chosen rank after the proposal response, before any purchase claim is made.
- Emits DMS_EXECUTION_TARGET logs with trade number, digit, stake, and feed age.
- Keeps existing buy claims and per-purchase REAL confirmation behavior unchanged.

Limitation: Recovery trade flow directly inside `_handle_strategy_tick` remains as it was; this change targets the foreground `step()` proposal path. The bot will remain blocked if contract settlement can't be verified. Python syntax validation completed; Deriv API/runtime behavior has not been tested.
