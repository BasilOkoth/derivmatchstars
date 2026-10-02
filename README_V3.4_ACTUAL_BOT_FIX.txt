DigitMatchStar Entry Tick DNA V3.4 — ACTUAL BOT EVENT WIRE

This build was made from the exact bot.html source supplied by the user on 2026-10-02, not from an older generated copy.

Root cause found:
- The supplied bot was still V3.1 ARM FIX.
- It had no digitmatchstar:cycle-started event.
- It had no digitmatchstar:cycle-finalized event.
- Therefore the shadow lab could arm and store, but had no lifecycle events to record cycles.

Fix:
1. startCycle() now dispatches digitmatchstar:cycle-started immediately after this.current is created.
2. completeCycle() now dispatches digitmatchstar:cycle-finalized before this.current is cleared.
3. The exact canonical window.lastTick is included with the start event.
4. The shadow module from V3.3 listens to these events directly.
5. Existing trading logic and frozen Entry Tick DNA V2 rule are unchanged.

Test after deploy:
- Hard refresh.
- ARM FRESH 100-CYCLE SHADOW.
- START BOT.
- At cycle start Current entry should populate.
- After first win ARMED should become 1/100 finalized and Last captured cycle should populate.
