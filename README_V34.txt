DigitMatchStar V34 — CONTINUOUS PERSISTENT TAE

What this fixes
---------------
1. TAE no longer depends on the trading worker being active.
   A separate server research loop keeps a live DEMO tick subscription for
   sessions with a candidate digit, even when Trade = 0 and trading is idle.

2. Browser AI target is synchronized to the server while Trade 0 has no open
   contract. Once a paid cycle has started, the candidate stays frozen.

3. If the browser reloads, it adopts an existing backend session automatically.

4. If there is no backend session yet, the browser can create a DEMO research
   session without calling /start. This starts research only, not trading.

5. Null metrics now render truthfully:
   - no matured hit-rate data => —
   - no selected STOP10 data => —
   - no pending sample => Next sample matures: —

6. Existing persistence remains:
   - tae_states
   - tae_observations
   - matured model/records survive restart when DATABASE_URL is persistent.
   - unresolved pending T10 windows are discarded on restart to protect
     strict forward continuity.

Expected progression
--------------------
After history is ready:
Pending T10 samples rises toward ~10.
After 10 subsequent live ticks:
Matured training begins increasing continuously:
0/250, 1/250, 2/250, ...

No paid trades are required for these 250 research observations.

Safety
------
Automated execution remains DEMO-only.
TAE estimates recurrence probabilities; it does not control Deriv RNG.
