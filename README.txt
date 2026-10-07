DigitMatchStar — Max Trades control update
===========================================

Based on the FULL Telegram Confirmed v3.1 package.

CHANGED
- Max Trades is now truly user-defined from 1 upward.
- Removed the old browser-side forced minimum of 20 trades.
- Default fallback is 15 trades.
- START reads the current Max Trades value and sends that exact validated value to the backend.
- Backend already enforces max_trades >= 1 and stops at MAX_TRADES_REACHED.
- Target recycle remains every 3 losses and is independent of Max Trades.

REAL ACCOUNT
- REAL OAuth/account connection remains available for account/status display.
- Automated or confirmation-triggered real-money Digit Match purchases remain disabled.
- DEMO execution continues to use the complete automated server strategy.

FILES
- bot.html
- api/publish-cycle.js
- app/engine.py
- app/main.py
- app/digit_score.py
- app/deriv_ws.py
