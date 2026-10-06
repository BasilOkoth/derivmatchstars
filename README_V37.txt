DigitMatchStar V37 — TAE PENDING/MATURATION FIX

Exact bug fixed
---------------
V36 successfully received dedicated server ticks, but every new T0 sample was
appended to a stale local Python list after self.tae_pending[sid] had already
been replaced with a new `still_pending` list.

Result:
- Server TAE ticks increased
- History stayed healthy
- Pending stayed 0
- Matured stayed 0/250

Fix
---
New T0 samples are now appended directly to:

    self.tae_pending[sid]

the authoritative unresolved-sample list.

Expected behavior
-----------------
With History already 100/100:
- first new server tick -> Pending 1
- next ticks -> Pending 2, 3, ... up to about 10
- on the 11th relevant observation cycle, the oldest T0 sample matures
- Matured begins increasing 1/250, 2/250, ...

The dedicated V36 research WebSocket remains unchanged.
No paid trade is needed for research maturation.
Automated execution remains DEMO-only.
