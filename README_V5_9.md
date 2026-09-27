
# DigitMatchStar Premium v5.9 — Actual Target Lock + Synchronized Final P/L

Key corrections:
- Video no longer reads the changing `predictedDigit` input for target selection.
- The target digit is established only from the ACTUAL active contract / cycle.
- Before a trade target is confirmed, the video stays in scanning mode.
- Once the real target is confirmed (e.g. 4), it remains static for the whole cycle.
- Later AI recommendations cannot change the target shown in the video.
- Every streaming tick is compared against that fixed target.

Win sequence:
1. Match detected:
   - `DIGIT MATCHED`
   - `Trade N matched target X`
   - `Waiting for the bot's final Cycle P/L to update…`
2. Recorder waits for visible bot P/L to synchronize with completed cycle net P/L.
3. Final result:
   - trade number that matched
   - target digit
   - winning-trade profit
   - final Cycle P/L
4. Final synchronized result stays visible about 3.8 seconds.

All v5.8 clarity, tick comparison, moderation buttons, WebM validation and CTA features remain.

Expected health version:
premium-guided-v5.9
