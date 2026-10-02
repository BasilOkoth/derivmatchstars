DigitMatchStar Entry Tick DNA V3.6 — DIRECT BOT CALL

Root fix:
- bot.html now calls EntryTickDNAV2.captureStart() synchronously inside cyclePerformance.startCycle().
- bot.html calls EntryTickDNAV2.captureFinalize() synchronously inside completeCycle() before current is cleared.
- Events and 200ms state polling remain only as fallback/diagnostics.
- This removes the race where a one-tick cycle can start and finish between polling intervals.

Test on DEMO:
1. Deploy ALL files in this bundle.
2. Hard refresh.
3. Panel should show Cycle source: DIRECT BOT CALL + STATE FALLBACK.
4. Arm fresh 100-cycle shadow.
5. START BOT.
6. Current entry should populate immediately at cycle start.
7. After win, finalized must become 1/100.
