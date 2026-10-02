DigitMatchStar Tick DNA Validation V2.2 — UNCENSORED ≥15 TEST

WHY THIS VERSION EXISTS
The previous V2.1 overnight validation accumulated 56 cycles while the bot had
Max Trades = 10. Those cycles are useful for studying "reaches trade 10", but
they cannot validate the frozen target maximumTradeDepth >= 15.

V2.2 fixes that experimental censoring problem.

WHAT V2.2 DOES
- Starts a completely NEW 100-cycle validation cohort.
- Uses a NEW IndexedDB record/key, so the previous V2.1 cohort is not mixed in.
- Enforces a 20-trade validation cycle cap while the cohort is armed.
- Keeps the frozen Tick DNA Tail Score V1 UNCHANGED.
- Keeps the score shadow-only; it never changes a trade decision.
- Supports DEMO-only overnight autopilot.
- Persists the new cohort in IndexedDB across refreshes.
- Explicitly labels exports as "uncensored".

FILES TO REPLACE
1. bot.html
2. research-suite-loader.js
3. tick-dna-tail-validation-v2.js

OPTIONAL DOCUMENTATION
- FROZEN_TAIL_SCORE_V1.json

BEFORE STARTING
1. Use DEMO / Virtual only.
2. Keep R_10 selected.
3. Confirm "Persistent storage: ✅ IndexedDB".
4. Confirm "Validation cycle cap: 20 trades 🔒".
5. Click ARM NEW 100-CYCLE ≥15 VALIDATION.
6. Turn Overnight DEMO ON if you want unattended demo testing.
7. Leave the browser open and keep the computer awake.

IMPORTANT ANALYSIS RULE
Do NOT combine the earlier 56 V2.1 cycles with this V2.2 cohort when measuring
prediction of depth >=15. The V2.1 cycles were right-censored at trade 10.

The old 56-cycle export should be retained separately as:
"V2.1 CENSORED AT 10 — auxiliary validation only."

The new V2.2 export is the actual frozen-score validation for depth >=15.
