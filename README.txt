DigitMatchStar V1.6 — Fast Recovery Reaction + Deterministic Sound

What changed in both bot.html and bot-obfuscated.html
1. SAFE-TICK V1.5 exact-epoch alignment is preserved.
2. Recovery digit is re-ranked after EVERY confirmed loss:
   - hold length = 1
   - stale recovery lock is cleared on loss
   - next eligible trade re-scores all 10 digits.
3. Server dashboard polling reduced from 1200 ms to 250 ms.
4. Sound now keys off durable lifecycle changes:
   - new contract/trade -> execution tone
   - RECOVERING -> loss tone
   - WON -> win chord
   - MAX_TRADES_REACHED -> loss/end tone
   - ERROR -> error tone
5. Tone initializes on the first user trading gesture and queues a cue if an
   event arrives before audio is unlocked.
6. While a server contract is open, each canonical tick updates the trade-status
   UI to show that live recovery analysis is still running.

IMPORTANT EXECUTION NOTE
Secure OAuth SERVER mode still leaves the actual Deriv purchase/settlement
sequence under the backend worker. These two HTML files can make the browser
react immediately to ticks and re-rank the next digit, but they cannot make the
backend submit a new purchase before the backend decides the previous contract
has settled. Changing that actual server buy timing requires updating the
server worker/API code as well.

Validation
- bot.html and bot-obfuscated.html are byte-for-byte synchronized.
- inline JavaScript passes Node syntax checking.
