DigitMatchStar — Old Stable Base + SAFE-TICK Alignment + Sound

Files:
- bot.html
- bot-obfuscated.html

Both files are intentionally synchronized from the two old-base files you supplied.

SAFE-TICK alignment correction
- V1.5 starts a NEW cohort; old V1.4 records are not mixed into it.
- T0 candidate capture now requires a real positive Deriv epoch.
- normalizeTick reads window.lastTick.raw.epoch, which was missing before.
- canonical digitmatchstar:tick events are authoritative.
- future ticks must have epoch > entryEpoch.
- event + fallback duplicates are deduplicated by Deriv epoch.
- out-of-order epochs are ignored.
- forwardEpochs and forwardDigits are stored for direct audit.
- the frozen rule itself is unchanged:
  candidateFreq25 <= 0.08
  entropy10 <= 2.5219280948873625

Sound
- Existing sound button retained.
- Saved ON/OFF preference is restored on load.
- Enabling sound initializes Tone.js after the user gesture.
- Execution sound on BUYING.
- WIN chord on WON.
- LOSS tone on RECOVERING.
- Error tone on server ERROR.
- Server polling is deduplicated so the same state does not beep repeatedly.

Validation
- Both output files are byte-for-byte synchronized.
- All inline JavaScript blocks passed Node syntax checking.
