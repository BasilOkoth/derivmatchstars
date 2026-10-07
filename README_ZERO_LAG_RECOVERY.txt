DigitMatchStar V2 — Zero-Lag Recovery Pipeline

PURPOSE
Reduce the delay between a losing result and the next recovery BUY, especially
at the 3-loss target-recycle boundary (e.g. Trade 18 -> Trade 19).

CHANGES
1. The exact next-loss target/stake/trade number is computed once immediately
   after the current BUY.
2. At recycle boundaries, the alternative ranked digit is chosen once and its
   proposal is requested while the current trade is still active.
3. Prefetch is scheduled BEFORE any cached result tick is dispatched.
4. Prefetch validity follows the strategy-active contract + trade number, not
   open_contract_id. Deriv settlement can therefore clear open_contract_id
   without destroying a valid recovery proposal.
5. Normal worker step() cannot start REQUESTING_PROPOSAL while an in-memory
   fast strategy contract still owns the current trade.
6. On loss, the preplanned proposal is consumed directly and BUY is sent.
7. A fresh proposal request exists only as an exceptional fallback if prefetch
   genuinely failed; it remains visibly marked FAST_RECOVERY_PREFETCH_MISSED.

PRESERVED
- Trigger Fusion V2 ranking
- 3-attempt recycle
- 1.15x stake progression behavior
- user Max Trades
- exact FAST_WON
- PostgreSQL evidence capture
- Trigger Fusion CSV/JSON export
- proposal serialization/rate-limit safeguards
- settlement-safe Telegram publishing

IMPORTANT
The network BUY request itself cannot be eliminated. This change removes the
normal proposal/scoring wait from the loss -> recovery critical path whenever
the prefetch succeeds.
