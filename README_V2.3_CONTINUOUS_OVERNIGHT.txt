DigitMatchStar Tick DNA Validation V2.3 — CONTINUOUS OVERNIGHT DEMO

FIXED
The old core stopBot() disabled Overnight after EVERY automatic cycle stop.
That forced the user to press START/Overnight again after a win or max-trade stop.

V2.3 behavior:
- Click 🌙 OVERNIGHT DEMO once.
- It starts the bot automatically on DEMO.
- When a cycle ends normally, Overnight stays ON.
- The next demo cycle starts automatically.
- This repeats while the page remains open.
- Manual STOP still turns Overnight OFF immediately.
- Turning 🌙 OVERNIGHT OFF stops continuous trading.
- Settlement reconciliation mismatch is treated as a hard fault and does NOT auto-restart.
- Frozen Tail Score V1 remains shadow-only.
- Validation cap remains 20 trades.
- IndexedDB persistence remains enabled.

UPLOAD / REPLACE
1. bot.html
2. research-suite-loader.js
3. tick-dna-tail-validation-v2.js

HOW TO USE
1. DEMO account only.
2. Confirm R_10 and validation cap 20.
3. Arm the 100-cycle validation.
4. Click 🌙 OVERNIGHT DEMO ON ONCE.
5. Leave the page open and computer awake.

Expected sequence:
Cycle starts → trades → cycle WIN/STOP → bot pauses briefly →
overnight controller automatically starts next cycle → continues collecting data.
