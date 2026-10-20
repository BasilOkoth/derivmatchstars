# Strict previous-tick ranking release

This release preserves the V1 100-tick live ranking with 200 stored ticks and 200-tick research shadow scoring.

## Changes
- Before the tick is appended to scoring history, a frozen reference to the previous completed ranking is captured.
- For an active one-tick contract's local loss recovery, selection and the margin decision use the frozen previous ranking, NOT the ranking calculated from the recovery-trigger tick.
- The next ranking is calculated once for the newly received tick and published for subsequent opportunities.
- The final BUY gate accepts the chosen and locked ranking when it matches the requested digit and the CURRENT configured margin (including OFF=0) permits it. This prevents the next displayed ranking from silently replacing the purchased barrier.
- Zero margin is treated explicitly as OFF even when the rank margin is missing.
- Existing official settlement mismatch protection remains in place.

## Limitations and safe rollout
This is not a separate ranking worker, nor does it guarantee the CPU finishes ranking before the next tick. Unchanged tick-callback concurrency and in-flight BUY timing must be validated on Deriv demo before live deployment. This source patch does not guarantee trading on every tick or fewer losing trades. The ranking-based selection is still a heuristic without an independently demonstrated predictive edge.

Static source-regression tests do not substitute for real execution and settlement tests. Validate that `based_on_tick_seq < trigger_tick_seq`, record requested barrier and official exit tick, and confirm any local fast win/loss using Deriv's official contract settlement before relying on results.
