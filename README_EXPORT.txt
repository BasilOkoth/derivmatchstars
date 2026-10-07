DigitMatchStar V2 Trigger Fusion — Persistent Export

NEW
- Dedicated "EXPORT TRIGGER FUSION DATA" button in the DigitScore V2 panel.
- New authenticated backend endpoint:
    GET /sessions/{sid}/trigger-fusion/export
- Export is generated from persisted TradeLog records in PostgreSQL.
- One click downloads BOTH:
    1. CSV — flat analysis table for Excel / R / Python
    2. JSON — complete raw evidence for reproducibility

EXPORT CONTENT
- trade/session/account/market identifiers
- target digit, stake, contract, result, settlement profit
- base score, final score, trigger bonus
- score margin and history count
- F5/F10/F25/F50/F100
- transition1 / transition2
- entropy
- gap
- trend velocity
- dominance metrics
- AA-break trigger
- alternating-pair trigger
- digit-9 research flag
- signal agreement / strength
- settlement timestamps

Persistence:
Because your deployment uses PostgreSQL through DATABASE_URL, this evidence
survives ordinary app restarts/redeploys as long as the PostgreSQL database
itself is retained.

FULL FILE PACKAGE
Upload the full files to their matching repository paths and redeploy.
