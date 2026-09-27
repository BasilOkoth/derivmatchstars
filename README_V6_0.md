
# DigitMatchStar Premium v6.0 — Actual Trade-1 Target Only

This release removes fake/pre-trade target locks.

Rules:
1. Before Trade 1:
   - show SCANNING DIGITS
   - show no target digit
   - show no target-vs-last-digit comparison
2. At Trade 1 confirmation:
   - read actual target from active contract/cycle
   - lock it exactly once
3. During the cycle:
   - target remains static
   - every new streaming LAST DIGIT is compared against that fixed target
   - later AI recommendations cannot change the displayed target
4. On match:
   - show Trade N matched target X
   - wait for bot Cycle P/L to synchronize
5. Final result:
   - exact matching trade number
   - fixed target
   - winning trade profit
   - final Cycle P/L
   - hold for several seconds

Expected health version:
premium-guided-v6.0
