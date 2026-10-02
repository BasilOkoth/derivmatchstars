DigitMatchStar Tick DNA Validation V2.4 — AUTO-RESTART FIX

ROOT CAUSE FOUND
V2.3 still had a scope mismatch:
- stopBot() lived in the core bot scope.
- overnight state lived inside the TailGuard IIFE.
- stopExistingBot(reason) also dropped the supplied reason when it called stopBot().

As a result, some normal cycle endings were indistinguishable from manual stops.

V2.4 FIX
- Overnight ON/OFF state is exposed on window for the core bot.
- Manual STOP is explicitly tagged as Manual STOP.
- Overnight OFF passes its stop reason correctly.
- Normal WIN / MAX-TRADE / tail-cycle completion keeps Overnight enabled.
- After automatic completion, startBot() is called after a 2.2 second cleanup delay.
- A 2-second watchdog independently restarts the bot if it is idle while Overnight is ON.
- DEMO-only restriction remains.
- Settlement reconciliation mismatch remains a hard stop.
- 20-trade uncensored validation remains unchanged.
- Frozen Tail Score V1 remains unchanged/shadow-only.
- IndexedDB validation persistence remains unchanged.

UPLOAD / REPLACE
1. bot.html
2. research-suite-loader.js
3. tick-dna-tail-validation-v2.js

TEST
1. Open DEMO R_10.
2. Arm the new uncensored validation if needed.
3. Click Overnight ON ONCE.
4. Do NOT press START BOT.
5. Bot should start itself.
6. Let one cycle finish.
7. Within roughly 2–4 seconds, the next cycle should start automatically.

Manual STOP or Overnight OFF must stop the loop.
