DigitMatchStar Entry Tick DNA V3 research bundle
================================================

WHAT IS NEW
- Keeps the existing Tick DNA Tail Validation V2.2 / 20-cap cohort code intact.
- Adds Entry Tick DNA V2 as a SEPARATE fresh forward shadow validation.
- Entry model uses T0/pre-entry information only.
- Frozen HIGH-risk rule:
    adjacentRepeats >= 1 AND 25-tick mean quote delta > 0
- HIGH means SHADOW "SKIP_CANDIDATE" only. It does NOT block a trade.

WHY SHADOW ONLY
The rule was selected after examining the prior 96-cycle cohort, where:
- baseline >=15 tail rate = 22/96 = 22.9%
- HIGH subgroup = 7/11 = 63.6%
- only 11/96 entries would have been rejected
- 7/22 tails would have been captured
These are discovery/post-hoc figures and require fresh forward validation.

HOW TO USE
1. Upload ALL files in this folder to the same site/root as bot.html.
2. Open bot.html on a Demo/Virtual account.
3. The purple "Entry Tick DNA V2 · SHADOW" panel appears at bottom-right.
4. Click "ARM FRESH 100-CYCLE SHADOW" BEFORE the new validation begins.
5. Let the bot trade normally. The shadow model never changes a trade.
6. Watch these live metrics:
   - HIGH shadow-risk tail rate
   - tail capture
   - rejected-if-active rate
   - false rejects
   - residual >=15 rate among accepted entries
7. Export JSON at 100 cycles and analyze before changing any trading logic.

FILES
- bot.html
- research-suite-loader.js
- tick-dna-tail-validation-v2.js
- FROZEN_TAIL_SCORE_V1.json
- entry-tick-dna-v2-shadow.js
- ENTRY_TICK_DNA_V2_FROZEN.json
- README_ENTRY_TICK_DNA_V3.txt

SAFETY / SCIENTIFIC NOTE
Demo-only research. The model does not establish predictability of Deriv synthetic ticks and does not guarantee profitability. Do not use the discovery rule as live trading control until a separate forward cohort confirms it.


V3.1 ARM FIX
- Demo detection now uses the bot's selectedAccountMode / accTypeToggle first.
- Fixes DOT-prefixed Demo accounts being incorrectly treated as non-demo.
- ARM button now uses a direct addEventListener and reports any failure visibly.
- window.EntryTickDNAV2.arm() is exposed for diagnostics.


V3.2 CYCLE CAPTURE FIX
- Directly hooks cyclePerformance.startCycle(), completeCycle(), and abortActiveCycle().
- Captures the first cycle immediately when CPR-3 creates it.
- Finalizes directly from the authoritative completed-cycle object.
- Keeps polling only as a fallback.
- Uses window.lastTick as a fallback if the public tick listener misses the entry tick.
- Adds visible Cycle hook and Last captured cycle diagnostics.
- Fixes maximumTradeDepth to use trades.length authoritatively.
