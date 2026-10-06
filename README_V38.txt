DigitMatchStar V38 — VISIBLE TAE EXPORT

What changed
------------
The TAE export function already existed in V37, but its visible button was inside
the Tail Precursor Lab / secondary panel and could easily be missed.

V38 adds two obvious export buttons:

1. Main Research Controls bar:
   📊 EXPORT TAE RESULTS
   next to EXPORT FULL DATA.

2. Directly inside the TARGET ATTRACTION ENGINE panel:
   📊 EXPORT TARGET ATTRACTION RESULTS

Both buttons call the same backend export:
GET /sessions/{sid}/tae/export

The export contains persisted matured forward-only T10 observations and current
TAE summary metrics.

Backend behavior is unchanged from V37.
Automated execution remains DEMO-only.
