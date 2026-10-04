# SAFE-TICK V1 — Prospective Validation Protocol

1. Use a brand-new R_10 cohort.
2. Score every exact aligned candidate at entry.
3. Freeze the rule:
   candidateFreq25 <= 0.08 AND entropy10 <= 2.5219280948873625
4. Do not change either threshold until the cohort is finished.
5. Keep the selector SHADOW-ONLY for the first validation run.
6. For each candidate, save the SAFE-TICK decision before future outcome exists.
7. Finalize STOP10 as:
   forwardGap > 10, or no recurrence through tick 20.
8. Report at 100, 250 and 500 finalized candidates:
   - number accepted
   - selection rate
   - accepted STOP10 count/rate
   - rejected STOP10 count/rate
   - STOP10 capture rate
   - accepted tail15 count/rate
   - recurrence-depth histogram
   - simulated P/L under maxTrades=10
9. Do not retrain SAFE-TICK V1 from checkpoint results.
10. If V1 fails, close it and build SAFE-TICK V2 from a separate discovery dataset.
