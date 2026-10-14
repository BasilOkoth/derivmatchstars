# DigitMatchStar frontend stop/lifecycle correction

- `bot.html`: Continuous Research no longer sends redundant POST /stop when a cycle is already terminal. Manual STOP is limited to one in-flight request per session.
- `app/main.py`: STOP requests report previous state to Render logs; redundant stops do not overwrite a terminal phase.
- Preserves the existing guarded reconciliation in `app/engine.py` (officially settled contract required before recovery).
- Does not remove manual STOP or enable unattended REAL purchases.
- Existing sessions stuck with an unresolved contract are deliberately not force-cleared.

**Verification**: Check Render runtime logs for `DMS_STOP_REQUEST`, and confirm contract settlement is recorded before a second DEMO purchase. If requests continue, check multiple open browser tabs or another frontend deployment.
