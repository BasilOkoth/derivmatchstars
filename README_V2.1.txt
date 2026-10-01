DigitMatchStar Tick DNA Validation V2.1

WHAT CHANGED
1. Persistent cohort storage moved from localStorage to IndexedDB.
2. The lab automatically migrates an old V2 localStorage cohort once, if one exists.
3. Refreshing or reopening the page restores the stored cohort.
4. Storage status is visible in the panel.
5. The lab now has a 🌙 OVERNIGHT DEMO button that calls the bot's existing overnight controller.
6. Overnight execution is DEMO-only. It never starts on a Real account.
7. The frozen Tick DNA Tail Score V1 remains shadow-only and does not alter trading.

UPLOAD / REPLACE
- bot.html
- research-suite-loader.js
- tick-dna-tail-validation-v2.js

Optional documentation:
- FROZEN_TAIL_SCORE_V1.json

HOW TO RUN OVERNIGHT
1. Login to DEMO / Virtual.
2. Keep R_10 selected.
3. Verify "Persistent storage: ✅ IndexedDB".
4. Arm the 100-cycle validation if it is not already armed.
5. Click 🌙 OVERNIGHT DEMO (or the existing top-level Overnight button).
6. Confirm the bot reports Overnight ON and DEMO trading active.
7. Leave the browser page open and the computer awake/plugged in.

IMPORTANT
- The bot already uses a screen wake-lock when supported.
- Browser/OS power-saving can still suspend a tab or the computer. Keep the computer plugged in and disable sleep for the night.
- Overnight does NOT auto-resume after a page refresh. After any refresh, explicitly click Overnight ON again.
- IndexedDB data DOES survive the refresh, so the validation cohort continues from its previous saved count.
- Use DEMO for this unattended validation. Do not switch to REAL while Overnight is enabled.
