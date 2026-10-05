DigitMatchStar V2.1.7 — Server Research + Balance Fix

Upload frontend:
- bot.html
- bot-obfuscated.html

Upload backend:
- app/main.py
- app/engine.py

What this fixes

1. SAFE-TICK / Candidate DNA in SERVER mode
Browser-mode research used to start inside analyzeAndTrade() immediately before
executeTrade(). SERVER mode bypasses executeTrade(), so no research candidate
was ever created. V2.1.7 explicitly freezes window.lastTick when a NEW server
cycle starts. Future public ticks already feed the research outcome engine.

2. SAFE-TICK storage quota
SAFE-TICK persistence is moved from localStorage to IndexedDB. Existing local
research is migrated on first load when available.

3. Blank balance in secure OAuth mode
The browser intentionally has no raw Deriv OAuth token, so the old browser
balance subscription cannot authenticate. The server now exposes account_balance
and updates its balance snapshot after each settled contract. The dashboard uses
that server value.

4. Reconciliation safety retained
No new research candidate is recorded while an already-open contract is merely
being reconciled.

Notes
- Server P/L and account balance are separate metrics.
- account_balance is based on the balance captured at OAuth connection plus
  bot-settled P/L. If the same Deriv account is changed elsewhere, reconnecting
  OAuth refreshes the snapshot.
