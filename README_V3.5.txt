DigitMatchStar Entry Tick DNA V3.5 — AUTHORITATIVE STATE POLL

Fix: shadow cohort capture no longer depends on lifecycle events or monkey-patching.
It polls window.cyclePerformance.current directly and finalizes from cyclePerformance history every 200 ms.
It also hydrates entry context from window.recentMarketTicks, so the 25-tick drift feature can be calculated even if the custom tick event was missed.

Diagnostics now show:
- Cycle source: AUTHORITATIVE STATE POLL
- Authoritative state: CONNECTED
- Active bot cycle
- Shadow active cycle
- Bot history cycles
- Last captured cycle

Frozen entry rule is unchanged and remains SHADOW ONLY.
Demo only.
