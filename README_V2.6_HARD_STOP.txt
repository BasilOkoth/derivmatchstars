DigitMatchStar Tick DNA Validation V2.6 — HARD STOP FIX

ROOT CAUSE
STOP BOT cleared the core in-memory flag but could leave the Overnight controller's
persisted state and watchdog timer active. That allowed the bot to restart.

V2.6 BEHAVIOR

OVERNIGHT ON:
- Starts DEMO trading automatically.
- Normal cycle completion restarts the next cycle automatically.
- Continues collecting validation data.

STOP BOT:
- Is now a MASTER STOP.
- Sets persisted overnightEnabled = false.
- Sets persisted autopilot enabled = false.
- Cancels the Overnight watchdog interval.
- Releases the screen wake lock.
- Clears any pending restart state.
- Stops the live bot.
- Will NOT restart until the user explicitly presses START BOT or turns Overnight ON.

OVERNIGHT OFF:
- Also stops continuous overnight trading.

UNCHANGED
- DEMO-only unattended execution.
- R_10 validation.
- 20-trade uncensored cycle cap.
- Frozen Tick DNA Tail Score V1.
- IndexedDB persistence.

UPLOAD / REPLACE
1. bot.html
2. research-suite-loader.js
3. tick-dna-tail-validation-v2.js

TEST
A. Turn Overnight ON. The bot should start itself.
B. Let a cycle end naturally. The next cycle should auto-start.
C. While running, press STOP BOT.
D. Wait at least 10 seconds. The bot must remain STOPPED and Overnight must show OFF.
E. Turn Overnight ON again. Automatic trading may resume.
