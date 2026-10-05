DigitMatchStar V2.1.4 Worker Error Fix

BACKEND — upload to repository root:
- app/engine.py
- app/deriv_rest.py
- app/deriv_ws.py

FRONTEND:
- bot.html
- bot-obfuscated.html

What is fixed:
1. Server worker now shows the exact failed stage: AUTH, OTP, WEBSOCKET,
   PROPOSAL, BUY, or SETTLEMENT.
2. Failed sessions stop instead of retrying the same failure every 0.5 seconds.
3. Proposal currency now comes from the connected Deriv account instead of
   being hard-coded to USD.
4. WebSocket connection/reconnection handling is more defensive.
5. HTTP/Deriv errors are preserved in a safe diagnostic form.
6. Dashboard now displays last_error directly under Worker phase.
7. DEMO server execution remains automatic.
8. REAL purchasing remains confirmation-based.

After deployment:
- reconnect DEMO
- start the bot
- if Deriv rejects anything, the exact reason will appear in the dashboard
  rather than only showing Worker phase: ERROR.
