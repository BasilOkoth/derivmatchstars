DigitMatchStar V32 — Target Attraction Export

Updated files
-------------
bot.html
app/engine.py
app/deriv_ws.py
app/main.py

New export
----------
Button: 📊 EXPORT TAE RESULTS

Endpoint:
GET /sessions/{sid}/tae/export

The JSON download contains:
- target digit
- T0 predicted P(return <= T10)
- selected/not selected
- arm threshold
- actual forward gap
- return-by-T10 label
- STOP10 label
- 12 T0 features
- model training count at T0
- aggregate forward hit rate
- selected hit rate
- selected STOP10 rate
- Brier score

Only matured forward observations are exported.
No future tick is used in the T0 feature vector.
Automated execution remains DEMO-only.
