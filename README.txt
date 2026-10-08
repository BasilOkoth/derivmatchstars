DigitMatchStar Canonical Tick ↔ Rank Sync V2

Upload:
1. app/__init__.py                         NEW FILE
2. tick-rank-sync-v1.1.js                 NEW FILE
3. research-suite-loader.js               REPLACE EXISTING FILE

Then redeploy/restart the backend and refresh the frontend.

Expected panel when synchronized:
Browser tick       digit X  e: N
Server tick        digit X  e: N
V1 #1              digit Y  e: N
Shadow pick        digit Z  e: N
NEXT target        digit Y  e: N
Badge: EXACT SAME EPOCH ✓

The open contract target remains frozen and is intentionally not required
to equal the newest V1/NEXT target.

This update changes provenance/reporting only; it does not place trades or
change the execution strategy.
