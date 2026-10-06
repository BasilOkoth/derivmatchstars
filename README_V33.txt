DigitMatchStar V33 — PERSISTENT TARGET ATTRACTION ENGINE

Updated files
-------------
bot.html
app/engine.py
app/deriv_ws.py
app/main.py
app/models.py

Persistence
-----------
Two new SQLAlchemy tables are created automatically by Base.metadata.create_all():

1. tae_states
   - persisted model weights/counters
   - persisted last 100 observed digits
   - target digit
   - survives backend process restart when DATABASE_URL points to persistent storage

2. tae_observations
   - one row per matured forward-only T0 -> T10 observation
   - used by the TAE export endpoint
   - preserves research across redeploys

Strict-forward restart rule
---------------------------
Unresolved/pending T10 samples are NOT restored after a process restart.
A restart means some ticks may have been missed, so restoring those pending
labels would break strict continuity. Matured observations and the trained model
are preserved.

Dashboard
---------
The Trade Status card now shows:
- current target
- history 0/100
- pending T10 observations
- ticks until next sample matures
- matured training 0/250
- training progress bar
- observed T10 hit rate
- selected STOP10 rate
- current P(return <= T10)
- model state

The old misleading "Max Trades is held at 20" message was removed.

Export
------
The existing "EXPORT TAE RESULTS" button now exports persisted matured
observations from the backend database.

Safety
------
Automated execution remains DEMO-only.
Target Attraction estimates recurrence probability. It does not control Deriv RNG.
