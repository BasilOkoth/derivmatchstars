DigitMatchStar Candidate Tick DNA V3.7 — EXACT ALIGNMENT + CLOUD

What changed
1. The research target is now the exact last digit of the exact tick passed to executeTrade() before the first purchase in a cycle.
2. The outcome is measured independently from trading: future ticks are watched until that exact digit recurs, up to 20 future ticks.
3. Therefore entryTick.lastDigit/candidateDigit/targetDigit are definitionally aligned for every new record.
4. Existing trading logic is unchanged; this remains SHADOW ONLY.
5. Added generic cross-device cloud sync using the existing Upstash/Vercel KV environment variables.

Cross-device datasets synchronized
- tick-dna-tail-validation-v22-uncensored (your earlier 100-cycle validation, when present locally)
- entry-tick-dna-v2-shadow-r10 (the legacy 12-cycle entry cohort, preserved as historical data)
- candidate-tick-dna-v3-aligned-r10 (the new clean aligned cohort)

Requirements for cloud persistence
- Same authenticated owner Deriv account on both devices.
- Vercel environment already has UPSTASH_REDIS_REST_URL + UPSTASH_REDIS_REST_TOKEN, or KV_REST_API_URL + KV_REST_API_TOKEN.
- TELEGRAM_PUBLISH_ACCOUNT_IDS includes the owner account, matching the app's existing owner-only cloud pattern.

IMPORTANT
The old 12-cycle V3.6 cohort is NOT mixed into the new aligned V3.7 cohort. It is retained only as a legacy dataset.
