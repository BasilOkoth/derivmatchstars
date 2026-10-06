DigitMatchStar — Telegram Result Accuracy Fix

ROOT CAUSE
Telegram was publishing on FAST_WON before the winning Deriv contract had
officially settled. At that moment st.pnl could still contain the previous
negative running P/L, so the message could say WIN but show a negative "PROFIT".

FIX
1. FAST_WON still stops the strategy immediately and plays the win sound.
2. Telegram does NOT publish at FAST_WON anymore.
3. The browser remembers the exact winning contract_id.
4. app/engine.py records the authoritative Deriv settlement for each session.
5. app/main.py exposes last_settlement in /sessions.
6. bot.html waits until last_settlement.contract_id matches the FAST_WON
   contract and last_settlement.result == WIN.
7. Telegram uses last_settlement.profit for "Winning trade P/L".
8. api/publish-cycle.js no longer labels raw cycle P/L as the winning-trade
   profit. It only prints final cycle P/L when explicitly marked authoritative.

IMPORTANT
A contract can WIN while the entire cycle is still negative because earlier
losses are part of cycle P/L. The Telegram message now distinguishes those
concepts instead of calling a stale/negative cycle number the winning profit.

FULL FILES INCLUDED
- bot.html
- app/engine.py
- app/main.py
- app/digit_score.py
- app/deriv_ws.py
- api/publish-cycle.js

Upload these complete files to the same paths and redeploy both the backend
(Render) and frontend/serverless publisher deployment.
