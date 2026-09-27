
# DigitMatchStar Premium v6.3 — One Target, One Dynamic Last Digit

Visual rule:
- Before Trade 1: BOT STATUS shows SCANNING DIGITS only.
- After Trade 1 confirms the actual target:
  - TARGET appears once inside BOT STATUS and stays fixed.
  - LAST DIGIT is the only digit that changes with streaming ticks.
  - Trade number and match/no-match status update alongside it.
- Removed duplicate target badge/strip from other parts of the frame.
- Removed extra target digits appearing/disappearing in different cards.
- Reclaimed the old target-strip space for a larger bot video area.

Example:
TARGET 4 | LAST DIGIT 7 | TRADE 3 | NO MATCH
TARGET 4 | LAST DIGIT 2 | TRADE 4 | NO MATCH
TARGET 4 | LAST DIGIT 4 | TRADE 5 | MATCH DETECTED

All v6.2 recovery messaging, v6.1.1 recorder fix, and one-tap Telegram moderation remain.

Expected health version: premium-guided-v6.3
