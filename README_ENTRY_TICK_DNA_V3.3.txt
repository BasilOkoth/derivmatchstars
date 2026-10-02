DigitMatchStar Entry Tick DNA V3.3 — DIRECT EVENT FIX

Fixes the shadow cohort capture by dispatching authoritative lifecycle events directly from bot.html:
- digitmatchstar:cycle-started at cyclePerformance.startCycle()
- digitmatchstar:cycle-finalized at cyclePerformance.completeCycle()

The shadow module listens to those events and retains polling/monkey-patch logic only as fallback.
The frozen entry filter itself is unchanged and remains SHADOW ONLY.

Test:
1. Deploy all files.
2. Hard refresh.
3. ARM FRESH 100-CYCLE SHADOW.
4. START BOT on Demo.
5. At cycle start, Current entry should populate.
6. After the first win/stop, finalized should become 1/100 and Last captured cycle should populate.
