DigitMatchStar V2 — Trigger Fusion

FULL replacement files. Built from the current settlement-safe codebase.

NEW RANKING SIGNALS
- true rolling trend velocity
- dominant digit + dominance margin
- least-frequency digit tracking
- strict AA-break detector
- strict alternating-pair-break detector
- signal agreement (0-7)
- WEAK / MODERATE / STRONG display classification
- maturity-aware F25 / F50 / F100 contributions
- digit-9 setup captured as RESEARCH-ONLY flag (no special execution bonus)

PRESERVED
- no hard entry threshold
- top-ranked eligible digit still trades
- same target for 3 attempts
- rerank + immediate failed-target exclusion after 3 losses
- 1.15x progression behavior
- user Max Trades
- exact next eligible tick FAST_WON
- pre-armed proposal execution
- Deriv proposal rate-limit protection
- background authoritative settlement
- settlement-safe Telegram WIN flow

EVIDENCE CAPTURE
Every purchased trade stores a causal score snapshot in TradeLog.raw_json under:
  dms_score_evidence

At settlement, Deriv settlement data is merged into the same raw JSON instead of
overwriting the ranking evidence. This allows later comparison of:
- score / base score / trigger bonus
- top margin
- transition1 / transition2
- trend velocity
- dominance
- break / pair triggers
- signal agreement
- strength classification
- actual settlement result and P/L

FILES
- app/digit_score.py  [UPDATED]
- app/engine.py       [UPDATED]
- bot.html            [UPDATED]
- app/main.py         [UNCHANGED current coherent version]
- app/deriv_ws.py     [UNCHANGED current coherent version]
- api/publish-cycle.js [UNCHANGED from packaged settlement-safe base]

VALIDATION
- Python syntax: PASS
- bot inline JavaScript syntax: PASS
- publisher JavaScript syntax: PASS
- scorer smoke test: PASS

IMPORTANT
The new pattern signals are ranking features, not guarantees. No hard score
threshold was added, so the trading cadence remains consistent with your
current setup.
