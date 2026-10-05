DigitMatchStar V2.2.0 — Continuous Research Restart + P/L Colors

Upload:
- bot.html
- bot-obfuscated.html
- screen-recorder-safe-v5-2.js

FIX 1 — Continuous DEMO Research
Previous build could remain in WON after settlement because it tried to reuse
the completed session. V2.2.0 now performs the lifecycle explicitly:

WON / MAX_TRADES_REACHED
→ wait briefly for research settlement
→ STOP completed server cycle
→ clear old session id locally
→ unlock old AI digit
→ obtain a fresh AI recommendation
→ freeze the new research candidate
→ create a fresh server session
→ START at trade 1

If AI is temporarily between recommendations, it retries for up to ~10 seconds
instead of silently remaining stopped.

Manual STOP always cancels auto-restart.

DEMO ONLY. This does not auto-start REAL-money purchases.

FIX 2 — P/L colors
- During a cycle, P/L is bold RED while no positive win has been achieved.
- When cycle P/L becomes positive / phase is WON, P/L becomes bold GREEN.
- Applies to both the main P/L metric and Server P/L.

RECORDER
Premium Recorder from V2.1.9 is retained unchanged.
