TICK DNA V1.1 FIX

This version is wired directly into the actual handleTick() and cyclePerformance
objects in the uploaded DigitMatchStar bot.

Replace/upload:
1. bot.html
2. research-suite-loader.js
3. tick-dna-tail-lab-v1.js

deriv-live-bridge.js is NOT required for Tick DNA capture in this version.

After deployment:
- hard refresh Ctrl+Shift+R
- open DEMO
- wait for live ticks
- Live tick buffer must increase above 0
- arm/reset the cohort if necessary
- when a trade cycle starts, Active cycle must change from "none" to its cycle ID
