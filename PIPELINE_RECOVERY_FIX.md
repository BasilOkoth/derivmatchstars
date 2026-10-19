# Pipeline recovery fix

- Releases a completed fast-contract owner only after authoritative settlement confirms an actual loss.
- Requires no open contract and no outstanding BUY_CLAIM; never guesses if a purchase succeeded.
- Uses the last purchased TradeLog stake to compute recovery exactly once, avoiding stake double increments.
- Uses a fresh server V1 top-ranked digit (no score threshold).
- Resumes stranded in-memory score-waiting sessions through the existing protected buy function.
- DEMO and REAL use the same account-bound purchase path and recovery engine.

Syntax validated; NOT live-tested. Stop and restart the DEMO worker if it remains on a stale Render deployment. Verify the previous contract has an authoritative Deriv settlement before expecting the next BUY.
