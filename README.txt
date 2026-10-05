DigitMatchStar V2.2.1 — SAFE-TICK Exact Epoch Alignment

Upload:
- bot.html
- bot-obfuscated.html
- screen-recorder-safe-v5-2.js

Critical research correction

The previous V1.4 export showed entryEpoch=null and implausibly extreme
forward-gap outcomes. V1.5 corrects the measurement layer:

1. Entry T0 is admitted only when the canonical Deriv epoch exists.
2. window.lastTick.raw.epoch is now recognized.
3. The canonical digitmatchstar:tick event is authoritative.
4. Every future tick must have epoch > T0 epoch.
5. Each future Deriv epoch is counted exactly once.
6. Event + polling fallback can no longer double-count the same tick.
7. Out-of-order older ticks are rejected.
8. Export now includes forwardDigits and forwardEpochs for audit.
9. V1.5 starts a fresh validation cohort and does NOT mix the suspect V1.4
   observations with corrected data.
10. Server-mode capture uses captureLatestCanonical(), not a lightweight
    quote-only snapshot.

Expected new exports:
- entryEpoch must be a positive integer for every admitted record.
- forwardEpochs should be strictly increasing.
- forwardTicksObserved should match forwardEpochs.length.
- the candidate's own T0 epoch must never appear in forwardEpochs.
- forwardGap should equal the first 1-based position in forwardDigits where
  digit == candidateDigit.

The frozen decision rule itself is unchanged:
candidateFreq25 <= 0.08 AND entropy10 <= 2.5219280948873625

This update changes measurement/alignment only, not the SAFE-TICK rule.
