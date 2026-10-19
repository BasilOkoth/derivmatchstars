# Shared DEMO and REAL execution

DEMO and REAL sessions use the same server-side rank selection, V1 margin gate, direct-parameter purchase, per-trade database claim, tick-driven result handling, recovery progression, trade-count stop, and settlement reconciliation. The configured Deriv account on the session determines where a purchase is sent.

Start Bot begins execution; there is no separate per-trade REAL confirmation button or independent REAL stake cap. The user-configured base stake, multiplier, and maximum trade count control the server session. The dashboard's dollar-exposure estimate is browser-side only and does not cap server purchases.

The engine does not guarantee trade outcomes or prediction accuracy. V1 rank is a strategy signal, not a validated probability. Verify new behavior in DEMO before using a REAL account.
