# 100-tick live scoring + provisional-match verification patch

## Changes
- Production V1 remains limited to 100 ticks (200 stored and 200-tick challenger retained unchanged).
- Local next-tick WIN no longer sets the final FAST_WON state. It enters LOCAL_MATCH_AWAITING_OFFICIAL.
- Normal settlement updates `settlement_verified`, `barrier_matches_exit_digit`, and `local_official_mismatch` in the execution-contract snapshot.
- Deriv settled profit determines whether a locally matched contract enters OFFICIAL_WON or RECONCILE_MISMATCH.
- Repeated settled-contract notifications also handle the pending local match state.

## Important limitations
- This patch does not prove prediction accuracy, reduce the mathematical tail of losing streaks, or prove that every callback is ordered.
- Local LOSS recovery is still speculative and may open a following order before official confirmation. This is a remaining execution risk, particularly in real-money trading.
- A production-grade resolution requires contract-id-keyed lifecycle state rather than one execution-contract snapshot per session, plus integration tests against demo settlement streams.
- Do not deploy to real money before testing with demo contracts, deliberately delayed settlement events, duplicate notifications, and mismatched local/official digits.

## Validation
- Python compileall passed.
- Source checks confirmed live scorer max_history=100 and no immediate FAST_WON state assignment.
